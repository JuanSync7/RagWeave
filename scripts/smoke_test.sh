#!/usr/bin/env bash
# smoke_test.sh — full pre-merge integration check
#
# Steps:
#   1. Build images (cache-aware, picks up source changes)
#   2. Start the stack
#   3. Wait for API health
#   4. Open a cloudflared tunnel and smoke-test through it
#   5. Tear down regardless of outcome
#
# Usage:
#   ./scripts/smoke_test.sh              # build + run
#   SKIP_BUILD=1 ./scripts/smoke_test.sh # skip build, use existing images

set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
API_PORT="${RAG_API_HOST_PORT:-8000}"
NGINX_PORT="${RAG_NGINX_HTTP_PORT:-80}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-120}"   # seconds to wait for API to become ready
TUNNEL_TIMEOUT="${TUNNEL_TIMEOUT:-45}"    # seconds to wait for cloudflared URL

PASS="\033[0;32m[PASS]\033[0m"
FAIL="\033[0;31m[FAIL]\033[0m"
INFO="\033[0;34m[INFO]\033[0m"

# Auto-detect compose binary
if command -v podman-compose &>/dev/null; then
    COMPOSE_CMD="podman-compose"
elif command -v podman &>/dev/null && podman compose version &>/dev/null 2>&1; then
    COMPOSE_CMD="podman compose"
elif command -v docker &>/dev/null && docker compose version &>/dev/null 2>&1; then
    COMPOSE_CMD="docker compose"
else
    echo -e "$FAIL Neither podman-compose nor docker compose found." >&2
    exit 1
fi
echo -e "$INFO Using compose: $COMPOSE_CMD"

cleanup() {
    echo -e "$INFO Tearing down stack..."
    $COMPOSE_CMD -f "$COMPOSE_FILE" --profile temporal --profile app --profile workers --profile monitoring down --remove-orphans 2>/dev/null || true
    # Prune dangling images left by compose builds
    docker image prune -f 2>/dev/null || true
    podman image prune -f 2>/dev/null || true
    if [[ -n "${TUNNEL_PID:-}" ]]; then
        kill "$TUNNEL_PID" 2>/dev/null || true
    fi
    if [[ -n "${TUNNEL_LOG:-}" && -f "$TUNNEL_LOG" ]]; then
        rm -f "$TUNNEL_LOG"
    fi
}
trap cleanup EXIT

# ---------------------------------------------------------------------------
# 1. Build
# ---------------------------------------------------------------------------
if [[ "${SKIP_BUILD:-0}" != "1" ]]; then
    echo -e "$INFO Compiling frontend (TypeScript → static JS)..."
    npm --prefix server/console/web ci --silent
    npm --prefix server/console/web run build
    echo -e "$PASS Frontend compiled."

    echo -e "$INFO Building images (cache-aware)..."
    $COMPOSE_CMD -f "$COMPOSE_FILE" --profile temporal --profile app build
    echo -e "$PASS Build complete."
else
    echo -e "$INFO Skipping build (SKIP_BUILD=1)."
fi

# ---------------------------------------------------------------------------
# 2. Start
# ---------------------------------------------------------------------------
echo -e "$INFO Tearing down any previous stack (all profiles)..."
$COMPOSE_CMD -f "$COMPOSE_FILE" --profile temporal --profile app --profile workers --profile monitoring down --remove-orphans --volumes 2>/dev/null || true
# Also force-remove any rag- containers that compose missed (handles mixed Podman/Docker sessions)
if command -v docker &>/dev/null; then
    docker ps -a --format "{{.Names}}" 2>/dev/null | grep "^rag-" | xargs -r docker rm -f 2>/dev/null || true
    docker network ls --format "{{.Name}}" 2>/dev/null | grep "ragweave" | xargs -r docker network rm 2>/dev/null || true
fi
if command -v podman &>/dev/null; then
    podman ps -a --format "{{.Names}}" 2>/dev/null | grep "^rag-" | xargs -r podman rm -f 2>/dev/null || true
fi

echo -e "$INFO Starting stack (profile: app)..."
$COMPOSE_CMD -f "$COMPOSE_FILE" --profile temporal --profile app up -d
echo -e "$PASS Stack started."

# ---------------------------------------------------------------------------
# 3. Wait for API health
# ---------------------------------------------------------------------------
echo -e "$INFO Waiting for API health (timeout ${HEALTH_TIMEOUT}s)..."
DEADLINE=$(( $(date +%s) + HEALTH_TIMEOUT ))
until curl -sf "http://localhost:${API_PORT}/health" -o /dev/null; do
    if (( $(date +%s) > DEADLINE )); then
        echo -e "$FAIL API did not become healthy within ${HEALTH_TIMEOUT}s."
        exit 1
    fi
    sleep 3
