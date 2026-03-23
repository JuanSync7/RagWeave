# Podman Migration — Specification

**Status**: Draft
**Date**: 2026-03-14
**Updated**: 2026-03-19

---

## 1. Overview

### 1.1 Problem Statement

The RAG platform currently uses Docker with a root daemon for container orchestration:

- **Docker requires a root daemon** — `dockerd` runs as root. The Dozzle monitoring container
  mounts `/var/run/docker.sock`. The worker Dockerfile runs as root. This conflicts with
  security hardening goals and increases the blast radius of any container compromise.

### 1.2 Why Podman over Docker

Podman is a daemonless, rootless OCI container engine that is CLI-compatible with Docker.
Replacing Docker with Podman eliminates the root daemon requirement while preserving
the full Docker workflow.

#### Architecture Comparison

| Aspect | Docker | Podman |
|--------|--------|--------|
| Process model | Client → root daemon (`dockerd`) | Fork/exec — no daemon |
| Root required | Yes (daemon runs as root) | No — rootless by default |
| Socket | `/var/run/docker.sock` (root-owned) | User socket in `$XDG_RUNTIME_DIR` |
| Single point of failure | Daemon crash kills all containers | No daemon to crash |
| Image format | OCI (compatible) | OCI (compatible) |
| Registries | Docker Hub, any OCI registry | Same |
| Systemd integration | Wrapper required | Native (`podman generate systemd`) |
| Compose support | `docker compose` (plugin) | `podman-compose` / `podman compose` |
| Kubernetes compatibility | Requires conversion | `podman play kube` built-in |

#### Key Security Benefits

- **No root daemon**: The single largest privilege reduction. A compromised container cannot
  escalate through `dockerd` because there is no `dockerd`.
- **No shared socket**: Mounting `/var/run/docker.sock` into a container is a well-known
  container escape vector. Podman's per-user socket removes this risk class entirely.
- **UID namespace isolation**: Rootless Podman maps container root to an unprivileged host UID
  via user namespaces, so a container breakout yields no host privileges.
- **Audit surface**: Every container operation is a direct `podman` subprocess owned by the
  invoking user — visible in standard OS audit logs without daemon interception.

### 1.3 Docker → Podman Swap Guide

For most workflows, swapping Docker for Podman requires no changes to images or Compose files.

#### What Stays the Same

- **Container images** — same OCI format; existing images work unchanged.
- **Compose files** — Podman supports the Compose spec; `docker-compose.yml` works as-is
  for the vast majority of syntax.
- **Health checks** — same `HEALTHCHECK` Dockerfile syntax and `healthcheck:` Compose key.
- **Volumes** — same bind-mount and named-volume syntax.
- **Registries** — `docker.io`, `quay.io`, `ghcr.io`, and any private registry work identically.

#### What Changes

| Item | Docker command/path | Podman equivalent | Notes |
|------|--------------------|--------------------|-------|
| Runtime binary | `docker` | `podman` | `alias docker=podman` covers ~95% of use |
| Compose | `docker compose` | `podman-compose` or `podman compose` | See `scripts/compose.sh` wrapper |
| Socket path | `/var/run/docker.sock` | `$XDG_RUNTIME_DIR/podman/podman.sock` | Set via `CONTAINER_SOCK` env var |
| Privileged ports | No restriction | Ports <1024 need sysctl or use >1024 | Default to 8080/8443 |
| Volume UID mapping | Implicit | Add `:U` flag for writable volumes | Safe to add; Docker ignores it |
| Daemon start | `sudo systemctl start docker` | No daemon — Podman starts on demand | Nothing to start |
| Socket enable | Always on | `systemctl --user enable --now podman.socket` | One-time user setup |

#### One-Time Setup (Rootless Podman)

```bash
# 1. Install Podman
sudo apt-get install -y podman podman-compose   # Debian/Ubuntu
# or: sudo dnf install -y podman podman-compose  # Fedora/RHEL

# 2. Enable user socket (for Dozzle monitoring)
systemctl --user enable --now podman.socket

# 3. Verify rootless mode
podman info | grep -i rootless   # should show: rootless: true

# 4. Use the compose wrapper (auto-detects Docker vs Podman)
./scripts/compose.sh --profile app up -d
```

---

## 2. Goals

| ID | Goal | Priority |
|----|------|----------|
| B1 | Replace Docker with Podman for rootless container execution | Must |
| B2 | All existing services start and run correctly under Podman | Must |
| B3 | Dozzle monitoring works without Docker socket | Should |
| B4 | Worker container runs as non-root | Must |
| B5 | CI/CD pipelines updated if applicable | Should |
| B6 | Developer documentation updated | Must |

---

## 3. Scope

### In Scope

