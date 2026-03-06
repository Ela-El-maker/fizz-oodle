#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.staging.yml}"
ENV_FILE="${ENV_FILE:-.env.staging}"
BASE_URL="${BASE_URL:-http://localhost}"
API_KEY="${API_KEY:-change-me}"
OUT_DIR="${OUT_DIR:-docs/evidence/stage7/live}"
INTERNAL_API_KEY="${INTERNAL_API_KEY:-internal-change-me}"

mkdir -p "$OUT_DIR"

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "ERROR: $1 is required" >&2
    exit 1
  fi
}

require_cmd jq
require_cmd curl

COMPOSE=(docker compose -f "$COMPOSE_FILE")
if [[ -f "$ENV_FILE" ]]; then
  COMPOSE+=(--env-file "$ENV_FILE")
fi

echo "[stage7] validating config and drift"
python scripts/validate_configs.py
python scripts/check_drift.py

echo "[stage7] starting stack"
"${COMPOSE[@]}" up -d postgres redis run-ledger-service agent-a-service agent-b-service agent-c-service agent-d-service agent-e-service scheduler-service gateway-service prometheus alertmanager grafana

echo "[stage7] waiting for gateway health"
for _ in $(seq 1 120); do
  if curl -fsS -H "X-API-Key: $API_KEY" "$BASE_URL/health" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

echo "[stage7] collecting base evidence"
curl -sS -H "X-API-Key: $API_KEY" "$BASE_URL/health" > "$OUT_DIR/health.json"
curl -sS -H "X-API-Key: $API_KEY" "$BASE_URL/runs?limit=200" > "$OUT_DIR/runs_window.json"

"${COMPOSE[@]}" exec -T scheduler-service python - <<PY > "$OUT_DIR/scheduler_dispatch.json"
import json
import urllib.request
req = urllib.request.Request("http://localhost:8010/internal/schedules", headers={"X-Internal-Api-Key": "${INTERNAL_API_KEY}"})
with urllib.request.urlopen(req, timeout=15) as r:
    print(r.read().decode())
PY

echo "[stage7] llm off validation"
"${COMPOSE[@]}" exec -T gateway-service python - <<PY > "$OUT_DIR/llm_off_validation.json"
import json
import os
print(json.dumps({"llm_mode": os.getenv("LLM_MODE", ""), "llm_off": os.getenv("LLM_MODE", "").lower() == "off"}, indent=2))
PY

echo "[stage7] trigger automated email validation windows"
curl -sS -X POST -H "X-API-Key: $API_KEY" "$BASE_URL/admin/email-validation/run?window=daily&force=true" > "$OUT_DIR/email_validation_trigger_daily.json"
curl -sS -X POST -H "X-API-Key: $API_KEY" "$BASE_URL/admin/email-validation/run?window=weekly&force=true" > "$OUT_DIR/email_validation_trigger_weekly.json"
curl -sS -H "X-API-Key: $API_KEY" "$BASE_URL/email-validation/latest?window=daily" > "$OUT_DIR/daily_validation_latest.json" || true
curl -sS -H "X-API-Key: $API_KEY" "$BASE_URL/email-validation/latest?window=weekly" > "$OUT_DIR/weekly_validation_latest.json" || true

post_run() {
  local url="$1"
  local out="$2"
  curl -sS -X POST -H "X-API-Key: $API_KEY" "$url" > "$out"
  jq -r '.run_id // empty' "$out"
}

wait_terminal() {
  local rid="$1"
  local agent="$2"
  for _ in $(seq 1 120); do
    local st
    st="$(curl -sS -H "X-API-Key: $API_KEY" "$BASE_URL/runs?agent_name=${agent}&limit=100" | jq -r --arg rid "$rid" '.items[] | select(.run_id==$rid) | .status' | head -n1 || true)"
    if [[ "$st" == "success" || "$st" == "partial" || "$st" == "fail" ]]; then
      echo "$st"
      return 0
    fi
    sleep 2
  done
  echo "unknown"
  return 1
}

echo "[stage7] controlled degraded-path drill"
RID_PARTIAL="$(post_run "$BASE_URL/run/archivist?run_type=weekly&period_key=2000-01-03" "$OUT_DIR/trigger_partial.json")"
ST_PARTIAL="$(wait_terminal "$RID_PARTIAL" "archivist" || true)"

echo "[stage7] test alert injection"
"${COMPOSE[@]}" exec -T gateway-service python - <<PY > "$OUT_DIR/alerts_fired.json"
import json
import urllib.request
payload = json.dumps([
  {
    "labels": {"alertname": "Stage7GateTestAlert", "severity": "info"},
    "annotations": {"summary": "Stage 7 gate test alert", "description": "Synthetic alert to validate Alertmanager path"}
  }
]).encode()
req = urllib.request.Request("http://alertmanager:9093/api/v2/alerts", data=payload, headers={"Content-Type": "application/json"}, method="POST")
with urllib.request.urlopen(req, timeout=15) as r:
    print(json.dumps({"status": r.status}, indent=2))
PY

echo "[stage7] backup + restore drills"
BACKUP_OUT="$(COMPOSE_FILE="$COMPOSE_FILE" ENV_FILE="$ENV_FILE" BACKUP_DIR="backups" ./scripts/backup_postgres.sh | head -n1)"
MANIFEST="$(ls -1t backups/*.manifest.json | head -n1)"
cp "$MANIFEST" "$OUT_DIR/backup_manifest.json"
if [[ -n "${S3_BUCKET:-}" ]]; then
  ./scripts/backup_upload_s3.sh "$BACKUP_OUT" >/dev/null
  ./scripts/backup_retention_prune.sh >/dev/null
fi
COMPOSE_FILE="$COMPOSE_FILE" ENV_FILE="$ENV_FILE" ./scripts/restore_postgres.sh "$BACKUP_OUT"
COMPOSE_FILE="$COMPOSE_FILE" ENV_FILE="$ENV_FILE" BASE_URL="$BASE_URL" API_KEY="$API_KEY" OUT_FILE="$OUT_DIR/restore_validation.json" ./scripts/restore_verify.sh >/dev/null

echo "[stage7] rollback validation capture"
cat > "$OUT_DIR/rollback_validation.json" <<JSON
{
  "validated_at_utc": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "strategy": "tag rollback",
  "status": "documented",
  "notes": "Use docs/runbooks/ROLLBACK.md procedure with previous immutable image tags."
}
JSON

cat > "$OUT_DIR/degraded_drill_status.json" <<JSON
{
  "run_id": "${RID_PARTIAL}",
  "status": "${ST_PARTIAL}"
}
JSON

echo "[stage7] complete: evidence in $OUT_DIR"
