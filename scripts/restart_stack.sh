#!/usr/bin/env bash
# @summary
# Full stack restart: safely brings down all containers then rebuilds and starts everything.
# Supports profile selection via flags. Waits for health checks before reporting success.
# Exports: (none — standalone script)
# Deps: scripts/compose.sh, scripts/container-runtime.sh
# @end-summary
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

# ── Defaults ──────────────────────────────────────────────────────────
PROFILES=()
BUILD=false
CLEAN_VOLUMES=false
REMOVE_ORPHANS=true
HEALTH_TIMEOUT=120      # seconds to wait for health checks
HEALTH_INTERVAL=3       # seconds between health polls

# ── Parse arguments ──────────────────────────────────────────────────
usage() {
    cat <<'EOF'
Usage: ./scripts/restart_stack.sh [OPTIONS]

Safely stop, rebuild, and restart the RAG container stack.

Options:
  --app              Include the API server profile
  --workers          Include the worker profile
  --monitoring       Include the monitoring profile (Dozzle, Prometheus, Grafana)
  --observability    Include the observability profile (Langfuse stack)
  --all              Enable all profiles (app + workers + monitoring + observability)
  --build            Force rebuild of images before starting
  --clean            Remove named volumes during teardown (DATA LOSS — use with care)
  --no-orphans       Skip --remove-orphans on down
  --health-timeout N Seconds to wait for health checks (default: 120)
  -h, --help         Show this help

Examples:
  # Restart infrastructure only (Temporal + DB + UI)
  ./scripts/restart_stack.sh

  # Restart with API + workers, force rebuild
  ./scripts/restart_stack.sh --app --workers --build

  # Full stack restart
  ./scripts/restart_stack.sh --all --build
EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --app)           PROFILES+=("app"); shift ;;
        --workers)       PROFILES+=("workers"); shift ;;
        --monitoring)    PROFILES+=("monitoring"); shift ;;
        --observability) PROFILES+=("observability"); shift ;;
        --all)
            PROFILES+=("app" "workers" "monitoring" "observability")
            shift ;;
        --build)         BUILD=true; shift ;;
        --clean)         CLEAN_VOLUMES=true; shift ;;
        --no-orphans)    REMOVE_ORPHANS=false; shift ;;
        --health-timeout)
            HEALTH_TIMEOUT="$2"; shift 2 ;;
        -h|--help)       usage ;;
        *)
            echo "Unknown option: $1" >&2
            usage ;;
    esac
done

# ── Detect runtime ───────────────────────────────────────────────────
source "$SCRIPT_DIR/container-runtime.sh"
echo "[restart] Container runtime: $CONTAINER_RT"

# Build compose command with profiles
COMPOSE="$SCRIPT_DIR/compose.sh"
PROFILE_ARGS=()
for p in "${PROFILES[@]+"${PROFILES[@]}"}"; do
    PROFILE_ARGS+=("--profile" "$p")
done

echo "[restart] Profiles: ${PROFILES[*]:-<default (infrastructure only)>}"

# ── Phase 1: Teardown ────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  Phase 1: Stopping containers"
echo "═══════════════════════════════════════════════════════════════"

DOWN_ARGS=("down")
if $REMOVE_ORPHANS; then
    DOWN_ARGS+=("--remove-orphans")
fi
if $CLEAN_VOLUMES; then
    echo "[restart] WARNING: --clean flag set — named volumes will be removed."
    DOWN_ARGS+=("-v")
fi

# Stop all containers (including all profiles, not just selected ones)
# This ensures nothing is left running from a previous config.
"$COMPOSE" \
    --profile app --profile workers --profile monitoring --profile observability --profile gateway \
    "${DOWN_ARGS[@]}" 2>&1 || true

# Verify nothing is still running
REMAINING=$($CONTAINER_RT ps --format '{{.Names}}' 2>/dev/null | grep -c '^rag-' || true)
if [[ "$REMAINING" -gt 0 ]]; then
    echo "[restart] $REMAINING rag-* containers still running — force stopping..."
    $CONTAINER_RT ps --format '{{.Names}}' | grep '^rag-' | xargs -r $CONTAINER_RT stop 2>/dev/null || true
    $CONTAINER_RT ps --format '{{.Names}}' | grep '^rag-' | xargs -r $CONTAINER_RT rm -f 2>/dev/null || true
fi

echo "[restart] All containers stopped."

