#!/usr/bin/env bash
set -euo pipefail

API_KEY="${API_KEY:-change-me}"
BASE_URL="${BASE_URL:-http://localhost:8000}"
OUT_DIR="${OUT_DIR:-docs/evidence/stage5/live}"

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

echo "[stage5-gate] ensuring stack is up"
docker compose up -d --build postgres redis run-ledger-service agent-a-service agent-b-service agent-c-service agent-d-service agent-e-service scheduler-service gateway-service >/dev/null

echo "[stage5-gate] running canonical guardrails"
python scripts/validate_configs.py
python scripts/check_drift.py

echo "[stage5-gate] waiting for API readiness"
for _ in $(seq 1 60); do
  if curl -fsS -H "X-API-Key: $API_KEY" "$BASE_URL/health" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

echo "[stage5-gate] trigger daily analyst run"
post_json_retry "$BASE_URL/admin/reports/trigger?report_type=daily" "$OUT_DIR/trigger_daily.json"
DAILY_RUN_ID="$(jq -r '.result.run_id // .run_id // empty' "$OUT_DIR/trigger_daily.json")"

for _ in $(seq 1 60); do
  STATUS="$(
    curl -sS -H "X-API-Key: $API_KEY" "$BASE_URL/runs?agent_name=analyst&limit=30" 2>/dev/null \
      | jq -r --arg rid "$DAILY_RUN_ID" '.items[] | select(.run_id==$rid) | .status' 2>/dev/null \
      | head -n1 || true
  )"
  if [[ "$STATUS" == "success" || "$STATUS" == "partial" || "$STATUS" == "fail" ]]; then
    break
  fi
  sleep 2
done

echo "[stage5-gate] trigger weekly analyst run"
post_json_retry "$BASE_URL/admin/reports/trigger?report_type=weekly" "$OUT_DIR/trigger_weekly.json"
WEEKLY_RUN_ID="$(jq -r '.result.run_id // .run_id // empty' "$OUT_DIR/trigger_weekly.json")"

for _ in $(seq 1 60); do
  STATUS="$(
    curl -sS -H "X-API-Key: $API_KEY" "$BASE_URL/runs?agent_name=analyst&limit=30" 2>/dev/null \
      | jq -r --arg rid "$WEEKLY_RUN_ID" '.items[] | select(.run_id==$rid) | .status' 2>/dev/null \
      | head -n1 || true
  )"
  if [[ "$STATUS" == "success" || "$STATUS" == "partial" || "$STATUS" == "fail" ]]; then
    break
  fi
  sleep 2
done

echo "[stage5-gate] force degraded partial run with historical period"
post_json_retry "$BASE_URL/admin/reports/trigger?report_type=daily&period_key=2000-01-01" "$OUT_DIR/trigger_partial.json"
PARTIAL_RUN_ID="$(jq -r '.result.run_id // .run_id // empty' "$OUT_DIR/trigger_partial.json")"

for _ in $(seq 1 60); do
  STATUS="$(
    curl -sS -H "X-API-Key: $API_KEY" "$BASE_URL/runs?agent_name=analyst&limit=50" 2>/dev/null \
      | jq -r --arg rid "$PARTIAL_RUN_ID" '.items[] | select(.run_id==$rid) | .status' 2>/dev/null \
      | head -n1 || true
  )"
  if [[ "$STATUS" == "success" || "$STATUS" == "partial" || "$STATUS" == "fail" ]]; then
    break
  fi
  sleep 2
done

echo "[stage5-gate] capturing evidence"
curl -sS -H "X-API-Key: $API_KEY" "$BASE_URL/health" > "$OUT_DIR/health.json"
curl -sS -H "X-API-Key: $API_KEY" "$BASE_URL/runs?agent_name=analyst&limit=50" > "$OUT_DIR/runs_latest.json"
curl -sS -H "X-API-Key: $API_KEY" "$BASE_URL/reports/latest?type=daily" > "$OUT_DIR/reports_latest_daily.json"
curl -sS -H "X-API-Key: $API_KEY" "$BASE_URL/reports/latest?type=weekly" > "$OUT_DIR/reports_latest_weekly.json"
curl -sS -H "X-API-Key: $API_KEY" "$BASE_URL/reports?limit=100" > "$OUT_DIR/reports_list.json"
curl -sS -H "X-API-Key: $API_KEY" "$BASE_URL/admin/reports?limit=100" > "$OUT_DIR/admin_reports_snapshot_live.html"
curl -sS -H "X-API-Key: $API_KEY" "$BASE_URL/runs?agent_name=analyst&limit=50" \
  | jq --arg rid "$PARTIAL_RUN_ID" '{item: (.items[] | select(.run_id==$rid))}' > "$OUT_DIR/runs_partial.json"

echo "[stage5-gate] done"
echo "  daily run:   $DAILY_RUN_ID"
echo "  weekly run:  $WEEKLY_RUN_ID"
echo "  partial run: $PARTIAL_RUN_ID"
echo "  evidence dir: $OUT_DIR"
