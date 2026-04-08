# Safe Pytest Execution Workflow for Claude Code Agents -- Design Sketch

**Date:** 2026-04-01
**Revision:** 2 (post-stakeholder review — addressed C1, C2, I1-I5, S3-S5)
**Goal:** Let Claude Code subagents run pytest safely through a controlled wrapper
that validates test files before execution, produces structured output, and supports
an automated fix-rerun loop.

---

## Current State

The RAG project has approximately 90 test files across seven test domains:

| Domain | Path | Files | Character |
|--------|------|-------|-----------|
| Ingest | `tests/ingest/` | ~35 | Heavy stubs (torch, transformers, weaviate, minio) |
| Retrieval | `tests/retrieval/` | ~5 | Mostly pure-logic routing/schema tests |
| Guardrails | `tests/guardrails/` | ~7 | NeMo-dependent, own conftest.py for langchain fix |
| Observability | `tests/observability/` | ~6 | Langfuse backend stubs |
| Server | `tests/server/` | ~1 | Schema contract tests |
| Import Check | `tests/import_check/` | ~8 | Own conftest.py with sys.modules surgery |
| Root-level | `tests/` | ~23 | Mixed: API, cache, security, RAG chain |

**Key facts:**
- Pytest 9.0.2 with pytest-mock; no pytest-asyncio.
- Root `conftest.py` stubs six heavy packages into `sys.modules` (torch, transformers,
  weaviate, minio, sentence_transformers, langchain family).
- Two subdirectory conftest files do additional `sys.modules` manipulation (guardrails,
  import_check). This is legitimate and must be allowed by any safety validator.
- CI runs via `uv run pytest` with explicit file lists.
- `pyproject.toml` pytest config is minimal: `testpaths=["tests"]`, `pythonpath=["."]`.
- Current `settings.local.json` allows `Bash(pytest *)` and `Bash(uv run:*)` -- agents
  have unrestricted pytest access today.

**Problem:** An agent with unrestricted pytest permission can execute arbitrary code by
writing a "test" file that imports `subprocess`, `os.system`, or any other dangerous
API. There is no pre-execution validation, no structured output format for agent
consumption, and no automated fix loop.

---

## Approach Exploration

### Approach A: Single Monolithic Script

One bash script (`scripts/run-tests.sh`) does everything: validates test files via an
embedded Python call, runs pytest, captures output to JSON.

**Pros:**
- One file to maintain.
- Easy to grant in `settings.json` as a single permission.
- No coordination between components.

**Cons:**
- Validation logic buried inside a shell script (harder to test, harder to extend).
- Shell scripts are fragile for complex Python AST analysis.
- No separation between "policy" (what is dangerous) and "mechanism" (how to run tests).
- Group configuration becomes awkward shell arrays/case statements.
- The safety validator itself cannot be unit-tested without extracting it.

**Smell test:** Works for a demo. Falls apart when the safety rules need updating or
when you want to test the validator independently.

### Approach B: Layered System (Validator + Runner + Group Configs)

Three components: a Python safety validator (`scripts/check_pytest.py`), a shell runner
(`scripts/run-tests.sh`), and per-domain group config files or thin wrapper scripts.

```
settings.json allows: Bash(scripts/run-tests.sh *)
                       ^^^ single permission entry point

scripts/run-tests.sh        <-- orchestration shell script
  |
  +--> scripts/check_pytest.py <scope>   <-- AST safety validator (Python)
  |         returns 0 (pass) or 1 (fail with structured report)
  |
  +--> uv run pytest <scope> <flags>     <-- actual execution
  |
  +--> writes .tmp-test-results/         <-- structured output directory
```

**Pros:**
- Clean separation: validator is pure Python, independently testable.
- Shell script is thin orchestration only -- easy to read.
- Group configs are declarative (YAML or simple shell vars).
- Validator can be reused by hooks, CI, or other tools.
- Single permission entry point in `settings.json`.

**Cons:**
- Two languages (Python + shell) in the critical path.
- Shell script needs careful quoting for path arguments.
- One more moving part than Approach A.

**Smell test:** This is the standard unix pattern -- small tools composed via a script.
Each piece is testable. The shell layer is thin enough to be auditable.

