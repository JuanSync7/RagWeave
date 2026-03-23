# Podman Migration — Implementation Guide

**Spec**: `docs/operations/PODMAN_SPEC.md`
**Date**: 2026-03-14
**Updated**: 2026-03-17

---

## Phase Overview

| Phase | Scope | Estimated Effort |
|-------|-------|-----------------|
| **Phase 1** | Rootless Podman: Dockerfiles, compose, monitoring, docs | Small |

---

## Phase 1 — Podman Migration

### Task 1.1: Update Dockerfile.runtime for Non-Root

**File:** `docker/Dockerfile.runtime`

```dockerfile
# Add before the final CMD or after COPY:
RUN groupadd --system app && useradd --system --gid app --create-home app
RUN chown -R app:app /app
USER app
```

Verify model files at `/models:ro` are readable by UID that maps to `app` in rootless Podman.

---

### Task 1.2: Update Dozzle for Podman Socket

**File:** `docker-compose.yml` — `dozzle` service

```yaml
  dozzle:
    profiles: ["monitoring"]
    image: amir20/dozzle:latest
    container_name: rag-monitor
    ports:
      - "9999:8080"
    volumes:
      # Use variable for Docker/Podman compatibility
      - ${CONTAINER_SOCK:-/var/run/docker.sock}:/var/run/docker.sock:ro
    restart: unless-stopped
```

Set `CONTAINER_SOCK=$XDG_RUNTIME_DIR/podman/podman.sock` in `.env` for Podman users.

---

### Task 1.3: Create Runtime Detection Script

**New file:** `scripts/compose.sh`

```bash
#!/usr/bin/env bash
# Auto-detect Docker or Podman and run compose with correct binary.
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

Usage: `./scripts/compose.sh --profile app up -d`

---

### Task 1.4: Rootless Port Binding

Ports 80 and 443 require either:
- `sysctl net.ipv4.ip_unprivileged_port_start=0` (system-wide)
- Or change to higher ports: `RAG_HTTPS_PORT=8443` and `RAG_HTTP_PORT=8080`

**Recommendation:** Default to 8443/8080 in `.env.example` for Podman users.

```bash
# .env.example addition
# Podman rootless: use unprivileged ports (or set sysctl)
# RAG_HTTPS_PORT=8443
# RAG_HTTP_PORT=8080
# CONTAINER_SOCK=$XDG_RUNTIME_DIR/podman/podman.sock
```

---

### Task 1.5: Update generate-certs.sh

**File:** `docker/generate-certs.sh`

Replace the Docker-based permission fix with runtime detection:

```bash
# At the end of the script, fix permissions for rootless Podman
if command -v podman &>/dev/null; then
    chmod 644 "$CERT_FILE"
    chmod 600 "$KEY_FILE"
fi
```

---

### Task 1.6: Volume UID Mapping

Podman rootless maps UIDs. For volumes that need write access, add `:U` flag:

```yaml
# docker-compose.yml — rag-api volumes
    volumes:
      - ./.runtime:/app/.runtime:U  # auto-map UID for rootless Podman
```

**Note:** `:U` is Podman-specific and ignored by Docker, so it's safe to add unconditionally.

---

### Task 1.7: Test Matrix

| Test | Command | Expected |
|------|---------|----------|
| Start default services | `podman-compose up -d` | Temporal + DB + UI healthy |
| Start app profile | `podman-compose --profile app up -d` | API + Nginx healthy, HTTPS works |
| Start workers | `podman-compose --profile workers up -d` | Worker connects to Temporal |
| Health check | `curl -sk https://localhost:8443/health` | `{"status":"healthy",...}` |
| Monitoring | `podman-compose --profile monitoring up -d` | Dozzle + Prometheus + Grafana up |
| Worker non-root | `podman exec rag-rag-worker-1 whoami` | `app` (not `root`) |
| Cert generation | `bash docker/generate-certs.sh` | Certs created in `.runtime/certs/` |
| Console UI | Browser -> `https://localhost:8443/console` | Console loads, queries work |

---

## Code Appendix — File Change Summary

### New Files

| File | Purpose |
|------|---------|
| `scripts/compose.sh` | Docker/Podman auto-detection wrapper |

### Modified Files

| File | Change |
|------|--------|
| `docker/Dockerfile.runtime` | Add non-root user |
| `docker-compose.yml` | Dozzle socket variable, volume `:U` flags |
| `docker/generate-certs.sh` | Podman permission handling |
| `.env.example` | Podman port/socket defaults |
