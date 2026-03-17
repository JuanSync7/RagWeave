#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <backup_dir>"
  exit 1
fi

SRC_DIR="$1"
if [[ ! -d "$SRC_DIR" ]]; then
  echo "backup dir not found: $SRC_DIR"
  exit 1
fi

if [[ -f "$SRC_DIR/temporal.sql" ]]; then
  cat "$SRC_DIR/temporal.sql" | docker exec -i rag-temporal-db psql -U temporal -d temporal
fi

if [[ -f "$SRC_DIR/langfuse.sql" ]] && docker ps --format '{{.Names}}' | rg -q '^rag-langfuse-postgres$'; then
  cat "$SRC_DIR/langfuse.sql" | docker exec -i rag-langfuse-postgres psql -U "${LANGFUSE_POSTGRES_USER:-postgres}" -d "${LANGFUSE_POSTGRES_DB:-postgres}"
fi

if [[ -f "$SRC_DIR/redis-appendonly.aof" ]] && docker ps --format '{{.Names}}' | rg -q '^rag-redis$'; then
  docker cp "$SRC_DIR/redis-appendonly.aof" rag-redis:/data/appendonly.aof
  docker restart rag-redis >/dev/null
fi

echo "[restore] complete"