### Approach C: Pure Python Entry Point

Everything in Python: a single `scripts/test_runner.py` that validates, invokes pytest
programmatically via `pytest.main()`, and writes JSON output.

**Pros:**
- Single language, no shell quoting issues.
- Can use pytest's programmatic API for fine-grained control.
- Timeout handling via Python's `signal` module or `subprocess` with timeout.

**Cons:**
- `pytest.main()` runs in-process, so a malicious test that passes AST validation but
  exploits a dynamic code path (e.g., `getattr` + `eval`) would run in the same process
  as the runner itself. No process isolation.
- Harder to kill a runaway pytest run from within the same process.
- Python entry point needs its own argument parsing -- reinventing shell argument handling.
- `settings.json` permission would be `Bash(python3 scripts/test_runner.py *)` which is
  arguably broader than a named script.

**Smell test:** Elegant but loses the process isolation boundary. The validator and
executor should not share an address space -- the validator approves, then a *separate*
process executes.

---

## Recommended Approach: B (Layered System)

**Rationale:** The core safety property is: validation happens in a separate process
from execution. Approach B gives this naturally -- `check_pytest.py` runs and exits
before `pytest` is ever invoked. The shell orchestration layer is thin (under 100 lines)
and auditable. The Python validator is independently testable. Group configuration is
just data.

The user's original insight is correct: allow the wrapper script globally, never give
agents raw pytest access. Approach B is the cleanest realization of this.

---

## Component Diagram

```
+---------------------+
|  Claude Code Agent   |
|  (or test-runner     |
|   skill)             |
+---------------------+
          |
          | Bash(scripts/run-tests.sh --group ingest)
          v
+---------------------+     +---------------------------+
| scripts/run-tests.sh|---->| scripts/check_pytest.py   |
| (orchestrator)      |     | (AST safety validator)    |
+---------------------+     +---------------------------+
          |                            |
          | if validator passes        | exit 0 = safe
          v                            | exit 1 = blocked (JSON report)
+---------------------+               |
| uv run pytest       |<--------------+
| --tb=short          |
| --json-report       |
| --timeout=<N>       |
+---------------------+
          |
          v
+---------------------------+
| .tmp-test-results/        |
|   report.json             |  <-- pytest-json-report output
|   validation.json         |  <-- safety validator output
|   run.log                 |  <-- captured stdout/stderr
+---------------------------+
          |
          v
+---------------------+
|  Agent reads JSON   |
|  pass -> report     |
|  fail -> fixer loop |
+---------------------+
```

---

## File Layout

```
scripts/
  run-tests.sh                 # Orchestrator: validate -> run -> capture
  check_pytest.py              # AST safety validator (standalone)
  test-groups/
    ingest.conf                # group config: paths, markers, timeout
    retrieval.conf
    guardrails.conf
    observability.conf
    server.conf
    import-check.conf
    root.conf                  # root-level tests/test_*.py
    all.conf                   # all tests (union of above)

.tmp-test-results/             # gitignored, ephemeral
  report.json                  # pytest-json-report output
  validation.json              # safety validator output
  run.log                      # stdout+stderr capture

.claude/
  settings.local.json          # updated: replace Bash(pytest *) with Bash(scripts/run-tests.sh *)

tests/
  scripts/                     # tests FOR the test infrastructure
    test_check_pytest.py       # unit tests for the AST validator
```

---

## Safety Validation Design (`check_pytest.py`)

### Core Principle

Use `ast.parse()` to build a tree of every test file in scope (including conftest.py
files in the path), then walk the tree looking for dangerous patterns. The validator
**never imports or executes** the test code -- it only reads syntax.

### Threat Model

An agent could write a test file containing dangerous operations that execute at import
time (module-level code), during fixture setup, or inside test functions. The validator
must catch these regardless of where they appear in the AST.

### Detection Categories

**Category 1: Dangerous Calls (BLOCK)**

Calls to functions that can execute arbitrary commands or code:

