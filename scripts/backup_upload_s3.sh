#!/usr/bin/env bash
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-backups}"
FILE_PATH="${1:-}"
S3_BUCKET="${S3_BUCKET:-}"
S3_PREFIX="${S3_PREFIX:-market-intel}"
S3_ENDPOINT_URL="${S3_ENDPOINT_URL:-}"
S3_REGION="${S3_REGION:-us-east-1}"

if ! command -v aws >/dev/null 2>&1; then
  echo "ERROR: aws CLI is required" >&2
  exit 1
fi

if [[ -z "$S3_BUCKET" ]]; then
  echo "ERROR: S3_BUCKET is required" >&2
  exit 1
fi

if [[ -z "$FILE_PATH" ]]; then
  FILE_PATH="$(ls -1t "$BACKUP_DIR"/*.enc 2>/dev/null | head -n1 || true)"
fi

if [[ -z "$FILE_PATH" || ! -f "$FILE_PATH" ]]; then
  echo "ERROR: backup file not found" >&2
  exit 1
fi

BASENAME="$(basename "$FILE_PATH")"
TARGET="s3://${S3_BUCKET}/${S3_PREFIX}/${BASENAME}"
AWS_ARGS=(--region "$S3_REGION")
if [[ -n "$S3_ENDPOINT_URL" ]]; then
  AWS_ARGS+=(--endpoint-url "$S3_ENDPOINT_URL")
fi

aws "${AWS_ARGS[@]}" s3 cp "$FILE_PATH" "$TARGET"

MANIFEST="${FILE_PATH%.enc}.manifest.json"
if [[ -f "$MANIFEST" ]]; then
  aws "${AWS_ARGS[@]}" s3 cp "$MANIFEST" "s3://${S3_BUCKET}/${S3_PREFIX}/$(basename "$MANIFEST")"
fi

echo "$TARGET"
