#!/usr/bin/env bash
set -euo pipefail

API_URL="${RAG_API_URL:-http://localhost:8000}"

echo "[smoke] checking health at $API_URL/health"
python - <<'PY'
import json
import os
import urllib.request

api = os.environ.get("RAG_API_URL", "http://localhost:8000").rstrip("/")
with urllib.request.urlopen(f"{api}/health", timeout=10) as resp:
    data = json.loads(resp.read().decode("utf-8"))
assert "status" in data, "missing status field"
print("[smoke] health:", data)
PY

echo "[smoke] ok"

