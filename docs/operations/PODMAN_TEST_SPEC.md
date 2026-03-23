# Podman Integration — Test Specification

**Status**: Active
**Date**: 2026-03-23
**Test file**: `tests/test_podman_migration.py`

**Related documents:**
- Specification: `docs/operations/PODMAN_SPEC.md`
- Architecture: `docs/operations/PODMAN_ARCHITECTURE.md`

---

## 1. Test Strategy

### 1.1 Approach: Static Code Analysis

All tests are **static** — they read file contents and verify patterns, structure, and consistency.
They do **not** require Docker, Podman, or any container runtime to be installed or running.

**Rationale:**
- Tests run in CI environments that may not have container runtimes.
- The migration's correctness can be verified by checking that files contain the right patterns.
- Runtime behavior (containers actually starting) is verified via smoke tests in the verification checklist.

### 1.2 What the Tests Verify

The test suite answers one question: **"Do all files in the codebase correctly support Podman as the primary runtime and Docker as a fallback?"**

This breaks down into:

1. **Detection scripts exist and are correct** — `container-runtime.sh` and `compose.sh` detect runtimes in the right order with proper safety guards.
2. **Dockerfiles enforce non-root users** — Both `Dockerfile.api` and `Dockerfile.runtime` have `USER` directives for non-root container processes.
3. **Compose config is runtime-agnostic** — `docker-compose.yml` uses env vars for runtime-specific paths (e.g., `CONTAINER_SOCK`).
4. **Scripts don't hardcode `docker`** — Shell and Python scripts use `$CONTAINER_RT` or `CONTAINER_RT` instead of literal `"docker"`.
5. **Documentation references the wrapper** — `README.md` and `.env.example` point users to `./scripts/compose.sh` and document Podman setup.
6. **Cross-file consistency** — USER names, detection order, and socket defaults match across all files.

---

## 2. Test Matrix

### 2.1 Test Classes

| # | Test Class | Scope | Count | Requirement |
|---|-----------|-------|-------|-------------|
| A | `TestShellScripts` | `container-runtime.sh`, `compose.sh` | 10 | R-B5, R-B7 |
| B | `TestDockerfiles` | `Dockerfile.runtime`, `Dockerfile.api` | 7 | R-B1, R-B4 |
| C | `TestDockerCompose` | `docker-compose.yml` | 6 | R-B2, R-B3 |
| D | `TestScriptMigration` | Shell + Python scripts | 12 | R-B7 |
| E | `TestEnvironmentAndDocs` | `.env.example`, `README.md` | 5 | R-B5 |
| F | `TestCrossFileConsistency` | Cross-file invariants | 7 | R-B1, R-B2, R-B7 |

**Total: 47 tests**

---

## 3. Detailed Test Descriptions

### 3.1 Class A: TestShellScripts

Tests for the two shell helper scripts that form the runtime detection layer.

| # | Test | What It Verifies | Failure Means |
|---|------|-----------------|---------------|
| A1 | `test_container_runtime_exports_container_rt` | `container-runtime.sh` contains `export CONTAINER_RT` | Sourcing scripts won't inherit the variable |
| A2 | `test_container_runtime_sets_container_rt` | Assigns `CONTAINER_RT` to `"podman"` or `"docker"` | Variable may be unset or set to wrong value |
| A3 | `test_compose_sh_is_executable` | `compose.sh` has the executable bit (`S_IXUSR`) | `./scripts/compose.sh` won't run without `bash` prefix |
| A4 | `test_compose_sh_has_correct_shebang` | `compose.sh` starts with `#!/...bash` | Script may run with wrong interpreter |
| A5 | `test_container_runtime_prefers_podman` | `podman` detection appears before `docker` detection | Docker would be selected even when Podman is available |
| A6 | `test_compose_sh_prefers_podman_compose` | `podman-compose` check appears before `docker compose` check | Wrong compose tool selected on dual-runtime hosts |
| A7 | `test_container_runtime_has_safety_flags_or_guard` | Has `set -euo pipefail` or `exit 1` fallback | Script might continue with unset `CONTAINER_RT` |
| A8 | `test_compose_sh_has_safety_flags` | Has `set -euo pipefail` | Errors in detection logic silently swallowed |
| A9 | `test_container_runtime_has_correct_shebang` | `container-runtime.sh` starts with bash shebang | May fail on systems where `/bin/sh` is not bash |