| Component | Current State | Podman Change |
|-----------|--------------|---------------|
| Container runtime | Docker Engine (root daemon) | Podman (daemonless, rootless) |
| Compose tool | `docker compose` | `podman-compose` (or `podman compose` via plugin) |
| `docker-compose.yml` | Docker Compose v3 syntax | Compatible as-is (Podman supports Compose spec) |
| `Dockerfile.api` | Runs as non-root user `app` | No change needed |
| `Dockerfile.runtime` | Runs as root (no USER directive) | Add non-root user |
| Dozzle (`/var/run/docker.sock`) | Mounts Docker socket | Replace with Podman user socket |
| Volume mounts | Docker volumes | Podman volumes (compatible); add `:U` for writable |
| Health checks | Docker health checks | Podman supports same syntax |
| `docker/generate-certs.sh` | Uses `docker run` for permission fix | Replace with `podman run` |

### Out of Scope

| Component | Reason |
|-----------|--------|
| Kubernetes / Podman play kube | Future consideration; not in this migration |
| Remote Podman | Local development only |
| Buildah (separate build tool) | Podman includes built-in build; no need for separate tool |

---

## 4. Requirements

### R-B1: Rootless Execution

- All containers MUST run under rootless Podman (no `sudo`, no root daemon).
- `Dockerfile.runtime` MUST be updated to create and use a non-root user (matching `Dockerfile.api` pattern).
- No container MUST use `--privileged` or `--cap-add` beyond what's strictly necessary.

**Acceptance criteria:**
- [ ] `podman info` shows rootless mode.
- [ ] All services start with `podman-compose --profile app --profile workers up -d`.
- [ ] No container runs as UID 0 inside the container (except init processes that drop privileges).

### R-B2: Compose Compatibility

- `docker-compose.yml` MUST work with `podman-compose` without modification.
- If syntax differences exist, use conditional comments or a thin wrapper script.
- Volume mounts, health checks, environment variables, and profiles MUST behave identically.

**Acceptance criteria:**
- [ ] `podman-compose up -d` starts all default services.
- [ ] `podman-compose --profile app --profile workers --profile monitoring up -d` starts full stack.
- [ ] Health checks pass for all services.

### R-B3: Monitoring Without Docker Socket

- Dozzle currently requires `/var/run/docker.sock` to stream container logs.
- Options (pick one):
  1. Mount Podman's user socket: `$XDG_RUNTIME_DIR/podman/podman.sock`
  2. Replace Dozzle with `podman logs --follow` wrapper
  3. Use Podman's systemd journal integration for log aggregation

**Acceptance criteria:**
- [ ] Container log streaming works from the monitoring UI.
- [ ] No root-owned socket is mounted into any container.

### R-B4: Worker Non-Root

- `Dockerfile.runtime` MUST add a non-root user and `USER` directive.
- Model files mounted read-only (`/models:ro`) MUST be readable by the non-root user.
- Weaviate seed data copy MUST work with non-root permissions.

**Acceptance criteria:**
- [ ] Worker container starts and processes ingestion/retrieval tasks.
- [ ] `podman exec rag-rag-worker-1 whoami` returns non-root user.

### R-B5: Developer Experience

- A wrapper script (`scripts/compose.sh`) MUST detect Docker vs Podman and use the correct command.
- README and operations docs MUST document the Podman setup steps (§1.3).
- `generate-certs.sh` MUST work with Podman.

**Acceptance criteria:**
- [ ] New developer can start the full stack following updated docs.
- [ ] Script auto-detects runtime and works transparently.
- [ ] `./scripts/compose.sh` works on both Docker and Podman hosts without modification.

---

## 5. Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| `podman-compose` feature gaps | Some Compose features may not be supported | Test all profiles; fall back to `podman compose` plugin if needed |
| Rootless networking limitations | Port < 1024 binding may fail without `net.ipv4.ip_unprivileged_port_start=0` | Document sysctl requirement or use ports > 1024 |
| Volume permission mismatches | UID mapping in rootless mode may cause permission errors | Use `podman unshare` or `:U` volume flag for auto-UID mapping |
| Third-party images assume root | Some images (ClickHouse, Temporal) may require root | Test each image; use `--userns=keep-id` where needed |
| CI/CD compatibility | GitHub Actions may not have Podman pre-installed | Provide Docker fallback in CI; Podman for local dev |

---

## 6. Non-Functional Requirements

### 6.1 Performance

- Podman container startup time MUST be within 20% of Docker baseline.

### 6.2 Security

- Podman rootless MUST be the default; rootful mode MUST NOT be documented as an option.
- Self-signed certs workflow MUST work identically under Podman.
- No container MUST mount a root-owned socket.

### 6.3 Testing

- Podman smoke test: full stack up/down with health check verification.
- All test matrix cases in the implementation guide MUST pass before migration is marked complete.

---

## 7. Traceability Matrix

| Requirement | Test | Component |
|-------------|------|-----------|
| R-B1 | Smoke: `podman info` rootless | Infrastructure |
| R-B2 | Smoke: all profiles start | `docker-compose.yml` |
| R-B3 | Smoke: log streaming works | Monitoring stack |
| R-B4 | Smoke: worker whoami non-root | `Dockerfile.runtime` |
| R-B5 | Manual: new dev setup + `compose.sh` smoke | Documentation, `scripts/compose.sh` |
