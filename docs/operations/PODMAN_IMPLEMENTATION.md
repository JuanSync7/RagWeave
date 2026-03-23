# Podman Migration — Implementation Guide

**Spec**: `docs/operations/PODMAN_SPEC.md`
**Date**: 2026-03-14
**Updated**: 2026-03-23

---

## Phase Overview

| Phase | Scope | Estimated Effort |
|-------|-------|-----------------|
| **Phase 1** | Rootless Podman: runtime detection, Dockerfiles, compose, scripts, monitoring, docs | Small–Medium |

---

## Phase 1 — Podman Migration

### Task 1.1: Create Runtime Detection Helper

**Why:** Every script in this project currently hardcodes `docker`. Instead of updating each
script individually with detection logic, we create ONE shared helper that all scripts source.
This is the foundation that every other task depends on.

**New file:** `scripts/container-runtime.sh`

**What it does:** Checks if `podman` or `docker` is installed and exports the binary name
as `$CONTAINER_RT`. Podman is preferred when both are present.

```bash
#!/usr/bin/env bash
# Detect container runtime: prefer Podman, fall back to Docker.
# Source this file — do not execute it directly.
#   source scripts/container-runtime.sh
# After sourcing, $CONTAINER_RT is set to "podman" or "docker".

if command -v podman &>/dev/null; then
    CONTAINER_RT="podman"
elif command -v docker &>/dev/null; then
    CONTAINER_RT="docker"
else
    echo "Error: Neither podman nor docker found in PATH." >&2
    exit 1
fi
export CONTAINER_RT
```

**How to verify:** `source scripts/container-runtime.sh && echo $CONTAINER_RT`

---

### Task 1.2: Create Compose Wrapper Script

**Why:** Docker uses `docker compose` (plugin) while Podman uses `podman-compose` or
`podman compose`. This wrapper auto-detects which is available so developers and other
scripts can use one consistent command: `./scripts/compose.sh`.

**New file:** `scripts/compose.sh`

```bash
#!/usr/bin/env bash
# Auto-detect Docker or Podman and run compose with the correct binary.
# Usage: ./scripts/compose.sh --profile app up -d
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
```

**How to verify:** `./scripts/compose.sh version`

---

### Task 1.3: Update Dockerfile.runtime for Non-Root

**Why:** The worker Dockerfile currently runs as root (no `USER` directive). This is a
security risk — if a container is compromised, the attacker has root inside it. The API
Dockerfile (`Dockerfile.api`) already runs as non-root user `app`; we mirror that pattern.

**File:** `docker/Dockerfile.runtime`

**What to add** (after the `COPY` directives, before any `CMD`):

```dockerfile
# Create non-root user (mirrors Dockerfile.api pattern).
RUN groupadd --system app && useradd --system --gid app --create-home app
RUN chown -R app:app /app
USER app
```

**Important notes:**
- Model files at `/models:ro` are mounted read-only — any UID can read them, so no issue.
- The Weaviate seed data copy in the compose command writes to `/tmp/`, which is
  world-writable, so it works under any user.
- Use `--chown=app:app` on COPY directives for source files owned by the app user.

---

### Task 1.4: Update Dozzle Socket in docker-compose.yml

**Why:** Dozzle (the container log viewer) currently hardcodes `/var/run/docker.sock`.
That socket is owned by root and only exists when Docker is running. Podman uses a
per-user socket at a different path. By using an environment variable with a default,
the same compose file works for both runtimes.

**File:** `docker-compose.yml` — `dozzle` service

**Change the volumes line from:**
```yaml
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
```

**To:**
```yaml
    volumes:
      - ${CONTAINER_SOCK:-/var/run/docker.sock}:/var/run/docker.sock:ro
```

**How it works:**
- Docker users: `CONTAINER_SOCK` is not set → defaults to `/var/run/docker.sock` → works as before.
- Podman users: set `CONTAINER_SOCK=$XDG_RUNTIME_DIR/podman/podman.sock` in `.env` → Dozzle
  connects to the Podman socket instead.

---

### Task 1.5: Update .env.example

**Why:** Podman users need to know which environment variables to set. Adding commented-out
examples in `.env.example` documents this without affecting Docker users.

**File:** `.env.example`

**Add at the end:**
```bash
# ============================================================
# Container Runtime (Podman)
# Uncomment these lines if using Podman instead of Docker.
# ============================================================
# CONTAINER_SOCK=$XDG_RUNTIME_DIR/podman/podman.sock
```

---

### Task 1.6: Update generate-certs.sh

**Why:** The cert generation script uses `openssl` directly (no Docker dependency), but
in rootless Podman the generated files need explicit permissions so the container user
can read them. Adding a `chmod` ensures certs work regardless of the user's umask.

**File:** `docker/generate-certs.sh`