| Pattern | AST Shape | Action |
|---------|-----------|--------|
| `subprocess.run/call/Popen/check_output` | `ast.Call` where func resolves to `subprocess.*` | BLOCK |
| `os.system`, `os.popen`, `os.exec*` | `ast.Call` where func resolves to `os.system` etc. | BLOCK |
| `eval(...)`, `exec(...)` | `ast.Call` where func is `eval`/`exec` builtin | BLOCK |
| `compile(...)` with exec/eval mode | `ast.Call` to `compile` | BLOCK |
| `__import__(...)` | `ast.Call` to `__import__` | BLOCK |

**Detection approach:** Walk all `ast.Call` nodes. Resolve the function name by
handling `ast.Name` (bare name like `eval`) and `ast.Attribute` (dotted like
`os.system`). Maintain a mapping of import aliases to canonical names so that
`import subprocess as sp; sp.run(...)` is still caught.

**Category 2: Dangerous Imports (BLOCK)**

Importing modules whose primary purpose is executing external processes or network I/O:

| Module | Reason | Exception |
|--------|--------|-----------|
| `subprocess` | Process execution | Per-group override (see Validation Policy Overrides) |
| `socket` | Raw network access | None |
| `http.client`, `http.server` | Network I/O | None |
| `ftplib`, `smtplib`, `telnetlib` | Network I/O | None |
| `ctypes` | FFI / native code execution | None |
| `multiprocessing` | Process spawning | None |

These are blocked at the `import` statement level. If a test file says
`import subprocess`, it fails validation immediately, regardless of whether the import
is used.

**Exception:** `unittest.mock.patch("subprocess.run", ...)` as a string argument to
`mock.patch` is NOT a real import and should be allowed. The validator checks the AST
node type -- `ast.Import`/`ast.ImportFrom` are blocked; `ast.Constant` string values
inside `mock.patch()` calls are ignored.

### Validation Policy Overrides (per-group)

Some test domains legitimately need patterns that are globally blocked. For example,
`tests/import_check/test_integration.py` uses real `subprocess.run()` to initialize
git repos in `tmp_path`, and `test_inventory.py` imports `subprocess` at module level
to construct `subprocess.CompletedProcess` return values for mocks.

The group config supports a `VALIDATION_OVERRIDES` key:

```bash
# scripts/test-groups/import-check.conf
TEST_PATHS="tests/import_check/"
VALIDATION_OVERRIDES="subprocess:allow"
```

**Semantics:** `pattern:allow` downgrades a BLOCK to ALLOW for files in that group.
Multiple overrides are comma-separated: `subprocess:allow,socket:allow`.

**Constraints:**
- Overrides apply only to the specific group config, not globally.
- The validator receives overrides via `--allow <pattern>` flag.
- Only import-level blocks can be overridden. Dangerous call patterns (Category 1)
  are never overridable -- this prevents `os.system("rm -rf /")` from sneaking through
  even if `os` is allowed as an import.
- Overrides are logged in `validation.json` with `"reason": "group_override"`.

**Mock pattern resolution:** The design commits to the pragmatic approach: module-level
import of a blocked library = BLOCK (overridable via group config), function-level
import = WARN. No mock-aware AST analysis -- the complexity is not justified.

**Category 3: File System Danger (WARN or BLOCK)**

| Pattern | Condition | Action |
|---------|-----------|--------|
| `open(path, 'w'/'a'/'x')` | path does not start with `/tmp` or `tmp_path` fixture | BLOCK |
| `shutil.rmtree(path)` | path is not under `/tmp` or `tmp_path` | BLOCK |
| `os.remove(path)`, `os.unlink(path)` | path is not under `/tmp` | BLOCK |
| `Path(...).unlink()` | receiver is not `tmp_path` derived | WARN |
| `pathlib.Path(...).write_text/write_bytes` | path not under `/tmp` or `tmp_path` | WARN |

**Heuristic for tmp_path detection:** If the function signature includes a parameter
named `tmp_path` or `tmp_path_factory`, and the `open()`/`Path()` argument is derived
from that parameter (via attribute access or string formatting on that name), classify
as safe. This is a best-effort heuristic -- the AST cannot trace all data flows, but
catching `tmp_path / "file.txt"` covers 95% of cases.

**Category 4: Process/Signal Manipulation (BLOCK)**

| Pattern | Action |
|---------|--------|
| `os.kill(...)` | BLOCK |
| `signal.signal(...)` | BLOCK |
| `sys.exit(...)` | BLOCK |
| `os._exit(...)` | BLOCK |
| `os.fork()` | BLOCK |

