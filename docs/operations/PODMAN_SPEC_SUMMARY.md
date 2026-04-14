# Podman Migration — Specification Summary

## 1) Generic System Overview

### Purpose

The container runtime migration system replaces a privileged, daemon-based container engine with a daemonless, unprivileged alternative across the full platform stack. The existing setup runs all containers under a root-owned background service, which creates an unnecessarily large privilege surface: any container compromise can potentially escalate through the shared daemon process or its globally accessible socket. This migration eliminates that attack class by shifting to a model where containers are launched directly by the invoking user, with no persistent root process mediating them.

### How It Works

The migration operates as a compatibility-preserving swap at the runtime layer. Existing container image definitions, compose service declarations, health checks, and volume configurations remain structurally unchanged — the migration targets only the execution substrate and the operational scripts that invoke it.

A shared runtime detection script runs first whenever a container operation is requested. It probes the host environment, identifies which container engine is available, and exports a canonical variable that all subsequent scripts consume. This indirection makes all scripts dual-runtime without duplicating logic.

The compose invocation path is wrapped by a thin dispatcher script that selects the correct compose command for the detected runtime. Service profiles, environment variable injection, and health check evaluation all flow through this wrapper unchanged.

Container image definitions are updated minimally: the one worker image that previously ran as the root user inside the container receives a new non-root user definition. All other images already ran as unprivileged users and require no changes.

The container log monitoring service previously relied on a hardcoded path to the root-owned daemon socket. This is replaced with an environment-variable-driven socket path so that the correct per-user socket is mounted when running under the unprivileged runtime, while the default value preserves backward compatibility with the root daemon for any environments that have not yet migrated.

### Tunable Knobs

**Socket path**: Operators can configure which container socket the monitoring service mounts. The default targets the root daemon socket for backward compatibility; migrated environments override this to point at the user-scoped socket.

**Runtime preference**: The detection script checks for the unprivileged runtime first, then falls back to the root daemon. Operators can influence resolution order if both runtimes are installed and a specific preference is needed.

**Worker user identity**: The non-root user added to the worker image can be configured to match whatever UID mapping strategy the host's namespace isolation requires. Volume permissions are enforced at image build time to ensure that read-only model mounts remain accessible under this identity.

### Design Rationale

The migration is designed for zero-disruption compatibility: image definitions and compose files must continue to work on both runtimes simultaneously. This rules out any runtime-specific volume flag or compose extension that one engine understands but the other does not. The compatibility constraint drives the choice to manage volume permissions at image build time rather than via mount flags, and to keep the compose file syntax at the lowest common denominator.

Detection-first architecture was chosen over hardcoding the new runtime because development, CI, and production environments may standardize on different engines. Forcing a single runtime would break cross-environment portability and require duplicate maintenance of scripts.

### Boundary Semantics

Entry point: any developer or automated process invoking a container lifecycle operation (start, stop, exec, backup, restore, scale). The migration intercepts these at the script layer by inserting runtime detection before any engine-specific command is issued.

Exit point: running containers that are functionally identical to the pre-migration state — same services, same networking, same health status — but executing under unprivileged process isolation rather than through a root daemon.

State maintained across the migration: image layer caches, named volumes, and environment configuration. State discarded: any assumption of a running root daemon or a globally accessible daemon socket.

---

## 2) Header

| Field | Value |
|-------|-------|
| Companion spec | `docs/operations/PODMAN_SPEC.md` |
| Spec status | Draft |
| Spec date | 2026-03-14 |
| Spec last updated | 2026-03-23 |
| Summary purpose | Digest of intent, scope, requirements, and key decisions for the Podman migration |

---

## 3) Scope and Boundaries

**Entry point:** Any container lifecycle operation invoked by a developer or automated pipeline — compose up/down, exec, backup, restore, scaling, log monitoring.

**Exit point:** A fully operational stack running under rootless container execution, with all operational scripts, monitoring, and tooling working transparently on both the new and legacy runtimes.

### In Scope

- Container runtime replacement (root daemon → daemonless, unprivileged engine)
- Compose tooling wrapper and runtime auto-detection script
- Compose file compatibility (no engine-specific syntax)
- Worker image update: add non-root user and USER directive
- Monitoring service: socket path made configurable via environment variable
- Certificate generation script: permission handling for rootless mode
- Backup, restore, and auto-scaling scripts: replace hardcoded runtime with detection helper
- Worker-tuning signal script: replace hardcoded runtime reference
- Developer documentation: setup steps and compose wrapper usage

### Out of Scope

- Kubernetes / pod-level orchestration
- Remote container engine access
- Separate image build tooling (unprivileged build is built into the new engine)
- Extra-hosts alias resolution (works identically on both runtimes; no change needed)

---

## 4) Architecture / Pipeline Overview

```
Developer / CI invokes container operation
         |
         v
 scripts/compose.sh          <-- thin wrapper: selects correct compose command
         |
         v
 scripts/container-runtime.sh  <-- detects available runtime; exports $CONTAINER_RT
         |
         +-----------> podman-compose / podman compose   (if Podman available)
         |
         +-----------> docker compose                    (fallback)
         |
         v
 docker-compose.yml           <-- unchanged; OCI-compatible service definitions
         |
         v
 Running containers
   - API service              (already non-root; no change)
   - Worker service           (updated: non-root user added)
   - Monitoring (Dozzle)      (socket path driven by CONTAINER_SOCK env var)
   - All other services       (unchanged)
         |
         v
 Operational scripts (backup, restore, scale, tuning)
   Source container-runtime.sh → use $CONTAINER_RT instead of hardcoded "docker"
```

