# Podman Migration Guide

This document describes all changes made during the Docker → Podman migration, explains the
design decisions, and provides a reference for developers working with the containerized stack.

**Related documents:**
- Specification: `docs/operations/PODMAN_SPEC.md`
- Implementation plan: `docs/operations/PODMAN_IMPLEMENTATION.md`

---

## 1. What Changed and Why

### 1.1 Runtime Detection (`scripts/container-runtime.sh`)

**What:** A shared Bash helper that detects whether `podman` or `docker` is installed and
exports the binary name as `$CONTAINER_RT`. Podman is preferred when both are present.

**Why:** Every operational script (backup, restore, scaling) previously hardcoded `docker`.
Rather than duplicating detection logic in each script, one helper is sourced by all of them.

**Usage:**
```bash
source scripts/container-runtime.sh
$CONTAINER_RT exec rag-temporal-db pg_dump ...
```

### 1.2 Compose Wrapper (`scripts/compose.sh`)

**What:** A wrapper script that auto-detects the correct compose command (`podman-compose`,
`podman compose`, or `docker compose`) and forwards all arguments to it.

**Why:** Docker uses `docker compose` (a plugin) while Podman uses `podman-compose`
(a standalone tool) or `podman compose`. The wrapper lets developers use one command
regardless of their runtime.

**Usage:**
```bash
./scripts/compose.sh --profile app --profile workers up -d
./scripts/compose.sh down
```

### 1.3 Non-Root Worker (`docker/Dockerfile.runtime`)

**What:** Added a non-root user `app` (matching `Dockerfile.api`) with `USER app` directive.
Source files use `--chown=app:app` on COPY.

**Why:** Running containers as root is a security risk. If a worker container is compromised,
the attacker gets root inside it. With rootless Podman + non-root user, two layers of
defense are in place.

**Impact on volumes:**
- `/models:ro` — read-only, readable by any UID. No issue.
- `/seed_weaviate:ro` — read-only, no issue.
- `/tmp/rag-weaviate-*` — the compose command copies seed data to `/tmp/` which is world-writable.

### 1.4 Dozzle Socket (`docker-compose.yml`)

**What:** Changed the Dozzle volume mount from hardcoded `/var/run/docker.sock` to
`${CONTAINER_SOCK:-/var/run/docker.sock}`.

**Why:** Dozzle needs access to the container runtime's socket to stream logs. Docker's
socket is at `/var/run/docker.sock` (root-owned), while Podman's is at
`$XDG_RUNTIME_DIR/podman/podman.sock` (user-owned). The env var makes it configurable.

**For Docker users:** No change needed — the default value is the Docker socket path.

**For Podman users:** Set `CONTAINER_SOCK=$XDG_RUNTIME_DIR/podman/podman.sock` in `.env`.

### 1.5 Certificate Permissions (`docker/generate-certs.sh`)

**What:** Added explicit `chmod 644` for the cert and `chmod 600` for the key after generation.

**Why:** In rootless Podman, the user's umask may create files with restrictive permissions.
Explicit chmod ensures the cert is world-readable (needed by Nginx) and the key is
owner-only (security best practice).

### 1.6 Shell Script Updates (`backup_all.sh`, `restore_all.sh`)

**What:** Both scripts now source `container-runtime.sh` and use `$CONTAINER_RT` instead
of hardcoded `docker`.

**Before:** `docker exec rag-temporal-db pg_dump ...`
**After:** `$CONTAINER_RT exec rag-temporal-db pg_dump ...`

### 1.7 Python Script Updates (`auto_scale_workers.py`, `watch_tuning_signals.py`)

**What:** Both scripts now use a `_detect_container_runtime()` function that checks
`shutil.which("podman")` first, then falls back to `docker`.

**Before:** `subprocess.run(["docker", "stats", ...], ...)`
**After:** `subprocess.run([CONTAINER_RT, "stats", ...], ...)`

### 1.8 README Updates

**What:** Updated `README.md` to:
- List Podman as an alternative to Docker in prerequisites
- Replace `docker compose` commands with `./scripts/compose.sh`
- Add a "Podman Setup" section with one-time configuration steps

---

## 2. Design Decision: Wrapper vs Alias

We chose the **wrapper/detection approach** over `alias docker=podman` because:

| Approach | Pros | Cons |
|----------|------|------|
| `alias docker=podman` | Zero code changes | Fragile; doesn't work in scripts (non-interactive shells don't load aliases); doesn't handle `docker compose` → `podman-compose` difference |
| Wrapper scripts | Works in all contexts; explicit; handles compose command differences | More files to maintain |
| Full Podman replacement | Clean; no ambiguity | Breaks for Docker-only users |

The wrapper approach maintains **dual-runtime compatibility** — the same codebase works
with both Docker and Podman without any user-side aliases or PATH modifications.

---

## 3. Design Decision: Volume Permissions

We chose **Dockerfile `chown`/`--chown`** over the `:U` volume flag because:

- The `:U` flag is **Podman-only**. Docker Compose does not recognize it and will error.
- Adding `:U` would break Docker compatibility, defeating the dual-runtime goal.
- Dockerfile-level ownership (`COPY --chown=app:app ...`) works identically on both runtimes.
- For bind-mounted volumes, the non-root user in the container can read world-readable
  files and write to world-writable directories (`/tmp`). No special flags needed.

---

## 4. Files Changed Summary

### New Files
| File | Purpose |
|------|---------|
| `scripts/container-runtime.sh` | Shared runtime detection (exports `$CONTAINER_RT`) |
| `scripts/compose.sh` | Compose command auto-detection wrapper |

### Modified Files
| File | Change |
|------|--------|
| `docker/Dockerfile.runtime` | Added non-root user `app` + `USER` directive |
| `docker-compose.yml` | `CONTAINER_SOCK` env var for Dozzle; updated header comments |
| `docker/generate-certs.sh` | Explicit `chmod` for cert/key permissions |
| `.env.example` | Added `CONTAINER_SOCK` documentation |
| `scripts/backup_all.sh` | Runtime detection via `$CONTAINER_RT` |
| `scripts/restore_all.sh` | Runtime detection via `$CONTAINER_RT` |
| `scripts/auto_scale_workers.py` | `_detect_container_runtime()` + `CONTAINER_RT` |
| `scripts/watch_tuning_signals.py` | `_detect_container_runtime()` + `CONTAINER_RT` |
| `README.md` | Podman Setup section; `compose.sh` references |
| `docs/operations/PODMAN_SPEC.md` | Fixed inaccuracies; added missing scope items |
| `docs/operations/PODMAN_IMPLEMENTATION.md` | Aligned with spec; made intern-friendly |

---

## 5. Verification Checklist

After applying these changes, verify:

- [ ] `source scripts/container-runtime.sh && echo $CONTAINER_RT` prints `podman` or `docker`
- [ ] `./scripts/compose.sh version` prints the compose version
- [ ] `./scripts/compose.sh up -d` starts Temporal infrastructure
- [ ] `./scripts/compose.sh --profile app up -d` starts the API
- [ ] `./scripts/compose.sh --profile workers up -d` starts workers
- [ ] Worker runs as non-root: `$CONTAINER_RT exec <worker> whoami` returns `app`
- [ ] Dozzle connects to logs when monitoring profile is started
- [ ] `bash docker/generate-certs.sh` creates certs with correct permissions
- [ ] Backup/restore scripts work: `./scripts/backup_all.sh test && echo OK`
