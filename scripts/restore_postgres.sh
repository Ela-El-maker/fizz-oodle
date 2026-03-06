#!/usr/bin/env bash
set -euo pipefail

BACKUP_FILE="${1:-}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
ENV_FILE="${ENV_FILE:-.env.prod}"
DB_USER="${DB_USER:-marketintel}"
BACKUP_ENCRYPTION_KEY="${BACKUP_ENCRYPTION_KEY:-}"
RESTORE_DROP_EXISTING="${RESTORE_DROP_EXISTING:-true}"

if [[ -z "$BACKUP_FILE" || ! -f "$BACKUP_FILE" ]]; then
  echo "ERROR: backup file path is required" >&2
  exit 1
fi

if [[ -z "$BACKUP_ENCRYPTION_KEY" ]]; then
  echo "ERROR: BACKUP_ENCRYPTION_KEY is required" >&2
  exit 1
fi

CMD=(docker compose -f "$COMPOSE_FILE")
if [[ -f "$ENV_FILE" ]]; then
  CMD+=(--env-file "$ENV_FILE")
fi

if [[ "$RESTORE_DROP_EXISTING" == "true" ]]; then
  "${CMD[@]}" exec -T postgres sh -lc "psql -U '$DB_USER' -d postgres -v ON_ERROR_STOP=1 <<'SQL'
DROP DATABASE IF EXISTS db_agent_a;
DROP DATABASE IF EXISTS db_agent_b;
DROP DATABASE IF EXISTS db_agent_c;
DROP DATABASE IF EXISTS db_agent_d;
DROP DATABASE IF EXISTS db_agent_e;
DROP DATABASE IF EXISTS db_platform_ops;
CREATE DATABASE db_agent_a;
CREATE DATABASE db_agent_b;
CREATE DATABASE db_agent_c;
CREATE DATABASE db_agent_d;
CREATE DATABASE db_agent_e;
CREATE DATABASE db_platform_ops;
SQL"
fi

openssl enc -d -aes-256-cbc -pbkdf2 -pass env:BACKUP_ENCRYPTION_KEY -in "$BACKUP_FILE" \
  | gunzip -c \
  | "${CMD[@]}" exec -T postgres sh -lc "psql -U '$DB_USER' -d postgres -v ON_ERROR_STOP=1"

echo "Restore completed from $BACKUP_FILE"