**Category 5: Database Access (WARN)**

| Pattern | Action |
|---------|--------|
| `sqlite3.connect(...)` | WARN (unless path is `:memory:` or under `/tmp`) |
| `psycopg2.connect(...)` | BLOCK |
| `pymongo.MongoClient(...)` | BLOCK |

SQLite with `:memory:` is safe for test-only databases and should not be blocked.

**Category 6: Network Libraries (BLOCK with mock exception)**

| Library | Action |
|---------|--------|
| `requests` | BLOCK import |
| `httpx` | BLOCK import |
| `aiohttp` | BLOCK import |
| `urllib.request` | BLOCK import |

**Mock exception:** If the import appears inside a `unittest.mock.patch` context
manager or decorator, or inside a function whose body is entirely mock setup, do not
block. Detection: check if the `ast.Import`/`ast.ImportFrom` node is inside an
`ast.With` node whose context expression is a `mock.patch(...)` call.

**Pragmatic simplification:** The mock exception is complex to detect reliably via AST.
A simpler rule: if the import is at the top of the file (module level) AND the module
is in the blocked list, BLOCK. If it appears inside a function body, WARN but allow
(test functions typically mock before using). This reduces false positives without
complex mock-detection logic.

### conftest.py Exemptions

The project's `conftest.py` files legitimately manipulate `sys.modules`, use
`importlib`, and stub heavy packages. The validator must handle this:

1. **Root `conftest.py`** (`tests/conftest.py`): Allowed to use `sys.modules[...] = ...`,
   `types.ModuleType(...)`, class definitions for stubs. This is the test bootstrap.

2. **Subdirectory conftest files** (`tests/guardrails/conftest.py`,
   `tests/import_check/conftest.py`): Allowed the same sys.modules manipulation.
   `tests/import_check/conftest.py` additionally calls `spec.loader.exec_module()`,
   which is functionally equivalent to `exec()` but is the standard importlib pattern
   for loading modules dynamically.

**Rule:** Files named `conftest.py` get a relaxed policy:
- `sys.modules` manipulation: ALLOW
- `importlib.util` usage: ALLOW
- `importlib.util.module_from_spec` + `spec.loader.exec_module()`: ALLOW
- `types.ModuleType(...)`: ALLOW
- All other rules (subprocess, os.system, network, etc.): still enforced

**Residual risk:** `exec_module()` in conftest files can execute arbitrary Python from
files resolved at runtime. This is accepted because conftest files are human-authored
project infrastructure, not agent-generated. The validator logs these as
`conftest_exemptions` in `validation.json` for audit visibility.

### Output Format

The validator writes JSON to stdout (for piping) and optionally to a file:

```json
{
  "status": "blocked",
  "timestamp": "2026-04-01T12:00:00Z",
  "files_scanned": 35,
  "files_passed": 33,
  "files_blocked": 2,
  "violations": [
    {
      "file": "tests/ingest/test_orchestrator.py",
      "line": 42,
      "category": "dangerous_call",
      "pattern": "subprocess.run",
      "severity": "block",
      "message": "Call to subprocess.run detected at line 42"
    }
  ],
  "conftest_exemptions": [
    {
      "file": "tests/conftest.py",
      "line": 9,
      "pattern": "sys.modules assignment",
      "reason": "conftest.py exemption for test bootstrap"
    }
  ]
}
```

Exit codes: 0 = all files pass, 1 = at least one BLOCK violation, 2 = validator error.

### Implementation Strategy

The validator is a single Python file (~500-600 lines) with no dependencies beyond
stdlib. (Original estimate of 300-400 was optimistic given alias tracking, conftest
exemptions, group overrides, and structured JSON output.) It uses:
- `ast.parse()` to parse each file
- `ast.walk()` or a custom `ast.NodeVisitor` subclass to traverse
- An alias table built from `ast.Import`/`ast.ImportFrom` nodes to resolve dotted names
- A policy dictionary mapping patterns to severity levels
- Command-line interface: `python scripts/check_pytest.py <path-or-glob> [--json] [--strict]`

---

## Test Runner Design (`run-tests.sh`)

