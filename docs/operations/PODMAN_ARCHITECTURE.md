# Podman in the RAG Stack — Architecture & Operations Guide

**Status**: Post-implementation
**Date**: 2026-03-23

**Related documents:**
- Specification: `docs/operations/PODMAN_SPEC.md`
- Implementation plan: `docs/operations/PODMAN_IMPLEMENTATION.md`
- Test specification: `docs/operations/PODMAN_TEST_SPEC.md`

---

## 1. What Is Podman Doing in This Project?

Podman is the **primary container runtime** for the RAG stack. It replaces Docker as the engine that builds, runs, and manages all containerized services — Temporal, the API server, workers, monitoring, and observability.

### In Plain Terms

Every service defined in `docker-compose.yml` — databases, the API, GPU workers, log viewers, metrics dashboards — runs inside a container. Podman is the program that creates and manages those containers. It reads the same Compose files and Dockerfiles that Docker uses, but it does so **without a root daemon**, which is the single most important difference.

---

## 2. Why Podman Instead of Docker?

### 2.1 The Root Daemon Problem

Docker requires a background process (`dockerd`) running as root. Every `docker` CLI command talks to this daemon over a Unix socket (`/var/run/docker.sock`). This creates three problems:

1. **Privilege escalation surface** — Any process that can talk to `dockerd` effectively has root access to the host. Mounting the Docker socket into a container (as Dozzle does for log streaming) is a well-known container escape vector.

2. **Single point of failure** — If `dockerd` crashes, every running container is affected.

3. **Audit blindness** — All container operations appear to come from `dockerd`, not from the user or script that initiated them.

### 2.2 How Podman Solves This

| Problem | Docker | Podman |
|---------|--------|--------|
| Root daemon | `dockerd` runs as root | No daemon — each `podman` command is a direct fork/exec |
| Socket ownership | `/var/run/docker.sock` (root) | `$XDG_RUNTIME_DIR/podman/podman.sock` (user) |
| Container crash isolation | Daemon crash affects all containers | No daemon to crash |
| Audit trail | All ops look like `dockerd` | Each op traces to invoking user/PID |
| UID mapping | Container root = host root | Container root maps to unprivileged host UID |

### 2.3 What Stays the Same

Podman is **CLI-compatible** with Docker. The same images, Compose files, Dockerfiles, volume mounts, health checks, and registries work on both. The RAG stack maintains **dual-runtime compatibility** — Docker still works as a fallback.

---

## 3. How Podman Is Integrated

### 3.1 Architecture Overview

```
                    ┌─────────────────────────────────────────┐
                    │         Host (rootless Podman)           │
                    │                                         │
  User runs:        │  ┌───────────────────────────────────┐  │
  ./scripts/        │  │      docker-compose.yml            │  │
  compose.sh ──────►│  │  (profiles: app, workers,          │  │
                    │  │   monitoring, observability)        │  │
                    │  └──────────────┬────────────────────┘  │
                    │                 │                        │
                    │    podman-compose / podman compose       │
                    │                 │                        │
                    │    ┌────────────┼────────────────┐      │
                    │    │            │                │      │
                    │    ▼            ▼                ▼      │
                    │ ┌──────┐  ┌──────────┐  ┌───────────┐  │
                    │ │ API  │  │ Workers  │  │ Infra     │  │
                    │ │(app) │  │(user:app)│  │(temporal, │  │
                    │ │      │  │ GPU mem  │  │ redis,    │  │
                    │ └──────┘  └──────────┘  │ dozzle)   │  │
                    │                         └───────────┘  │
                    │                                         │
                    │  User socket: $XDG_RUNTIME_DIR/         │
                    │    podman/podman.sock                    │
                    └─────────────────────────────────────────┘
```

### 3.2 Runtime Detection Layer

The stack uses a **two-script detection layer** so that the same codebase works on both Podman and Docker hosts:

#### Shell Scripts: `scripts/container-runtime.sh`

```bash
# Sourced by operational scripts (backup, restore)
source scripts/container-runtime.sh
# $CONTAINER_RT is now "podman" or "docker"
$CONTAINER_RT exec rag-temporal-db pg_dump ...
```

- Detection order: **Podman first**, Docker fallback.
- Exits with error if neither is found.
- Sourced (not executed) so the variable propagates to the calling script.

