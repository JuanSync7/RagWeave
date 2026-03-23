#!/usr/bin/env bash
# @summary
# Auto-detect Docker or Podman and run compose with the correct binary.
# Usage: ./scripts/compose.sh --profile app up -d
# Exports: (none — exec's into compose)
# Deps: podman-compose | podman compose | docker compose
# @end-summary
set -euo pipefail

if command -v podman-compose &>/dev/null; then
    COMPOSE_CMD="podman-compose"
elif command -v podman &>/dev/null && podman compose version &>/dev/null 2>&1; then
    COMPOSE_CMD="podman compose"
elif command -v docker &>/dev/null && docker compose version &>/dev/null 2>&1; then
    COMPOSE_CMD="docker compose"
else
    echo "Error: Neither podman-compose nor docker compose found." >&2
    exit 1
fi

echo "[compose] Using: $COMPOSE_CMD"
exec $COMPOSE_CMD "$@"