### Interface

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

Exactly one of `--group`, `--path`, or `--marker` must be provided.

**`--no-validate` removed:** An earlier draft included a `--no-validate` flag for CI.
This is removed because agents could use it to bypass safety. CI can call `uv run pytest`
directly since CI is not the threat model — agents are.

**Group name validation:** `--group NAME` must match `^[a-z0-9-]+$`. No path separators,
no dots, no special characters. The runner verifies the corresponding `.conf` file exists
under `scripts/test-groups/` before sourcing it. Path traversal (e.g., `--group ../foo`)
is rejected at the regex level.

**Path validation:** `--path PATH` must resolve to a location under `tests/`. Absolute
paths or paths containing `..` that escape the project are rejected.

### Execution Flow

```
1. Parse arguments
2. Validate group name (alphanumeric + hyphens only, no path separators)
3. Resolve test scope:
   - --group: source scripts/test-groups/<name>.conf (verified to exist and be git-tracked)
   - --path: use directly (must be under tests/)
   - --marker: pass to pytest -m
4. Collect file list via filesystem glob (NOT pytest --collect-only, which imports code):
   find <test_paths> -name "test_*.py" -o -name "*_test.py"
   Also discover conftest.py files by walking up from test paths to tests/ root.
5. Run safety validation:
   python scripts/check_pytest.py <collected-files> --json [--allow <overrides>]
   If exit != 0: write validation.json, print summary, exit 1
6. Run pytest:
   timeout <run-timeout> uv run pytest \
     <scope-args> \
     --tb=short \
     --json-report --json-report-file=.tmp-test-results/report.json \
     --timeout=<per-test-timeout> \
     2>&1 | tee .tmp-test-results/run.log
6. Write combined summary to stdout
7. Exit with pytest's exit code
```

### Output Directory

```
.tmp-test-results/
  report.json          # pytest-json-report plugin output
  validation.json      # safety validator output (even on success, for audit)
  run.log              # raw stdout+stderr
```

This directory is created fresh each run (rm -rf + mkdir -p). It must be gitignored.

### Timeout Handling

Two layers:
1. **Per-test timeout:** via `pytest-timeout` plugin (`--timeout=N`). Each test that
   exceeds N seconds is terminated and marked as an error.
2. **Total run timeout:** via the shell `timeout` command wrapping the entire pytest
   invocation. If pytest as a whole exceeds the run timeout, it is killed with SIGTERM
   (then SIGKILL after a grace period).

If `pytest-timeout` is not installed, the runner falls back to shell-level timeout only
and prints a warning suggesting the plugin be installed.

### Dependencies

The runner needs two pytest plugins that are not currently in `pyproject.toml`:
- `pytest-json-report` -- for structured JSON output
- `pytest-timeout` -- for per-test timeout enforcement

These should be added to the `[project.optional-dependencies] dev` group.

---

## Group Configuration Design

### Format

Each group config is a simple key=value file (shell-sourceable):

```bash
# scripts/test-groups/ingest.conf
TEST_PATHS="tests/ingest/"
MARKERS=""
TIMEOUT=30
RUN_TIMEOUT=300
EXTRA_FLAGS=""
DESCRIPTION="Ingestion pipeline tests (document processing, embedding, orchestration)"
```

**Why not YAML?** Shell-sourceable files require zero parsing logic -- the runner just
does `source scripts/test-groups/${GROUP}.conf`. No Python dependency for configuration.

**Why not JSON?** Same reason. Shell can't natively parse JSON without jq.

### Group Definitions

| Group | TEST_PATHS | MARKERS | TIMEOUT | Notes |
|-------|------------|---------|---------|-------|
| ingest | `tests/ingest/` | | 30 | Largest group, heavy stubs |
| retrieval | `tests/retrieval/` | | 15 | Small, fast, pure logic |
| guardrails | `tests/guardrails/` | | 30 | NeMo-dependent |
| observability | `tests/observability/` | | 15 | Langfuse stubs |
| server | `tests/server/` | | 15 | Schema contracts |
| import-check | `tests/import_check/` | | 15 | sys.modules surgery |
| root | `tests/test_*.py` | | 30 | Mixed root-level tests |
| all | `tests/` | | 30 | Everything (union) |

