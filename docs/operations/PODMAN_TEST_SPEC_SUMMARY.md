# Podman Integration — Test Specification Summary

## 1) Generic System Overview

### Purpose

This system validates that a container runtime migration has been performed correctly — specifically, that all files in a codebase have been updated to treat a rootless-capable container runtime as the primary runtime, with the incumbent runtime as a fallback. Without this verification layer, migration regressions would go undetected until deployment, when containers fail to start, non-root enforcement is absent, or monitoring components break due to hardcoded socket paths. The test suite provides rapid, environment-agnostic assurance that the migration is complete and internally consistent.

### How It Works

The test suite is organized into six groups of static checks, each targeting a distinct concern area. A file-content fixture layer reads the relevant source files once and makes their content available to all tests in the group, avoiding repeated disk access and keeping tests hermetically isolated from runtime state.

The first group inspects runtime detection scripts to confirm they export the correct environment variable, prefer the newer runtime over the fallback in detection order, and fail safely when neither runtime is available. The second group inspects container image build files to confirm that non-root user setup is performed correctly and in the right order before the user switch directive. The third group inspects the service composition configuration to confirm that socket paths are parameterized via environment variables rather than hardcoded, that all expected services remain present, and that cross-host networking entries are preserved. The fourth group inspects operational scripts — both shell and interpreted — to confirm that each sources or calls the shared detection layer instead of invoking a hardcoded runtime binary. The fifth group inspects documentation and environment configuration to confirm that users are directed to the runtime-agnostic wrapper and that Podman setup is documented as a first-class path. The sixth group performs cross-file consistency checks, asserting that the user identity, socket default, and detection order are uniform across all files that define them.

All checks are static pattern matches — no container runtime, socket, or network connection is required to run them. This makes the suite executable in CI environments without elevated privileges or installed runtimes.

### Tunable Knobs

Operators can run the full suite or target individual test groups to isolate a concern area. Individual test cases within a group can also be targeted by name. The suite requires only a standard test runner and a YAML parsing library; both are managed as development dependencies in the project's package manifest, so no additional environment setup is needed beyond a normal development install.

### Design Rationale

The static analysis approach was chosen deliberately over integration-style tests that invoke actual runtimes. Integration tests would require CI environments to have both runtimes installed and running, creating a fragile dependency that defeats the purpose of the tests — which is to verify migration correctness, not runtime behavior. Since the migration's correctness is structural (files must contain the right patterns), pattern-based static analysis is both sufficient and more portable. Grouping tests by concern area rather than by file makes the failure signal more actionable: a failing group immediately tells the operator which category of migration gap to investigate.

### Boundary Semantics

Entry point: the test suite is invoked by the test runner against the project's source tree. It reads file content from the working directory at test execution time and asserts on patterns within that content. Exit point: the suite produces a pass/fail result for each of the 47 checks, grouped by concern class. State is not persisted between runs. The suite does not modify any files; it only reads them. Responsibility ends at pattern verification — runtime behavior such as whether containers actually start or the correct binary is resolved at execution time falls outside scope and is deferred to a manual smoke-test checklist.

---

## 2) Header

| Field | Value |
|---|---|
| **Companion spec** | `docs/operations/PODMAN_SPEC.md` |
| **Companion architecture** | `docs/operations/PODMAN_ARCHITECTURE.md` |
| **Test file** | `tests/test_podman_migration.py` |
| **Spec date** | 2026-03-23 |
| **Status** | Active |
| **Purpose** | Concise digest of the Podman integration test specification — scope, structure, coverage, and key decisions |

---

## 3) Scope and Boundaries

**Entry point:** The test runner invokes the suite against the project's working directory. No runtime dependencies are required.

**Exit point:** Pass/fail results for 47 static checks across 6 test classes.

**In scope:**
- Runtime detection shell scripts (`container-runtime.sh`, `compose.sh`)
- Container image build files (`Dockerfile.runtime`, `Dockerfile.api`)
- Service composition configuration (`docker-compose.yml`)
- Operational shell and interpreted scripts (`backup_all.sh`, `restore_all.sh`, `auto_scale_workers.py`, `watch_tuning_signals.py`, `generate-certs.sh`)
- Environment configuration template (`.env.example`)
- Project documentation (`README.md`)
- Cross-file consistency invariants (user identity, socket default, detection order)

**Out of scope:**
- Runtime behavior (container start, image build, network connectivity)
- End-to-end smoke testing (deferred to manual verification checklist)
- Performance or load characteristics of the containerized system

---

## 4) Architecture / Pipeline Overview

```
Test Runner invocation
        |
        v
 File Content Fixtures  <-- reads project source files
        |
        v
 +---------+-----------+-----------+-----------+----------+----------+
 |         |           |           |           |          |          |
 A         B           C           D           E          F
Shell    Dockerfiles  Compose   Scripts    Env/Docs  Cross-File
Scripts              Config              Coverage  Consistency
(10)      (7)         (6)        (12)       (5)        (7)
        |
        v
  Pass / Fail (47 total checks)
```

Stage descriptions:
- **A — Shell Scripts:** Detection order, export, safety flags, shebang
- **B — Dockerfiles:** USER directive, user creation order, chown, non-root enforcement
- **C — Compose Config:** Socket env var parameterization, service completeness, networking
- **D — Script Migration:** Runtime sourcing, absence of hardcoded binary references, cert permissions
- **E — Environment and Docs:** Socket var documentation, Podman setup section, compose wrapper references
- **F — Cross-File Consistency:** User identity, socket default, detection order uniformity

---

## 5) Requirement Framework