### 3.2 Class B: TestDockerfiles

Tests that container images enforce non-root execution.

| # | Test | What It Verifies | Failure Means |
|---|------|-----------------|---------------|
| B1 | `test_runtime_has_user_directive` | `Dockerfile.runtime` has `USER <name>` line | Worker container runs as root |
| B2 | `test_runtime_creates_user_group` | Contains `groupadd` and `useradd` | `USER` directive references non-existent user |
| B3 | `test_runtime_creates_user_before_switching` | `useradd` appears before `USER` directive | Build fails — USER references user not yet created |
| B4 | `test_runtime_uses_chown_on_copy` | At least one `COPY --chown=...` directive | Application files owned by root inside container |
| B5 | `test_api_has_user_directive` | `Dockerfile.api` has `USER` directive | API container runs as root |
| B6 | `test_runtime_user_is_not_root` | `USER` value is not `"root"` | Non-root directive is present but set to root |

### 3.3 Class C: TestDockerCompose

Tests that `docker-compose.yml` is compatible with both runtimes.

| # | Test | What It Verifies | Failure Means |
|---|------|-----------------|---------------|
| C1 | `test_dozzle_uses_container_sock_env_var` | Raw text contains `${CONTAINER_SOCK:-` | Dozzle socket path is hardcoded (breaks Podman) |
| C2 | `test_dozzle_does_not_hardcode_docker_sock` | Dozzle service has volumes | Dozzle volume mount is missing entirely |
| C3 | `test_all_expected_services_exist` | All 16 expected services are present | Service was accidentally removed during migration |
| C4 | `test_extra_hosts_preserved` | `rag-api` and `rag-worker` have `host.docker.internal` in `extra_hosts` | Container-to-host networking broken |

### 3.4 Class D: TestScriptMigration

Tests that operational scripts use runtime detection instead of hardcoded `docker`.

| # | Test | What It Verifies | Failure Means |
|---|------|-----------------|---------------|
| D1 | `test_backup_does_not_hardcode_docker_exec` | No bare `docker exec` in `backup_all.sh` (excluding comments) | Backup fails on Podman hosts |
| D2 | `test_backup_sources_container_runtime` | `backup_all.sh` sources `container-runtime.sh` | `$CONTAINER_RT` is unset during backup |
| D3 | `test_restore_does_not_hardcode_docker_commands` | No bare `docker exec/cp/ps/restart` in `restore_all.sh` | Restore fails on Podman hosts |
| D4 | `test_restore_sources_container_runtime` | `restore_all.sh` sources `container-runtime.sh` | `$CONTAINER_RT` is unset during restore |
| D5 | `test_auto_scale_has_detect_function` | `auto_scale_workers.py` defines `_detect_container_runtime()` | No runtime detection in autoscaler |
| D6 | `test_auto_scale_has_container_rt_variable` | Module-level `CONTAINER_RT = _detect_container_runtime()` | Subprocess calls use wrong binary |
| D7 | `test_auto_scale_no_hardcoded_docker_in_subprocess` | No `"docker"` in subprocess calls outside detection functions | Scaling operations fail on Podman |
| D8 | `test_watch_tuning_has_detect_function` | `watch_tuning_signals.py` defines `_detect_container_runtime()` | No runtime detection in tuning watcher |
| D9 | `test_watch_tuning_has_container_rt_variable` | Module-level `CONTAINER_RT = _detect_container_runtime()` | Stats collection uses wrong binary |
| D10 | `test_watch_tuning_no_hardcoded_docker_in_subprocess` | No `"docker"` in subprocess calls outside detection function | Monitoring fails on Podman |
| D11 | `test_generate_certs_has_chmod_644` | `generate-certs.sh` contains `chmod 644` | Cert unreadable in rootless mode |
| D12 | `test_generate_certs_has_chmod_600` | `generate-certs.sh` contains `chmod 600` | Private key has overly permissive access |

### 3.5 Class E: TestEnvironmentAndDocs

Tests that documentation guides users to the correct Podman setup.