**Add at the end of the script, after the `echo` line:**
```bash
# Ensure cert permissions are correct for rootless container runtimes.
chmod 644 "$CERT_FILE"
chmod 600 "$KEY_FILE"
```

---

### Task 1.7: Update Shell Scripts for Runtime Detection

**Why:** `backup_all.sh` and `restore_all.sh` hardcode `docker` for exec/cp/ps/restart
commands. They must use `$CONTAINER_RT` from the shared helper so they work on Podman too.

#### File: `scripts/backup_all.sh`

**Change:** Add `source` line at the top (after `set -euo pipefail`) and replace all
`docker` calls with `$CONTAINER_RT`:

```bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/container-runtime.sh"
```

Then replace every `docker exec` → `$CONTAINER_RT exec`, `docker ps` → `$CONTAINER_RT ps`,
`docker cp` → `$CONTAINER_RT cp`.

#### File: `scripts/restore_all.sh`

Same pattern: source the helper, replace `docker` → `$CONTAINER_RT`.

---

### Task 1.8: Update Python Scripts for Runtime Detection

**Why:** `auto_scale_workers.py` and `watch_tuning_signals.py` hardcode `"docker"` in
subprocess calls. They need to detect the runtime dynamically.

**Pattern to use in both files:**

```python
import shutil

def _detect_container_runtime() -> str:
    """Return 'podman' if available, else 'docker'."""
    if shutil.which("podman"):
        return "podman"
    if shutil.which("docker"):
        return "docker"
    raise RuntimeError("Neither podman nor docker found in PATH")

CONTAINER_RT = _detect_container_runtime()
```

Then replace every `"docker"` string in subprocess calls with `CONTAINER_RT`.

**Files to update:**
- `scripts/auto_scale_workers.py` — uses `docker ps`, `docker stats`, `docker compose`
- `scripts/watch_tuning_signals.py` — uses `docker stats`

---

### Task 1.9: Update docker-compose.yml Header Comments

**Why:** The header comments reference `docker compose` commands. Update them to reference
the `scripts/compose.sh` wrapper so new developers use the correct command.

**File:** `docker-compose.yml`

Replace `docker compose` references in the comment block with `./scripts/compose.sh`.

---

### Task 1.10: Test Matrix

| # | Test | Command | Expected |
|---|------|---------|----------|
| 1 | Runtime detection (shell) | `source scripts/container-runtime.sh && echo $CONTAINER_RT` | `podman` or `docker` |
| 2 | Compose wrapper | `./scripts/compose.sh version` | Prints compose version |
| 3 | Start default services | `./scripts/compose.sh up -d` | Temporal + DB + UI healthy |
| 4 | Start app profile | `./scripts/compose.sh --profile app up -d` | API healthy |
| 5 | Start workers | `./scripts/compose.sh --profile workers up -d` | Worker connects to Temporal |
| 6 | Health check | `curl -fsS http://localhost:${RAG_API_PORT:-8000}/health` | `{"status":"healthy",...}` |
| 7 | Monitoring | `./scripts/compose.sh --profile monitoring up -d` | Dozzle + Prometheus + Grafana up |
| 8 | Worker non-root | `$CONTAINER_RT exec <worker> whoami` | `app` (not `root`) |
| 9 | Cert generation | `bash docker/generate-certs.sh` | Certs created in `.runtime/certs/` |
| 10 | Backup script | `./scripts/backup_all.sh test-run` | Backup files created |
| 11 | Python runtime detection | `python3 -c "from scripts.auto_scale_workers import CONTAINER_RT; print(CONTAINER_RT)"` | `podman` or `docker` |

---

## Code Appendix — File Change Summary

### New Files

| File | Purpose | Spec Requirement |
|------|---------|-----------------|
| `scripts/container-runtime.sh` | Shared runtime detection helper (sets `$CONTAINER_RT`) | R-B7 |
| `scripts/compose.sh` | Docker/Podman compose auto-detection wrapper | R-B5 |

### Modified Files

| File | Change | Spec Requirement |
|------|--------|-----------------|
| `docker/Dockerfile.runtime` | Add non-root user (`app`) with `USER` directive | R-B4 |
| `docker-compose.yml` | Dozzle socket via `CONTAINER_SOCK` env var; update header comments | R-B3, R-B2 |
| `docker/generate-certs.sh` | Add explicit `chmod` for cert permissions | R-B5 |
| `.env.example` | Add `CONTAINER_SOCK` documentation | R-B5 |
| `scripts/backup_all.sh` | Source `container-runtime.sh`, use `$CONTAINER_RT` | R-B7 |
| `scripts/restore_all.sh` | Source `container-runtime.sh`, use `$CONTAINER_RT` | R-B7 |
| `scripts/auto_scale_workers.py` | Add `_detect_container_runtime()`, use `CONTAINER_RT` | R-B7 |
| `scripts/watch_tuning_signals.py` | Add `_detect_container_runtime()`, use `CONTAINER_RT` | R-B7 |