# ── Phase 2: Build (optional) ────────────────────────────────────────
if $BUILD; then
    echo ""
    echo "═══════════════════════════════════════════════════════════════"
    echo "  Phase 2: Building images"
    echo "═══════════════════════════════════════════════════════════════"
    "$COMPOSE" "${PROFILE_ARGS[@]}" build 2>&1
    echo "[restart] Build complete."
fi

# ── Phase 3: Start ───────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  Phase 3: Starting containers"
echo "═══════════════════════════════════════════════════════════════"

UP_ARGS=("up" "-d")
if $BUILD; then
    UP_ARGS+=("--build")
fi

"$COMPOSE" "${PROFILE_ARGS[@]}" "${UP_ARGS[@]}" 2>&1
echo "[restart] Containers started."

# ── Phase 4: Health checks ───────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  Phase 4: Waiting for health checks"
echo "═══════════════════════════════════════════════════════════════"

# Collect containers that have health checks
HEALTH_TARGETS=()

# Temporal DB is always started (no profile)
HEALTH_TARGETS+=("rag-temporal-db")

# Profile-dependent health checks
for p in "${PROFILES[@]+"${PROFILES[@]}"}"; do
    case "$p" in
        app)           HEALTH_TARGETS+=("rag-api" "rag-nginx") ;;
        observability) HEALTH_TARGETS+=("rag-langfuse-postgres" "rag-langfuse-redis" "rag-langfuse-clickhouse" "rag-langfuse-minio") ;;
    esac
done

ALL_HEALTHY=true
for target in "${HEALTH_TARGETS[@]}"; do
    echo -n "[health] Waiting for $target..."

    ELAPSED=0
    while [[ $ELAPSED -lt $HEALTH_TIMEOUT ]]; do
        STATUS=$($CONTAINER_RT inspect --format '{{.State.Health.Status}}' "$target" 2>/dev/null || echo "missing")
        if [[ "$STATUS" == "healthy" ]]; then
            echo " healthy (${ELAPSED}s)"
            break
        fi
        sleep "$HEALTH_INTERVAL"
        ELAPSED=$((ELAPSED + HEALTH_INTERVAL))
    done

    if [[ "$STATUS" != "healthy" ]]; then
        echo " TIMEOUT after ${HEALTH_TIMEOUT}s (status: $STATUS)"
        ALL_HEALTHY=false
    fi
done

# ── Phase 5: Final status ───────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  Phase 5: Final status"
echo "═══════════════════════════════════════════════════════════════"

$CONTAINER_RT ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null | grep -E '(NAMES|rag-)' || true

echo ""

# Quick API smoke test if app profile is active
for p in "${PROFILES[@]+"${PROFILES[@]}"}"; do
    if [[ "$p" == "app" ]]; then
        # Direct API check (bypasses nginx)
        echo -n "[smoke] API direct (port ${RAG_API_HOST_PORT:-8000}): "
        if command -v curl &>/dev/null; then
            HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:${RAG_API_HOST_PORT:-8000}/health" 2>/dev/null || echo "000")
            if [[ "$HTTP_CODE" == "200" ]]; then
                echo "OK (HTTP 200)"
            else
                echo "FAILED (HTTP $HTTP_CODE)"
                ALL_HEALTHY=false
            fi

            # Nginx check (through reverse proxy)
            echo -n "[smoke] API via nginx (https): "
            NGINX_BODY=$(curl -sk "https://localhost/health" 2>/dev/null || true)
            HTTP_CODE=$(curl -sk -o /dev/null -w "%{http_code}" "https://localhost/health" 2>/dev/null || echo "000")
            if [[ "$HTTP_CODE" == "200" ]]; then
                echo "OK (HTTP 200) — $NGINX_BODY"
            else
                echo "FAILED (HTTP $HTTP_CODE) — check: docker logs rag-nginx"
                ALL_HEALTHY=false
            fi
        else
            python3 -c "
import urllib.request, ssl
ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
try:
    r = urllib.request.urlopen('http://localhost:${RAG_API_HOST_PORT:-8000}/health', timeout=5)
    print(f'OK (HTTP {r.status})')
except Exception as e:
    print(f'FAILED ({e})')
try:
    r = urllib.request.urlopen('https://localhost/health', context=ctx, timeout=5)
    print(f'nginx OK (HTTP {r.status})')
except Exception as e:
    print(f'nginx FAILED ({e})')
" 2>/dev/null || echo "SKIP (no curl or python3)"
        fi
        break
    fi
done

echo ""
if $ALL_HEALTHY; then
    echo "[restart] Stack is up and healthy."
else
    echo "[restart] WARNING: Some services did not pass health checks."
    echo "[restart] Run '$CONTAINER_RT logs <container>' to investigate."
fi
