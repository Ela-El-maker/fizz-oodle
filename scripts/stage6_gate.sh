#!/usr/bin/env bash
set -euo pipefail

API_KEY="${API_KEY:-change-me}"
BASE_URL="${BASE_URL:-http://localhost:8000}"
OUT_DIR="${OUT_DIR:-docs/evidence/stage6/live}"
INTERNAL_API_KEY="${INTERNAL_API_KEY:-internal-change-me}"

if ! command -v jq >/dev/null 2>&1; then
  echo "ERROR: jq is required" >&2
  exit 1
fi

mkdir -p "$OUT_DIR"

post_json_retry() {
  local url="$1"
  local out_file="$2"
  local response=""
  for _ in $(seq 1 30); do
    response="$(curl -sS -X POST "$url" -H "X-API-Key: $API_KEY" || true)"
    if echo "$response" | jq -e . >/dev/null 2>&1; then
      echo "$response" > "$out_file"
      return 0
    fi
    sleep 2
  done
  echo "$response" > "$out_file"
  return 1
}

wait_terminal_run() {
  local run_id="$1"
  for _ in $(seq 1 120); do
    local status_val
    status_val="$(
      curl -sS -H "X-API-Key: $API_KEY" "$BASE_URL/runs?agent_name=archivist&limit=100" 2>/dev/null \
        | jq -r --arg rid "$run_id" '.items[] | select(.run_id==$rid) | .status' 2>/dev/null \
        | head -n1 || true
    )"
    if [[ "$status_val" == "success" || "$status_val" == "partial" || "$status_val" == "fail" ]]; then
      echo "$status_val"
      return 0
    fi
    sleep 2
  done
  echo "unknown"
  return 1
}

capture_stream_json() {
  local stream_name="$1"
  local out_file="$2"
  docker compose exec -T gateway-service python - "$stream_name" <<'PY' > "$out_file"
import asyncio
import json
import sys
from redis.asyncio import Redis
from apps.core.config import get_settings

stream = sys.argv[1]
settings = get_settings()

def decode(value):
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)

async def main():
    client = Redis.from_url(settings.REDIS_URL, decode_responses=False)
    try:
        entries = await client.xrevrange(stream, count=10)
        out = []
        for msg_id, payload in entries:
            row = {"event_id": decode(msg_id)}
            for k, v in payload.items():
                key = decode(k)
                raw = decode(v)
                try:
                    row[key] = json.loads(raw)
                except Exception:
                    row[key] = raw
            out.append(row)
        print(json.dumps({"stream": stream, "items": out}, indent=2))
    finally:
        await client.aclose()

asyncio.run(main())
PY
}

echo "[stage6-gate] ensuring microservices stack is up"
docker compose up -d postgres redis run-ledger-service agent-a-service agent-b-service agent-c-service agent-d-service agent-e-service scheduler-service gateway-service >/dev/null

echo "[stage6-gate] running canonical guardrails"
python scripts/validate_configs.py
python scripts/check_drift.py

echo "[stage6-gate] waiting for API readiness"
for _ in $(seq 1 90); do
  if curl -fsS -H "X-API-Key: $API_KEY" "$BASE_URL/health" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

echo "[stage6-gate] trigger archivist weekly run"
post_json_retry "$BASE_URL/run/archivist" "$OUT_DIR/trigger_weekly.json"
WEEKLY_RUN_ID="$(jq -r '.run_id // empty' "$OUT_DIR/trigger_weekly.json")"
WEEKLY_STATUS="$(wait_terminal_run "$WEEKLY_RUN_ID" || true)"

echo "[stage6-gate] trigger archivist monthly run"
post_json_retry "$BASE_URL/run/archivist?run_type=monthly" "$OUT_DIR/trigger_monthly.json"
MONTHLY_RUN_ID="$(jq -r '.run_id // empty' "$OUT_DIR/trigger_monthly.json")"
MONTHLY_STATUS="$(wait_terminal_run "$MONTHLY_RUN_ID" || true)"

echo "[stage6-gate] trigger degraded partial archivist run"
post_json_retry "$BASE_URL/run/archivist?run_type=weekly&period_key=2000-01-03" "$OUT_DIR/trigger_partial.json"
PARTIAL_RUN_ID="$(jq -r '.run_id // empty' "$OUT_DIR/trigger_partial.json")"
PARTIAL_STATUS="$(wait_terminal_run "$PARTIAL_RUN_ID" || true)"

echo "[stage6-gate] verify strict DB ownership"
docker compose exec -T gateway-service python scripts/verify_microservice_db_ownership.py > "$OUT_DIR/db_ownership.json"

echo "[stage6-gate] capture evidence"
curl -sS -H "X-API-Key: $API_KEY" "$BASE_URL/health" > "$OUT_DIR/health.json"
curl -sS -H "X-API-Key: $API_KEY" "$BASE_URL/runs?agent_name=archivist&limit=50" > "$OUT_DIR/runs_latest.json"
curl -sS -H "X-API-Key: $API_KEY" "$BASE_URL/patterns/summary" > "$OUT_DIR/patterns_summary.json"
curl -sS -H "X-API-Key: $API_KEY" "$BASE_URL/patterns/active?limit=100" > "$OUT_DIR/patterns_active.json"
curl -sS -H "X-API-Key: $API_KEY" "$BASE_URL/impacts/other" > "$OUT_DIR/impact_other.json" || true
curl -sS -H "X-API-Key: $API_KEY" "$BASE_URL/archive/latest?run_type=weekly" > "$OUT_DIR/archive_latest_weekly.json" || true
curl -sS -H "X-API-Key: $API_KEY" "$BASE_URL/archive/latest?run_type=monthly" > "$OUT_DIR/archive_latest_monthly.json" || true
capture_stream_json "archivist.patterns.updated.v1" "$OUT_DIR/events_archivist_patterns_updated.json"
capture_stream_json "analyst.report.generated.v1" "$OUT_DIR/events_analyst_report_generated.json"

cat > "$OUT_DIR/run_statuses.json" <<EOF
{
  "weekly": {"run_id": "$WEEKLY_RUN_ID", "status": "$WEEKLY_STATUS"},
  "monthly": {"run_id": "$MONTHLY_RUN_ID", "status": "$MONTHLY_STATUS"},
  "partial": {"run_id": "$PARTIAL_RUN_ID", "status": "$PARTIAL_STATUS"}
}
EOF

echo "[stage6-gate] done"
echo "  weekly run:  $WEEKLY_RUN_ID"
echo "  monthly run: $MONTHLY_RUN_ID"
echo "  partial run: $PARTIAL_RUN_ID"
echo "  evidence dir: $OUT_DIR"