done
echo -e "$PASS API is healthy."

# ---------------------------------------------------------------------------
# 4. Cloudflare tunnel + smoke tests
# ---------------------------------------------------------------------------
TUNNEL_LOG=$(mktemp /tmp/cloudflared-XXXXXX.log)
echo -e "$INFO Starting cloudflared tunnel on port ${NGINX_PORT}..."
cloudflared tunnel --url "http://localhost:${API_PORT}" \
    --no-autoupdate 2>"$TUNNEL_LOG" &
TUNNEL_PID=$!

# Extract the trycloudflare URL from the log
TUNNEL_URL=""
DEADLINE=$(( $(date +%s) + TUNNEL_TIMEOUT ))
while [[ -z "$TUNNEL_URL" ]]; do
    if (( $(date +%s) > DEADLINE )); then
        echo -e "$FAIL cloudflared did not produce a URL within ${TUNNEL_TIMEOUT}s."
        cat "$TUNNEL_LOG"
        exit 1
    fi
    TUNNEL_URL=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' "$TUNNEL_LOG" 2>/dev/null | head -1 || true)
    sleep 1
done
echo -e "$PASS Tunnel URL: $TUNNEL_URL"

# Give the tunnel time to be reachable through Cloudflare's edge
echo -e "$INFO Waiting for tunnel to be reachable..."
TUNNEL_READY=0
for i in $(seq 1 12); do
    status=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$TUNNEL_URL/health" || echo "000")
    if [[ "$status" == "200" || "$status" == "401" || "$status" == "422" || "$status" == "404" ]]; then
        TUNNEL_READY=1
        break
    fi
    echo -e "$INFO  attempt $i/12: got $status, retrying in 5s..."
    sleep 5
done
if (( TUNNEL_READY == 0 )); then
    echo -e "$FAIL Tunnel never became reachable after 60s."
    cat "$TUNNEL_LOG"
    exit 1
fi
echo -e "$PASS Tunnel is reachable."

FAILURES=0

run_check() {
    local label="$1"
    local url="$2"
    local expected_status="${3:-200}"
    local status
    status=$(curl -s -o /dev/null -w "%{http_code}" "$url" || echo "000")
    if [[ "$status" == "$expected_status" ]]; then
        echo -e "$PASS $label → HTTP $status"
    else
        echo -e "$FAIL $label → expected HTTP $expected_status, got $status"
        FAILURES=$(( FAILURES + 1 ))
    fi
}

echo -e "$INFO Running smoke checks through tunnel..."

# API health via tunnel
run_check "GET /health (via tunnel)"          "$TUNNEL_URL/health"

# Console (web UI) — expect 200
run_check "GET /console (web UI)"             "$TUNNEL_URL/console"

# 404 envelope — must return structured JSON, not raw nginx 404
status=$(curl -s -o /dev/null -w "%{http_code}" "$TUNNEL_URL/does-not-exist" || echo "000")
if [[ "$status" == "404" ]]; then
    body=$(curl -s "$TUNNEL_URL/does-not-exist" || true)
    if echo "$body" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d.get('ok') is False" 2>/dev/null; then
        echo -e "$PASS GET /does-not-exist → 404 with structured envelope"
    else
        echo -e "$FAIL GET /does-not-exist → 404 but response is not a structured envelope"
        FAILURES=$(( FAILURES + 1 ))
    fi
else
    echo -e "$FAIL GET /does-not-exist → expected 404, got $status"
    FAILURES=$(( FAILURES + 1 ))
fi

# POST /query with empty body — expect 422 (validation error envelope)
status=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$TUNNEL_URL/query" \
    -H "Content-Type: application/json" -d '{}' || echo "000")
if [[ "$status" == "422" ]]; then
    echo -e "$PASS POST /query (empty body) → 422 validation error"
else
    echo -e "$FAIL POST /query (empty body) → expected 422, got $status"
    FAILURES=$(( FAILURES + 1 ))
fi

# ---------------------------------------------------------------------------
# 5. Result
# ---------------------------------------------------------------------------
echo ""
if (( FAILURES == 0 )); then
    echo -e "$PASS All smoke checks passed. Safe to merge to main."
    exit 0
else
    echo -e "$FAIL $FAILURES smoke check(s) failed. Do not merge."
    exit 1
fi
