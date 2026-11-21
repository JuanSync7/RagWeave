#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a
exec .venv/bin/uvicorn server.api:app --host 0.0.0.0 --port "${RAG_API_PORT:-8000}"
