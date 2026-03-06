#!/usr/bin/env bash
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-backups}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"
S3_BUCKET="${S3_BUCKET:-}"
S3_PREFIX="${S3_PREFIX:-market-intel}"
S3_ENDPOINT_URL="${S3_ENDPOINT_URL:-}"
S3_REGION="${S3_REGION:-us-east-1}"

find "$BACKUP_DIR" -type f -name '*.enc' -mtime "+${RETENTION_DAYS}" -delete || true
find "$BACKUP_DIR" -type f -name '*.manifest.json' -mtime "+${RETENTION_DAYS}" -delete || true

if [[ -n "$S3_BUCKET" ]] && command -v aws >/dev/null 2>&1 && command -v jq >/dev/null 2>&1; then
  AWS_ARGS=(--region "$S3_REGION")
  if [[ -n "$S3_ENDPOINT_URL" ]]; then
    AWS_ARGS+=(--endpoint-url "$S3_ENDPOINT_URL")
  fi

  CUTOFF="$(date -u -d "-${RETENTION_DAYS} days" +%Y-%m-%dT%H:%M:%SZ)"
  aws "${AWS_ARGS[@]}" s3api list-objects-v2 --bucket "$S3_BUCKET" --prefix "$S3_PREFIX/" \
    | jq -r --arg cutoff "$CUTOFF" '.Contents[]? | select(.LastModified < $cutoff) | .Key' \
    | while read -r key; do
        [[ -z "$key" ]] && continue
        aws "${AWS_ARGS[@]}" s3 rm "s3://${S3_BUCKET}/${key}"
      done
fi

echo "Retention prune completed"