### Naming Convention

Files: `scripts/test-groups/<group-name>.conf`
Invocation: `scripts/run-tests.sh --group <group-name>`

The group name is the filename stem. No `test-` or `run-` prefix on the conf files --
the `--group` flag already makes the intent clear.

### "Run All" Behavior

`--group all` sources `all.conf` which simply sets `TEST_PATHS="tests/"`. The safety
validator runs on the full tree. This is intentionally the same as running pytest with
no path argument.

---

## Agent / Skill Design

### Skill vs. Agent Decision

This should be a **skill** (`~/.claude/skills/test-runner/`), not an agent.

**Reasoning:**
- Skills are invoked by the operator (or by other skills/agents) as capability units.
- An agent would need its own prompt, tool permissions, and lifecycle management.
- The test runner is a *capability* ("run tests and interpret results"), not an
  *autonomous actor* ("go find and fix all test failures").
- The fix loop is orchestrated by whichever agent invoked the skill, not by the skill itself.

However, the fix loop logic (read failure, fix code, re-run) is better suited to an
agent-level orchestration. The recommended split:

| Component | Type | Responsibility |
|-----------|------|---------------|
| `test-runner` | Skill | Run tests, return structured results |
| Fix loop | Agent-level orchestration | Invoke test-runner, read failures, fix, retry |

The skill provides the capability. The calling agent (or autonomous orchestrator)
provides the judgment and retry logic.

### Skill Interface

The skill accepts:

```
Input:
  scope: string       # one of: group name, file path, directory path, marker expression
  scope_type: string  # "group" | "path" | "marker" | "keyword"
  strict: bool        # treat warnings as errors (default: false)
  timeout: int        # per-test timeout override (optional)

Output (to agent):
  status: "pass" | "fail" | "blocked" | "error"
  summary: string     # human-readable one-liner
  total: int
  passed: int
  failed: int
  errors: int
  skipped: int
  failures: list[{test_name, file, line, message, longrepr}]
  validation_issues: list[{file, line, category, message}]  # if blocked
  duration_seconds: float
```

### Fix Loop Design

The fix loop is NOT part of the skill. It is orchestrated by the calling agent. The
recommended pattern:

```
Agent receives: "run ingest tests and fix failures"

1. Invoke test-runner skill with scope="ingest", scope_type="group"
2. If status == "pass": report success, done
3. If status == "blocked": report validation failure, done (do not try to fix safety violations)
4. If status == "fail":
   a. For each failure in failures:
      - Read the test file at file:line
      - Read the source file being tested (infer from import)
      - Determine: is this a test bug or a source bug?
      - Fix the appropriate file
   b. Re-invoke test-runner skill with same scope
   c. If still failing: check if same tests are failing
      - If different tests: progress is being made, continue
      - If same tests with same error: stop (infinite loop detected)
   d. Max iterations: 3
5. Report final status
```

### Infinite Loop Prevention

Three guards:
1. **Max iterations:** Hard cap of 3 retry cycles (configurable).
2. **Same-failure detection:** If the exact same test names fail with the same error
   messages after a fix attempt, the loop terminates early with a "unable to fix" report.
3. **Monotonic progress:** If the number of failures is not decreasing across iterations,
   stop after 2 attempts at the same failure count.

### Fixer Context and Scope

When the fix loop dispatches a fix, it provides:

```
Context for fixer:
  - Test file path and relevant test function
  - Full failure output (longrepr from pytest-json-report)
  - Source file being tested (inferred from imports in the test file)
  - The last N lines of the source file around the relevant code
  - Whether this is a re-attempt (and what was tried last time)
```

The fixer does NOT get the full test suite output -- only the specific failure it is
asked to fix. This keeps context focused and avoids the fixer trying to fix everything
at once.

**Fixer file scope (resolved):** The fixer agent MAY modify both test files and source
files. Rationale: the agent already has Edit permission for source files in normal
operation; the fix loop just automates the manual test-fix-rerun cycle. Constraint:
the fixer may only modify files that are already tracked by git (`git ls-files`). It
must not create new files or delete files — only edit existing ones. This prevents
scope creep where a "test fix" turns into a refactoring session.

---

## Observability

### Log Structure

