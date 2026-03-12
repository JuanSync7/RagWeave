#!/usr/bin/env bash
set -euo pipefail

STAMP="${1:-$(date +%Y%m%d-%H%M%S)}"
OUT_DIR="${BACKUP_DIR:-./backups}/$STAMP"
mkdir -p "$OUT_DIR"

echo "[backup] writing backups into $OUT_DIR"

docker exec rag-temporal-db pg_dump -U temporal temporal > "$OUT_DIR/temporal.sql"

if docker ps --format '{{.Names}}' | rg -q '^rag-langfuse-postgres$'; then
  docker exec rag-langfuse-postgres pg_dump -U "${LANGFUSE_POSTGRES_USER:-postgres}" "${LANGFUSE_POSTGRES_DB:-postgres}" > "$OUT_DIR/langfuse.sql"
fi

if docker ps --format '{{.Names}}' | rg -q '^rag-redis$'; then
  docker exec rag-redis redis-cli SAVE >/dev/null
  docker cp rag-redis:/data/appendonly.aof "$OUT_DIR/redis-appendonly.aof" || true
fi

echo "[backup] done"