The spec traces tests to a set of behavioral requirements using an `R-B*` naming convention. Each requirement maps to one or more test classes that together provide coverage.

| Requirement Family | Coverage Area |
|---|---|
| R-B1 | Rootless execution — USER directives and non-root enforcement |
| R-B2 | Compose compatibility — env var parameterization and service preservation |
| R-B3 | Monitoring without hardcoded socket paths |
| R-B4 | Worker container non-root setup |
| R-B5 | Developer experience — script usability and documentation |
| R-B7 | Runtime detection — all scripts detect and prefer the primary runtime |

Tests are named using the convention `test_<scope>_<what_it_verifies>`. Each test entry in the spec includes the test name, what it verifies, and what a failure means operationally.

---

## 6) Functional Coverage Domains

Six test classes form the coverage map:

- **TestShellScripts (A — 10 tests):** Verifies that detection scripts export the runtime variable, prefer the primary runtime, enforce correct shebang, and fail safely on detection failure. Traces to R-B5, R-B7.

- **TestDockerfiles (B — 7 tests):** Verifies that both container image build files create a named non-root user before switching to it, use `--chown` on file copies, and do not set the user directive to root. Traces to R-B1, R-B4.

- **TestDockerCompose (C — 6 tests):** Verifies that the monitoring service uses an environment-variable socket path, all 16 expected services are present, and cross-host networking entries are preserved. Traces to R-B2, R-B3.

- **TestScriptMigration (D — 12 tests):** Verifies that backup, restore, autoscaling, and monitoring scripts source the shared detection layer and do not reference the runtime binary directly. Also verifies that certificate generation uses correct file permission modes for rootless operation. Traces to R-B7.

- **TestEnvironmentAndDocs (E — 5 tests):** Verifies that the environment template documents the socket variable, the project README mentions the primary runtime by name, references the compose wrapper, includes a setup section, and avoids runtime-specific commands in code blocks. Traces to R-B5.

- **TestCrossFileConsistency (F — 7 tests):** Verifies that user identity matches across image build files, socket default is backward-compatible, detection order is consistent between shell and interpreted scripts, and both operational scripts source the same detection mechanism. Traces to R-B1, R-B2, R-B7.

---

## 7) Non-Functional and Security Themes

- **Portability:** All tests are stateless static checks; no runtime, socket, or privilege escalation is required.
- **CI compatibility:** The suite is designed to run in locked-down CI environments with no container infrastructure.
- **Security — non-root enforcement:** A dedicated test class and cross-file consistency group together ensure that containers cannot accidentally run as root, and that the user setup sequence is correct.
- **Security — file permissions:** Certificate permission modes are explicitly checked to prevent over-permissive private key access and under-permissive public cert access in rootless contexts.
- **Fail-safe detection:** Tests assert that detection scripts have safety flags or explicit exit fallbacks, preventing silent failure when neither runtime is installed.

---

## 8) Design Principles

- **Static over dynamic:** Tests verify structure and patterns, not runtime behavior, to avoid infrastructure dependencies.
- **Concern-grouped classes:** Each test class targets one migration concern area, making failures immediately actionable.
- **Operational failure semantics documented:** Every test entry records what a failure means in production, not just what the assertion checks.
- **Single detection mechanism:** All scripts and services must share one runtime detection source of truth — cross-file consistency tests enforce this.
- **Backward-compatible defaults:** Socket and runtime defaults must not require existing Docker users to change configuration.

---

## 9) Key Decisions

- **47 total tests across 6 classes** — scope chosen to cover all files modified during the migration without over-testing implementation details that are likely to change.
- **No subprocess or runtime calls in tests** — a deliberate constraint to keep the suite portable and fast.
- **Cross-file consistency as a first-class class** — rather than embedding consistency checks inside individual file-focused classes, consistency is promoted to its own class (F) so that cross-file invariant failures are immediately distinguishable from single-file failures.
- **Requirement traceability included in spec** — each `R-B*` requirement is mapped to the tests that cover it, making gap analysis straightforward as new functionality is added.
- **Test naming convention enforced** — `test_<scope>_<what_it_verifies>` produces self-documenting test names that describe the assertion without needing to read the body.

---

## 10) Acceptance and Evaluation

The spec defines a clear acceptance condition: all 47 tests pass. The expected output section shows the exact pytest summary line format.

The spec also defines an extension contract: when new Podman-related functionality is added, the contributor must identify the relevant `R-B*` requirement, place the new test in the appropriate class, keep it static, and update the spec's test table. This prevents coverage drift as the system evolves.

---

## 11) External Dependencies

| Dependency | Type | Role |
|---|---|---|
| Python 3.10+ | Required | Test execution runtime |
| pytest | Required (dev) | Test runner framework |
| pyyaml | Required (dev) | YAML parsing for compose file tests |
| Container runtime (Docker or Podman) | Not required | Intentionally excluded — no runtime needed |

Both development dependencies are declared in the project's package manifest and are available in the standard development install.

---

## 12) Companion Documents

This summary is a digest of `docs/operations/PODMAN_TEST_SPEC.md`. It captures scope, structure, coverage domains, and key decisions. It does not reproduce individual test descriptions, requirement traceability rows, or the running instructions — those live in the companion spec.

Related documents in the same subsystem:
- `docs/operations/PODMAN_SPEC.md` — behavioral requirements the tests verify against
- `docs/operations/PODMAN_ARCHITECTURE.md` — architecture document for the migration

---

## 13) Sync Status

| Field | Value |
|---|---|
| **Spec version** | 2026-03-23 (Active) |
| **Summary written** | 2026-04-10 |
| **Aligned to** | `PODMAN_TEST_SPEC.md` as of 2026-03-23 |
