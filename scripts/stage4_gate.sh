#!/usr/bin/env bash
set -euo pipefail

API_KEY="${API_KEY:-change-me}"
BASE_URL="${BASE_URL:-http://localhost:8000}"
OUT_DIR="${OUT_DIR:-docs/evidence/stage4/live}"

if ! command -v jq >/dev/null 2>&1; then
  echo "ERROR: jq is required" >&2
  exit 1
fi

mkdir -p "$OUT_DIR"

echo "[stage4-gate] ensuring stack is up"
docker compose up -d --build api worker beat postgres redis >/dev/null

echo "[stage4-gate] running migrations"
docker compose exec -T api alembic upgrade head >/dev/null

echo "[stage4-gate] running canonical guardrails"
python scripts/validate_configs.py
python scripts/check_drift.py

echo "[stage4-gate] waiting for API readiness"
for _ in $(seq 1 60); do
  if curl -fsS -H "X-API-Key: $API_KEY" "$BASE_URL/health" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

echo "[stage4-gate] resetting source breaker state"
curl -sS -X POST "$BASE_URL/admin/sentiment/sources/reset?api_key=$API_KEY" > "$OUT_DIR/reset_sources_response.json"

echo "[stage4-gate] triggering success-path sentiment run"
curl -sS -X POST "$BASE_URL/admin/sentiment/trigger?api_key=$API_KEY" > "$OUT_DIR/trigger_response.json"
SUCCESS_TRIGGER_RUN_ID="$(jq -r '.run_id' "$OUT_DIR/trigger_response.json")"

for _ in $(seq 1 60); do
  STATUS="$(curl -sS -H "X-API-Key: $API_KEY" "$BASE_URL/runs?agent_name=sentiment&limit=20" \
    | jq -r --arg rid "$SUCCESS_TRIGGER_RUN_ID" '.items[] | select(.run_id==$rid) | .status' | head -n1)"
  if [[ "$STATUS" == "success" || "$STATUS" == "partial" || "$STATUS" == "fail" ]]; then
    break
  fi
  sleep 2
done

echo "[stage4-gate] capturing main evidence bundle"
curl -sS -H "X-API-Key: $API_KEY" "$BASE_URL/health" > "$OUT_DIR/health.json"
curl -sS -H "X-API-Key: $API_KEY" "$BASE_URL/runs?agent_name=sentiment&limit=30" > "$OUT_DIR/runs_latest.json"
curl -sS -H "X-API-Key: $API_KEY" "$BASE_URL/sentiment/weekly" > "$OUT_DIR/sentiment_weekly.json"
curl -sS -H "X-API-Key: $API_KEY" "$BASE_URL/sentiment/sources/health" > "$OUT_DIR/sentiment_sources_health.json"
curl -sS -H "X-API-Key: $API_KEY" "$BASE_URL/sentiment/digest/latest" > "$OUT_DIR/sentiment_digest_latest.json"
curl -sS -H "X-API-Key: $API_KEY" "$BASE_URL/v1/sentiment/latest" > "$OUT_DIR/sentiment_legacy_latest.json"
curl -sS "$BASE_URL/admin/sentiment?api_key=$API_KEY&limit=100" > "$OUT_DIR/admin_sentiment_snapshot_live.html"
docker compose logs --tail=200 worker > "$OUT_DIR/compose_logs_tail.txt"
curl -sS -H "X-API-Key: $API_KEY" "$BASE_URL/runs?agent_name=sentiment&limit=50" \
  | jq '{item: (first(.items[] | select(.status=="success")))}' > "$OUT_DIR/runs_success.json"

echo "[stage4-gate] forcing deterministic partial-run scenario"
docker compose exec -T postgres psql -U marketintel -d market_intel -v ON_ERROR_STOP=1 >/dev/null <<'SQL'
INSERT INTO source_health (source_id, last_success_at, last_failure_at, consecutive_failures, breaker_state, cooldown_until, last_metrics)
VALUES ('bbc_business_rss', now(), now(), 5, 'open', now() + interval '30 minutes', '{"forced_for_stage4_partial": true}'::jsonb)
ON CONFLICT (source_id)
DO UPDATE SET
  consecutive_failures = 5,
  breaker_state = 'open',
  cooldown_until = now() + interval '30 minutes',
  last_failure_at = now(),
  last_metrics = coalesce(source_health.last_metrics, '{}'::jsonb) || '{"forced_for_stage4_partial": true}'::jsonb;
SQL

curl -sS -X POST "$BASE_URL/admin/sentiment/trigger?api_key=$API_KEY" > "$OUT_DIR/trigger_response_partial.json"
PARTIAL_RUN_ID="$(jq -r '.run_id' "$OUT_DIR/trigger_response_partial.json")"

for _ in $(seq 1 60); do
  STATUS="$(curl -sS -H "X-API-Key: $API_KEY" "$BASE_URL/runs?agent_name=sentiment&limit=30" \
    | jq -r --arg rid "$PARTIAL_RUN_ID" '.items[] | select(.run_id==$rid) | .status' | head -n1)"
  if [[ "$STATUS" == "success" || "$STATUS" == "partial" || "$STATUS" == "fail" ]]; then
    break
  fi
  sleep 2
done

curl -sS -H "X-API-Key: $API_KEY" "$BASE_URL/runs?agent_name=sentiment&limit=30" \
  | jq --arg rid "$PARTIAL_RUN_ID" '{item: (.items[] | select(.run_id==$rid))}' > "$OUT_DIR/runs_partial.json"
curl -sS -H "X-API-Key: $API_KEY" "$BASE_URL/sentiment/sources/health" > "$OUT_DIR/sentiment_sources_health_partial.json"
curl -sS -H "X-API-Key: $API_KEY" "$BASE_URL/health" > "$OUT_DIR/health_partial.json"

echo "[stage4-gate] resetting source breaker state after partial scenario"
curl -sS -X POST "$BASE_URL/admin/sentiment/sources/reset?api_key=$API_KEY" > "$OUT_DIR/reset_sources_response_after_partial.json"

echo "[stage4-gate] done"
echo "  success run: $(jq -r '.item.run_id // empty' "$OUT_DIR/runs_success.json")"
echo "  partial run: $(jq -r '.item.run_id // empty' "$OUT_DIR/runs_partial.json")"
echo "  evidence dir: $OUT_DIR"
