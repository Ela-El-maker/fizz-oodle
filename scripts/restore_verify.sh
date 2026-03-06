#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
ENV_FILE="${ENV_FILE:-.env.prod}"
DB_USER="${DB_USER:-marketintel}"
BASE_URL="${BASE_URL:-http://localhost}"
API_KEY="${API_KEY:-change-me}"
OUT_FILE="${OUT_FILE:-docs/evidence/stage7/live/restore_validation.json}"

CMD=(docker compose -f "$COMPOSE_FILE")
if [[ -f "$ENV_FILE" ]]; then
  CMD+=(--env-file "$ENV_FILE")
fi

mkdir -p "$(dirname "$OUT_FILE")"

DBS=(db_agent_a db_agent_b db_agent_c db_agent_d db_agent_e db_platform_ops)
CHECKS=()
for db in "${DBS[@]}"; do
  COUNT="$("${CMD[@]}" exec -T postgres sh -lc "psql -U '$DB_USER' -d postgres -tAc \"select count(*) from pg_database where datname='${db}'\"")"
  CHECKS+=("{\"database\":\"${db}\",\"exists\":$([[ "$COUNT" == "1" ]] && echo true || echo false)}")
done

HEALTH_STATUS="unknown"
if curl -fsS -H "X-API-Key: ${API_KEY}" "${BASE_URL}/health" >/dev/null 2>&1; then
  HEALTH_STATUS="ok"
else
  HEALTH_STATUS="fail"
fi

{
  echo "{"
  echo "  \"verified_at_utc\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\","
  echo "  \"health_status\": \"${HEALTH_STATUS}\","
  echo "  \"databases\": [$(IFS=,; echo "${CHECKS[*]}")]"
  echo "}"
} > "$OUT_FILE"

echo "$OUT_FILE"