All logs go to `.tmp-test-results/` which is ephemeral per run:

```
.tmp-test-results/
  validation.json      # safety validator decisions (always written)
  report.json          # pytest-json-report output (only if validation passed)
  run.log              # raw stdout/stderr from pytest
  meta.json            # run metadata: timestamp, scope, duration, exit code, agent info
```

### meta.json Format

```json
{
  "timestamp": "2026-04-01T12:00:00Z",
  "scope": "tests/ingest/",
  "scope_type": "group",
  "group": "ingest",
  "duration_seconds": 45.2,
  "exit_code": 0,
  "validation_status": "passed",
  "pytest_status": "passed",
  "agent": null,
  "iteration": 1,
  "max_iterations": 3
}
```

### What the Agent Reads

1. **Primary:** `report.json` -- the pytest-json-report output with per-test pass/fail,
   duration, and failure details.
2. **On validation failure:** `validation.json` -- which files were blocked and why.
3. **On pytest error:** `run.log` -- raw output for debugging unexpected crashes.
4. **For audit:** `meta.json` -- run metadata for logging/debugging the fix loop.

### What the Fixer Needs

The fixer agent does NOT read the raw log files. The calling agent extracts the relevant
failure from `report.json` and passes it as structured context. This keeps the fixer
focused on one failure at a time.

---

## Key Design Decisions

| # | Decision | Rationale | Alternative Considered |
|---|----------|-----------|----------------------|
| 1 | Shell orchestrator + Python validator | Process isolation between validation and execution; validator runs and exits before pytest starts | Pure Python runner (loses process boundary) |
| 2 | AST-only validation, never import/execute | Cannot be exploited by the code being validated; zero side effects | importlib-based analysis (executes target code) |
| 3 | conftest.py gets relaxed policy | Project's test bootstrap legitimately manipulates sys.modules; blocking this breaks all tests | No exceptions (breaks existing tests) |
| 4 | Skill for running, agent-level fix loop | Separation of capability (run tests) from judgment (what to fix); skill is reusable by multiple agents | Monolithic agent that does everything |
| 5 | Shell-sourceable group configs | Zero parsing dependencies; runner is a shell script, so configs should be shell-native | YAML (needs Python or yq to parse in shell) |
| 6 | pytest-json-report for output | De facto standard for machine-readable pytest output; well-maintained | Custom pytest plugin (reinventing the wheel) |
| 7 | .tmp-test-results/ ephemeral directory | Fresh per run, gitignored, no state accumulation across runs | Named directories per run (clutters filesystem) |
| 8 | Max 3 fix iterations with same-failure detection | Prevents infinite loops while allowing genuine multi-step fixes | Unlimited retries (risks runaway agent) |
| 9 | Warn-not-block for ambiguous patterns | File writes where tmp_path detection is uncertain get WARN severity; --strict flag upgrades to BLOCK | Block everything ambiguous (too many false positives) |
| 10 | Single permission entry in settings.json | `Bash(scripts/run-tests.sh *)` replaces `Bash(pytest *)` -- agents can only run tests through the wrapper | Multiple permissions for each component |

---

## Edge Cases

### 1. Dynamic Code Generation in Tests

A test could use `exec()` inside a string that is constructed at runtime (e.g.,
`exec("sub" + "process.run(...)")`). AST analysis cannot catch this.

**Mitigation:** The validator blocks `exec()` and `eval()` calls entirely, regardless
of their arguments. String concatenation that eventually reaches `exec` is blocked
because the `exec` call itself is blocked.

### 2. Fixture-Injected Danger

A conftest.py fixture could return a function that calls `subprocess.run`. The test
file itself looks clean, but the fixture introduces the danger.

**Mitigation:** The validator scans ALL conftest.py files in the pytest collection path,
not just the test files. Conftest files get the relaxed policy (sys.modules OK) but
are still scanned for subprocess/os.system/network calls.

### 3. Third-Party Plugin Side Effects

A pytest plugin (installed via pip) could execute arbitrary code. The validator only
scans project files, not installed packages.

**Mitigation:** Out of scope for AST validation. The project's `pyproject.toml` pins
plugin versions. New plugin additions go through PR review. This is an accepted risk.