#### Shell Scripts: `scripts/compose.sh`

```bash
# Replaces all "docker compose" / "podman-compose" commands
./scripts/compose.sh --profile app --profile workers up -d
```

- Detection order: `podman-compose` > `podman compose` > `docker compose`.
- Uses `exec` to replace itself with the compose command (clean process tree).
- Single entry point for all compose operations across docs, scripts, and developer workflows.

#### Python Scripts: `_detect_container_runtime()`

```python
# Used by auto_scale_workers.py, watch_tuning_signals.py
import shutil

def _detect_container_runtime() -> str:
    if shutil.which("podman"):
        return "podman"
    if shutil.which("docker"):
        return "docker"
    raise RuntimeError("Neither podman nor docker found in PATH")

CONTAINER_RT = _detect_container_runtime()
```

- Same Podman-first order as the shell scripts.
- Uses `shutil.which()` — portable, no subprocess overhead.
- Set at module import time as a module-level constant.

### 3.3 Container Security: Non-Root Workers

All containers run as non-root users:

| Dockerfile | User | How |
|-----------|------|-----|
| `containers/Dockerfile.api` | `app` | `groupadd`/`useradd` + `USER app` |
| `containers/Dockerfile.runtime` | `app` | `groupadd`/`useradd` + `COPY --chown=app:app` + `USER app` |

This gives **two layers of defense**:
1. **Rootless Podman** — container root maps to an unprivileged host UID.
2. **Non-root USER** — even inside the container, the process runs as `app`, not root.

### 3.4 Dozzle Log Monitoring

Dozzle (the container log viewer) needs access to the runtime socket:

```yaml
# docker-compose.yml
volumes:
  - ${CONTAINER_SOCK:-/var/run/docker.sock}:/var/run/docker.sock:ro
```

- **Docker users**: No configuration needed (default works).
- **Podman users**: Set `CONTAINER_SOCK=$XDG_RUNTIME_DIR/podman/podman.sock` in `.env`.

### 3.5 Volume Permissions

The `:U` volume flag (Podman-only, auto-chowns mounted volumes) is **not used** because it would break Docker compatibility. Instead:

- Application code ownership is set via `COPY --chown=app:app` in Dockerfiles.
- Read-only bind mounts (`/models:ro`, `/seed_weaviate:ro`) work for any UID.
- Writable temp directories (`/tmp`) are world-writable by default.
- Certificate permissions are set explicitly with `chmod 644`/`chmod 600` in `containers/generate-certs.sh`.

---

## 4. File Map

### New Files (Podman Integration)

| File | Purpose |
|------|---------|
| `scripts/container-runtime.sh` | Shell runtime detection — exports `$CONTAINER_RT` |
| `scripts/compose.sh` | Compose command wrapper — auto-detects and forwards |

### Modified Files

| File | What Changed | Why |
|------|-------------|-----|
| `containers/Dockerfile.runtime` | Non-root user `app`, `--chown` on COPY | Security: non-root container process |
| `containers/generate-certs.sh` | Explicit `chmod 644`/`chmod 600` | Rootless umask may create restrictive permissions |
| `docker-compose.yml` | `CONTAINER_SOCK` env var for Dozzle | Configurable socket path for Podman |
| `.env.example` | Documented `CONTAINER_SOCK` | Discovery for Podman users |
| `scripts/backup_all.sh` | Sources runtime helper, uses `$CONTAINER_RT` | Runtime-agnostic backup |
| `scripts/restore_all.sh` | Sources runtime helper, uses `$CONTAINER_RT` | Runtime-agnostic restore |
| `scripts/auto_scale_workers.py` | `_detect_container_runtime()` + compose detection | Runtime-agnostic scaling |
| `scripts/watch_tuning_signals.py` | `_detect_container_runtime()` | Runtime-agnostic monitoring |
| `README.md` | Podman Setup section, `compose.sh` references | Developer onboarding |

### Configuration Files (Unchanged Format)

| File | Notes |
|------|-------|
| `docker-compose.yml` | Standard Compose v3 — works with both `podman-compose` and `docker compose` |
| `containers/Dockerfile.api` | Standard Dockerfile — already had non-root user |
| `containers/nginx.conf` | No runtime dependency |
| `containers/proxy_params.conf` | No runtime dependency |

