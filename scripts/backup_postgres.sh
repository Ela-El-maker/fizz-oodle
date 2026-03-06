#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
ENV_FILE="${ENV_FILE:-.env.prod}"
BACKUP_DIR="${BACKUP_DIR:-backups}"
DB_USER="${DB_USER:-marketintel}"
BACKUP_ENCRYPTION_KEY="${BACKUP_ENCRYPTION_KEY:-}"

if [[ -z "$BACKUP_ENCRYPTION_KEY" ]]; then
  echo "ERROR: BACKUP_ENCRYPTION_KEY is required" >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_FILE="$BACKUP_DIR/postgres-all-${TS}.sql.gz.enc"
MANIFEST_FILE="$BACKUP_DIR/postgres-all-${TS}.manifest.json"

CMD=(docker compose -f "$COMPOSE_FILE")
if [[ -f "$ENV_FILE" ]]; then
  CMD+=(--env-file "$ENV_FILE")
fi

"${CMD[@]}" exec -T postgres sh -lc "pg_dumpall -U '$DB_USER'" \
  | gzip -c \
  | openssl enc -aes-256-cbc -pbkdf2 -salt -pass env:BACKUP_ENCRYPTION_KEY \
  > "$OUT_FILE"

SHA256="$(sha256sum "$OUT_FILE" | awk '{print $1}')"
SIZE_BYTES="$(wc -c < "$OUT_FILE" | tr -d ' ')"

cat > "$MANIFEST_FILE" <<JSON
{
  "created_at_utc": "${TS}",
  "backup_file": "${OUT_FILE}",
  "sha256": "${SHA256}",
  "size_bytes": ${SIZE_BYTES},
  "compose_file": "${COMPOSE_FILE}",
  "env_file": "${ENV_FILE}"
}
JSON

echo "$OUT_FILE"
echo "$MANIFEST_FILE"
