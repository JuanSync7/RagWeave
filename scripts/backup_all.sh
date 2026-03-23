#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/container-runtime.sh"

STAMP="${1:-$(date +%Y%m%d-%H%M%S)}"
OUT_DIR="${BACKUP_DIR:-./backups}/$STAMP"
mkdir -p "$OUT_DIR"

echo "[backup] writing backups into $OUT_DIR"

$CONTAINER_RT exec rag-temporal-db pg_dump -U temporal temporal > "$OUT_DIR/temporal.sql"

if $CONTAINER_RT ps --format '{{.Names}}' | rg -q '^rag-langfuse-postgres$'; then
  $CONTAINER_RT exec rag-langfuse-postgres pg_dump -U "${LANGFUSE_POSTGRES_USER:-postgres}" "${LANGFUSE_POSTGRES_DB:-postgres}" > "$OUT_DIR/langfuse.sql"
fi

if $CONTAINER_RT ps --format '{{.Names}}' | rg -q '^rag-redis$'; then
  $CONTAINER_RT exec rag-redis redis-cli SAVE >/dev/null
  $CONTAINER_RT cp rag-redis:/data/appendonly.aof "$OUT_DIR/redis-appendonly.aof" || true
fi

echo "[backup] done"