---

## 5. Developer Workflows

### 5.1 First-Time Setup (Podman)

```bash
# Install Podman
sudo apt-get install -y podman podman-compose   # Debian/Ubuntu

# Enable user socket (needed for Dozzle)
systemctl --user enable --now podman.socket

# Verify rootless
podman info | grep -i rootless   # → rootless: true

# Configure socket for Dozzle
echo "CONTAINER_SOCK=\$XDG_RUNTIME_DIR/podman/podman.sock" >> .env
```

### 5.2 Daily Operations

```bash
# Start infrastructure
./scripts/compose.sh up -d

# Start full stack
./scripts/compose.sh --profile app --profile workers up -d

# Scale workers
./scripts/compose.sh --profile workers up -d --scale rag-worker=3

# View logs
./scripts/compose.sh logs -f rag-worker

# Monitoring dashboard
./scripts/compose.sh --profile monitoring up -d

# Backup
./scripts/backup_all.sh

# Restore
./scripts/restore_all.sh ./backups/<timestamp>
```

### 5.3 Docker Fallback

If a developer has Docker but not Podman, **everything works unchanged**. The detection scripts fall back to Docker automatically. No aliases, PATH changes, or configuration needed.

---

## 6. Design Decisions

### 6.1 Why Wrapper Scripts, Not `alias docker=podman`?

| Approach | Verdict |
|----------|---------|
| `alias docker=podman` | **Rejected** — aliases don't work in non-interactive shells (scripts, CI). Doesn't handle `docker compose` → `podman-compose` difference. |
| Wrapper scripts | **Chosen** — works in all contexts, handles compose command differences, maintains dual-runtime compatibility. |
| Full Podman replacement | **Rejected** — would break Docker-only users. |

### 6.2 Why `COPY --chown` Instead of `:U` Volume Flag?

The `:U` flag is Podman-only. Docker Compose does not recognize it and will error. Using Dockerfile-level ownership works identically on both runtimes.

### 6.3 Why Keep `docker-compose.yml` and `Dockerfile` Names?

These are industry-standard names recognized by both Docker and Podman. Renaming to `podman-compose.yml` or `Containerfile` would break compatibility without functional benefit. The `containers/` directory (formerly `docker/`) uses the generic name since it holds build context for any OCI runtime.

### 6.4 Why Podman-First Detection Order?

When both runtimes are installed, Podman is preferred because:
- It's the target runtime for this project.
- Rootless by default — better security posture.
- Developers who installed both likely intend to use Podman.

Docker is always available as a fallback for environments where Podman isn't installed.

---

## 7. Troubleshooting

### Dozzle Shows No Containers

```bash
# Verify socket exists
ls -la $XDG_RUNTIME_DIR/podman/podman.sock

# Verify CONTAINER_SOCK is set in .env
grep CONTAINER_SOCK .env

# Restart Dozzle
./scripts/compose.sh --profile monitoring restart dozzle
```

### Permission Denied on Volume Mounts

```bash
# Check if running rootless
podman info | grep rootless

# Verify container user
podman exec <container> whoami   # should be "app"

# Check file ownership inside container
podman exec <container> ls -la /app/
```

### `podman-compose` Command Not Found

```bash
# Option 1: Install podman-compose
pip install podman-compose

# Option 2: Use podman compose plugin (Podman 4+)
podman compose version

# Option 3: Fall back to Docker
# compose.sh will auto-detect docker compose
```

### Certificate Permission Issues

```bash
# Regenerate with correct permissions
rm -rf .runtime/certs
bash containers/generate-certs.sh
ls -la .runtime/certs/   # cert=644, key=600
```

---

## 8. Relationship to Other Documents

| Document | Purpose | When to Read |
|----------|---------|-------------|
| `PODMAN_SPEC.md` | Requirements and acceptance criteria | When verifying completeness or adding new requirements |
| `PODMAN_IMPLEMENTATION.md` | Step-by-step implementation tasks | When onboarding or understanding what was changed |
| `PODMAN_MIGRATION_GUIDE.md` | Design decisions and change summary | When understanding why a decision was made |
| `PODMAN_TEST_SPEC.md` | Test strategy and coverage | When adding or modifying tests |
| This document | Architecture and operations reference | When operating the stack day-to-day |