### 4. Tests That Legitimately Need Network (Integration Tests)

Some future integration tests may need real HTTP calls (e.g., testing against a local
Docker service).

**Mitigation:** The `--no-validate` flag for CI environments where validation is handled
differently. For agent runs, integration tests should be in a separate group with
explicit marker (`@pytest.mark.integration`) and the group config can set a different
validation policy. This is a spec-phase decision.

### 5. Monkeypatch and mock.patch Usage

Tests frequently use `monkeypatch.setattr("module.function", mock_fn)`. The string
`"module.function"` is not an import and should not be flagged.

**Mitigation:** The validator only flags `ast.Import` and `ast.ImportFrom` nodes for
import-level blocking. String arguments to `mock.patch()` and `monkeypatch.setattr()`
are not imports and are inherently safe (they replace behavior, they do not add it).

### 6. conftest.py That Actually Does Something Dangerous

A conftest.py could contain `subprocess.run(...)` and claim it is "test setup."

**Mitigation:** conftest.py exemptions are limited to sys.modules/importlib/types
manipulation only. All other dangerous patterns (subprocess, os.system, network, etc.)
are still enforced in conftest.py files.

### 7. Validator Itself Has a Bug (False Negative)

The AST validator misses a pattern and allows a dangerous test to run.

**Mitigation:** Defense in depth. The shell `timeout` command kills runaway processes.
The agent's shell permission is limited to the wrapper script. The wrapper script runs
pytest in a subprocess, not in the agent's own process. A missed pattern results in
pytest running unsafe code, but that code is still constrained by OS-level permissions
(the user account's filesystem access, no sudo). This is the residual risk.

---

## Open Questions for Spec Phase

1. **pytest-json-report availability:** Is this plugin already usable in the project's
   venv, or does it need to be added to `pyproject.toml`? What version? Are there
   compatibility issues with pytest 9.0.2?

2. **Validation policy versioning:** Should the list of blocked patterns be in a
   separate config file (easy to update) or hardcoded in `check_pytest.py` (simpler,
   fewer moving parts)?

3. **Integration test group:** Should there be a separate group for tests that need
   real infrastructure (Docker services, network access)? What validation policy
   would they use?

4. **Settings.json migration:** When replacing `Bash(pytest *)` with
   `Bash(scripts/run-tests.sh *)`, should the old permission be removed in the same
   change set, or kept temporarily with a deprecation notice?

5. **CI integration:** Should CI also use `run-tests.sh`, or continue using direct
   `uv run pytest` invocations? Using the wrapper in CI would validate the same code
   path, but adds overhead.

6. **Async test support:** The project does not use pytest-asyncio today, but retrieval
   tests may need it in the future. Should the runner support async-specific flags
   or timeout handling?

7. **Coverage integration:** Should the runner optionally collect coverage data
   (`--cov`)? This is orthogonal to safety but is a common test runner feature.

8. **Skill registry:** The skill needs to be registered in
   `~/.claude/skills/SKILLS_REGISTRY.yaml`. What is the trigger phrase? Should it be
   invocable as `/test` or `/run-tests`?

9. **Fixer scope:** When the fix loop identifies a source bug (not a test bug), should
   the fixer agent be allowed to modify source files, or only test files? Modifying
   source files from a test-fixing context is a larger permission scope.

10. **Parallel group execution:** Should the runner support running multiple groups
    in parallel (e.g., `--group ingest,retrieval`)? This complicates output merging
    but could speed up full-suite runs.

---

## Scope Boundary

### In Scope

- `scripts/check_pytest.py` -- AST safety validator
- `scripts/run-tests.sh` -- orchestrator shell script
- `scripts/test-groups/*.conf` -- group configuration files
- `.tmp-test-results/` directory structure and gitignore entry
- `settings.local.json` update to replace raw pytest permission
- Test-runner skill definition (SKILL.md)
- pyproject.toml update for pytest-json-report and pytest-timeout
- Unit tests for the AST validator

### Out of Scope

- Fixer agent implementation (uses existing agent capabilities)
- CI pipeline changes (separate concern)
- Integration test infrastructure
- Coverage collection
- Parallel test execution
- pytest plugin development
- Docker-based test isolation (overkill for this project's threat model)