| # | Test | What It Verifies | Failure Means |
|---|------|-----------------|---------------|
| E1 | `test_env_example_contains_container_sock` | `.env.example` documents `CONTAINER_SOCK` | Podman users don't know how to configure the socket |
| E2 | `test_readme_mentions_podman` | `README.md` contains "Podman" or "podman" | Users don't know Podman is supported |
| E3 | `test_readme_references_compose_sh` | `README.md` contains `./scripts/compose.sh` | Users run bare `docker compose` which may not work |
| E4 | `test_readme_has_podman_setup_section` | `README.md` has a heading matching `Podman Setup` | No onboarding path for Podman users |
| E5 | `test_readme_does_not_use_bare_docker_compose_in_commands` | No `docker compose` in fenced code blocks (excluding comments) | Documentation tells users to use Docker-only commands |

### 3.6 Class F: TestCrossFileConsistency

Tests that migration changes are internally consistent across multiple files.

| # | Test | What It Verifies | Failure Means |
|---|------|-----------------|---------------|
| F1 | `test_user_name_matches_across_dockerfiles` | `USER` is `app` in both Dockerfiles | Permission mismatches between API and worker containers |
| F2 | `test_container_sock_default_is_docker_socket` | `CONTAINER_SOCK` default is `/var/run/docker.sock` | Docker users need extra configuration |
| F3 | `test_detection_order_consistent_shell_scripts` | Both shell scripts check Podman before Docker | Inconsistent runtime selection depending on entry point |
| F4 | `test_python_scripts_detection_order_matches_shell` | Python detection matches shell detection order | Different runtime selected for scaling vs compose operations |
| F5 | `test_backup_restore_both_source_same_script` | Both backup and restore source `container-runtime.sh` | One script might use a different detection mechanism |
| F6 | `test_python_scripts_use_shutil_which_for_detection` | Both Python scripts use `shutil.which()` | Fragile detection via subprocess or PATH scanning |

---

## 4. Requirement Traceability

| Requirement | Tests | Coverage |
|-------------|-------|----------|
| R-B1: Rootless Execution | B1, B2, B3, B4, B5, B6, F1 | USER directives, non-root enforcement |
| R-B2: Compose Compatibility | C1, C2, C3, C4, F2 | Env vars, service preservation, extra_hosts |
| R-B3: Monitoring Without Docker Socket | C1, C2, E1 | CONTAINER_SOCK env var, documentation |
| R-B4: Worker Non-Root | B1, B2, B3, B4, B6, F1 | Dockerfile.runtime user setup |
| R-B5: Developer Experience | A3, A4, A7, A8, E1–E5 | Script usability, documentation |
| R-B7: Runtime Detection | A1, A2, A5, A6, A9, D1–D12, F3–F6 | All scripts detect and prefer Podman |

---

## 5. Running the Tests

```bash
# Run all Podman tests
python3 -m pytest tests/test_podman_migration.py -v

# Run a specific test class
python3 -m pytest tests/test_podman_migration.py::TestShellScripts -v

# Run a single test
python3 -m pytest tests/test_podman_migration.py::TestDockerfiles::test_runtime_has_user_directive -v
```

### Prerequisites

- Python 3.10+
- `pytest` and `pyyaml` installed (both are in `pyproject.toml` dev dependencies)
- No Docker or Podman runtime needed

### Expected Output

All 47 tests should pass:

```
tests/test_podman_migration.py::TestShellScripts::test_container_runtime_exports_container_rt PASSED
tests/test_podman_migration.py::TestShellScripts::test_container_runtime_sets_container_rt PASSED
...
========================= 47 passed in 0.XXs =========================
```

---

## 6. Adding New Tests

When adding Podman-related functionality:

1. **Identify the requirement** — Which `R-B*` requirement does the change relate to?
2. **Choose the test class** — Place the test in the class that matches the scope.
3. **Follow the pattern** — Read file content via fixture, assert on patterns using regex.
4. **Keep tests static** — No subprocess calls, no runtime dependencies.
5. **Update this document** — Add the test to the relevant table in section 3.

### Test Naming Convention

```
test_<scope>_<what_it_verifies>
```

Examples:
- `test_backup_sources_container_runtime`
- `test_runtime_user_is_not_root`
- `test_detection_order_consistent_shell_scripts`