---

## 5) Requirement Framework

Requirements are labeled **R-B{n}**, where `n` corresponds to a goal ID from the goals table. Each requirement includes:

- **SHALL / MUST** language for mandatory items
- Explicit acceptance criteria with verifiable checklist items
- Direct mapping to one or more affected components

The spec uses a goals table (B1–B7) as the traceability anchor, with requirements and acceptance criteria per goal. A traceability matrix in Section 7 maps each requirement to its smoke test and affected component.

---

## 6) Functional Requirement Domains

| Domain | Requirement IDs | Coverage |
|--------|-----------------|----------|
| Rootless execution | R-B1 | All containers must run without root; worker image updated to non-root user |
| Compose compatibility | R-B2 | Compose file must work on both runtimes; socket env var defaults to legacy path |
| Log monitoring | R-B3 | Monitoring socket mount made configurable; no root-owned socket under new runtime |
| Worker non-root identity | R-B4 | Worker image gains non-root user; volume mounts verified accessible |
| Developer experience | R-B5 | Compose wrapper, runtime detection helper, and updated documentation |
| Runtime detection | R-B7 | Shared detection script; all shell and Python scripts updated to use it |

---

## 7) Non-Functional and Security Themes

**Performance**
- Container startup time must remain within an acceptable margin of the current baseline.

**Security**
- Rootless mode is the required default; root-mode operation must not be documented or promoted.
- No container may mount a root-owned socket.
- Certificate generation workflow must function correctly under unprivileged execution.

**Testing**
- Full stack smoke test (all service profiles: up, health check, down) required before migration is marked complete.
- All items in the implementation test matrix must pass.

---

## 8) Design Principles

- **Compatibility first** — changes must not break environments still running the legacy runtime.
- **No engine-specific syntax in shared artifacts** — compose files and Dockerfiles must remain valid on both runtimes.
- **Detection over configuration** — runtime selection is automatic; operators should not need to manually configure which engine is used in most cases.
- **Permissions at build time** — volume and file permission handling is resolved in the image definition, not at mount time, to avoid engine-specific mount flags.
- **Rootless by default** — the unprivileged engine is the preferred runtime; the legacy engine is the fallback only.

---

## 9) Key Decisions

- **Socket path via environment variable**: Rather than patching the monitoring service's compose entry for each runtime, a single configurable env var handles both cases with a sensible default.
- **No `:U` volume flag**: The engine-specific volume ownership flag is explicitly excluded from all compose and mount definitions to preserve cross-runtime compatibility.
- **Wrapper script over alias**: A standalone compose wrapper script is used instead of a shell alias so that CI pipelines and automation can invoke it without shell profile loading.
- **Detection order — unprivileged engine first**: When both runtimes are installed, the unprivileged engine takes precedence to nudge environments toward the more secure option without requiring manual reconfiguration.
- **Python scripts use dynamic detection**: Operational Python scripts that previously embedded the runtime name as a string literal are updated to detect the runtime at invocation time using the same detection logic as shell scripts.

---

## 10) Acceptance and Evaluation

The spec defines per-requirement acceptance criteria as verifiable checklist items. Acceptance themes are:

- **Rootless verification**: Runtime reports unprivileged mode; no container runs as UID 0.
- **Full-stack start**: All service profiles start successfully through the compose wrapper.
- **Health check pass**: All services pass their defined health checks after startup.
- **Monitoring functionality**: Log streaming works from the monitoring UI without a root-owned socket.
- **Worker identity**: Worker container exec confirms non-root user identity.
- **Script portability**: Runtime detection exports the correct binary; all operational scripts function on both runtimes.
- **Developer onboarding**: A new developer can start the full stack following the updated documentation alone.

---

## 11) External Dependencies

| Dependency | Type | Notes |
|------------|------|-------|
| Unprivileged container engine | Required (new runtime) | Must be installed and user socket enabled for monitoring |
| Compose plugin / companion tool | Required | Either the engine's built-in compose or the standalone compose tool |
| Systemd user session | Required (monitoring) | User socket is managed as a systemd user service |
| OCI-compatible registries | Required (existing) | No change; same registries used by both runtimes |
| Legacy container engine | Optional (fallback) | Supported as fallback by detection script; not required if new runtime is present |

---

## 12) Companion Documents

This summary is a digest of `PODMAN_SPEC.md` (the Layer 3 authoritative spec). It covers intent, scope, requirement domains, and key decisions. It does not reproduce individual requirement text, acceptance criteria values, or the traceability matrix — refer to the companion spec for those.

The spec references an implementation guide for the full test matrix and step-by-step migration procedure.

---

## 13) Sync Status

| Field | Value |
|-------|-------|
| Aligned to spec version | Draft (2026-03-23) |
| Summary written | 2026-04-10 |
| Next sync trigger | When spec status changes from Draft, or when scope/requirements are updated |
