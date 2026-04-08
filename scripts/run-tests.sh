#!/usr/bin/env bash
# Test runner orchestrator -- the ONLY permitted test execution path.
# Validates test files for safety via check_pytest.py before running pytest.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

OUTPUT_DIR=".tmp-test-results"

# ── Argument parsing ────────────────────────────────────────────────

parse_args() {
    GROUP=""
    TEST_PATH=""
    MARKER=""
    KEYWORD=""
    TIMEOUT_OVERRIDE=""
    RUN_TIMEOUT_OVERRIDE=""
    STRICT="false"
    DRY_RUN="false"
    VERBOSE="false"

    while [ $# -gt 0 ]; do
        case "$1" in
            --group)
                [ -n "${2:-}" ] || { echo "ERROR: --group requires a value" >&2; exit 2; }
                GROUP="$2"; shift 2 ;;
            --path)
                [ -n "${2:-}" ] || { echo "ERROR: --path requires a value" >&2; exit 2; }
                TEST_PATH="$2"; shift 2 ;;
            --marker)
                [ -n "${2:-}" ] || { echo "ERROR: --marker requires a value" >&2; exit 2; }
                MARKER="$2"; shift 2 ;;
            --keyword)
                [ -n "${2:-}" ] || { echo "ERROR: --keyword requires a value" >&2; exit 2; }
                KEYWORD="$2"; shift 2 ;;
            --timeout)
                [ -n "${2:-}" ] || { echo "ERROR: --timeout requires a value" >&2; exit 2; }
                TIMEOUT_OVERRIDE="$2"; shift 2 ;;
            --run-timeout)
                [ -n "${2:-}" ] || { echo "ERROR: --run-timeout requires a value" >&2; exit 2; }
                RUN_TIMEOUT_OVERRIDE="$2"; shift 2 ;;
            --strict)
                STRICT="true"; shift ;;
            --dry-run)
                DRY_RUN="true"; shift ;;
            --verbose)
                VERBOSE="true"; shift ;;
            *)
                echo "ERROR: Unknown argument: $1" >&2; exit 2 ;;
        esac
    done

    # Exactly one of --group or --path must be provided
    if [ -z "$GROUP" ] && [ -z "$TEST_PATH" ]; then
        echo "ERROR: Exactly one of --group or --path is required" >&2
        exit 2
    fi
    if [ -n "$GROUP" ] && [ -n "$TEST_PATH" ]; then
        echo "ERROR: --group and --path are mutually exclusive" >&2
        exit 2
    fi

    # Validate integer-typed overrides
    if [ -n "$TIMEOUT_OVERRIDE" ]; then
        if ! [[ "$TIMEOUT_OVERRIDE" =~ ^[0-9]+$ ]]; then
            echo "ERROR: --timeout must be a positive integer, got: $TIMEOUT_OVERRIDE" >&2
            exit 2
        fi
    fi
    if [ -n "$RUN_TIMEOUT_OVERRIDE" ]; then
        if ! [[ "$RUN_TIMEOUT_OVERRIDE" =~ ^[0-9]+$ ]]; then
            echo "ERROR: --run-timeout must be a positive integer, got: $RUN_TIMEOUT_OVERRIDE" >&2
            exit 2
        fi
    fi
}

# ── Group name validation ───────────────────────────────────────────

validate_group_name() {
    if ! [[ "$GROUP" =~ ^[a-z0-9-]+$ ]]; then
        echo "ERROR: Invalid group name '$GROUP'. Must match ^[a-z0-9-]+\$" >&2
        exit 2
    fi

    local CONF_FILE="scripts/test-groups/${GROUP}.conf"
    if [ ! -f "$CONF_FILE" ]; then
        echo "ERROR: Group config not found: $CONF_FILE" >&2
        echo "Available groups:" >&2
        ls scripts/test-groups/*.conf 2>/dev/null | sed 's|.*/||;s|\.conf$||' >&2
        exit 2
    fi

    # Verify .conf file is git-tracked
    if ! git ls-files --error-unmatch "$CONF_FILE" >/dev/null 2>&1; then
        echo "ERROR: Group config '$CONF_FILE' is not tracked by git. Refusing to source." >&2
        exit 2
    fi
}

# ── Path validation ─────────────────────────────────────────────────

validate_test_path() {
    local RESOLVED
    RESOLVED="$(realpath "$TEST_PATH" 2>/dev/null || true)"

    if [ -z "$RESOLVED" ]; then
        echo "ERROR: Cannot resolve path: $TEST_PATH" >&2
        exit 2
    fi

    local TESTS_DIR
    TESTS_DIR="$(realpath "$PROJECT_ROOT/tests")"

    if [[ "$RESOLVED" != "$TESTS_DIR"* ]]; then
        echo "ERROR: Path must resolve under tests/. Got: $RESOLVED" >&2
        exit 2
    fi

    if [ ! -e "$RESOLVED" ]; then
        echo "ERROR: Path does not exist: $RESOLVED" >&2
        exit 2
    fi

    TEST_PATH="$RESOLVED"
}

# ── File collection ─────────────────────────────────────────────────

collect_files() {
    COLLECTED_FILES_TMPFILE="$(mktemp)"
    trap "rm -f '$COLLECTED_FILES_TMPFILE'" EXIT

    local test_files=()
    local conftest_files=()

    for path in $RESOLVED_TEST_PATHS; do
        # Handle glob patterns (e.g., tests/test_*.py)
        if [[ "$path" == *"*"* ]]; then
            # Expand glob from project root
            local expanded
            expanded=$(ls -1 $path 2>/dev/null || true)
            if [ -n "$expanded" ]; then
                while IFS= read -r f; do
                    test_files+=("$f")
                done <<< "$expanded"
            fi
        elif [ -d "$path" ]; then
            # Directory: find test files recursively
            while IFS= read -r f; do
                test_files+=("$f")
            done < <(find "$path" -type f \( -name "test_*.py" -o -name "*_test.py" \) 2>/dev/null)
            # Find conftest files in directory
            while IFS= read -r f; do
                conftest_files+=("$f")
            done < <(find "$path" -type f -name "conftest.py" 2>/dev/null)
        elif [ -f "$path" ]; then
            test_files+=("$path")
        fi
    done

    # Walk upward from each test file directory to tests/ root, collecting conftest.py files
    local tests_root="$PROJECT_ROOT/tests"
    declare -A seen_conftest=()
    for tf in "${test_files[@]}"; do
        local dir
        dir="$(dirname "$tf")"
        # Make absolute for comparison
        if [[ "$dir" != /* ]]; then
            dir="$PROJECT_ROOT/$dir"
        fi
        while [ "$dir" != "$PROJECT_ROOT" ] && [ "$dir" != "/" ]; do
            if [ -f "$dir/conftest.py" ]; then
                local rel_conftest
                # Store as relative if inside project root
                if [[ "$dir/conftest.py" == "$PROJECT_ROOT/"* ]]; then
                    rel_conftest="${dir#$PROJECT_ROOT/}/conftest.py"
                else
                    rel_conftest="$dir/conftest.py"
                fi
                if [ -z "${seen_conftest[$rel_conftest]:-}" ]; then
                    conftest_files+=("$rel_conftest")
                    seen_conftest["$rel_conftest"]=1
                fi
            fi
            dir="$(dirname "$dir")"
        done
    done

    # Deduplicate and write all files
    {
        for f in "${conftest_files[@]}"; do echo "$f"; done
        for f in "${test_files[@]}"; do echo "$f"; done
    } | sort -u > "$COLLECTED_FILES_TMPFILE"

    local count
    count=$(wc -l < "$COLLECTED_FILES_TMPFILE" | tr -d ' ')
    if [ "$count" -eq 0 ]; then
        echo "WARNING: No test files found for scope: $RESOLVED_TEST_PATHS" >&2
    fi
    echo "Collected $count files for validation" >&2
}

# ── Validation overrides parsing ────────────────────────────────────

parse_validation_overrides() {
    ALLOW_PATTERNS=""
    if [ -n "${VALIDATION_OVERRIDES:-}" ]; then
        IFS=',' read -ra OVERRIDE_PAIRS <<< "$VALIDATION_OVERRIDES"
        for pair in "${OVERRIDE_PAIRS[@]}"; do
            local pattern="${pair%%:*}"
            local action="${pair##*:}"
            if [ "$action" != "allow" ]; then
                echo "ERROR: Unknown override action '$action' in VALIDATION_OVERRIDES. Only 'allow' is supported." >&2
                exit 2
            fi
            if [ -n "$ALLOW_PATTERNS" ]; then
                ALLOW_PATTERNS="$ALLOW_PATTERNS,$pattern"
            else
                ALLOW_PATTERNS="$pattern"
            fi
        done
    fi
}

# ── Safety validation ───────────────────────────────────────────────

run_validation() {
    local cmd="python scripts/check_pytest.py"
    cmd+=" $(cat "$COLLECTED_FILES_TMPFILE" | tr '\n' ' ')"
    cmd+=" --json"

    if [ -n "$ALLOW_PATTERNS" ]; then
        cmd+=" --allow $ALLOW_PATTERNS"
    fi
    if [ "$STRICT" = "true" ]; then
        cmd+=" --strict"
    fi

    set +e
    eval "$cmd" > "$OUTPUT_DIR/validation.json" 2>/dev/null
    VALIDATION_EXIT=$?
    set -e

    if [ $VALIDATION_EXIT -eq 0 ]; then
        VALIDATION_STATUS="passed"
        echo "Safety validation: PASSED" >&2
    elif [ $VALIDATION_EXIT -eq 1 ]; then
        VALIDATION_STATUS="blocked"
        echo "Safety validation: BLOCKED" >&2
        # Print summary of violations
        if command -v python3 >/dev/null 2>&1; then
            python3 -c "
import json, sys
try:
    data = json.load(open('$OUTPUT_DIR/validation.json'))
    for v in data.get('violations', []):
        print(f\"  {v.get('severity','?').upper()}: {v.get('file','')}:{v.get('line','')} - {v.get('pattern','')} ({v.get('message','')})\", file=sys.stderr)
except Exception:
    pass
" 2>&2 || true
        fi
    else
        VALIDATION_STATUS="error"
        echo "Safety validation: ERROR (exit code $VALIDATION_EXIT)" >&2
    fi
}

# ── Pytest invocation ───────────────────────────────────────────────

run_pytest() {
    # Check pytest-json-report is installed (REQUIRED)
    if ! uv run python -c "import pytest_json_report" 2>/dev/null; then
        echo "ERROR: pytest-json-report not installed. Install with: uv add --dev pytest-json-report" >&2
        PYTEST_EXIT=2
        return
    fi

    # Build pytest command
    local PYTEST_CMD="uv run pytest"
    PYTEST_CMD+=" $RESOLVED_TEST_PATHS"

    if [ -n "${MARKER:-}" ]; then
        PYTEST_CMD+=" -m \"$MARKER\""
    fi
    if [ -n "${KEYWORD:-}" ]; then
        PYTEST_CMD+=" -k \"$KEYWORD\""
    fi

    PYTEST_CMD+=" --json-report"
    PYTEST_CMD+=" --json-report-file=$OUTPUT_DIR/report.json"

    # Per-test timeout (optional, degrade gracefully)
    if uv run python -c "import pytest_timeout" 2>/dev/null; then
        PYTEST_CMD+=" --timeout=$PER_TEST_TIMEOUT"
    else
        echo "WARNING: pytest-timeout not installed, per-test timeout disabled" >&2
    fi

    PYTEST_CMD+=" --tb=short"

    if [ -n "${EXTRA_FLAGS:-}" ]; then
        PYTEST_CMD+=" $EXTRA_FLAGS"
    fi

    echo "Running: timeout $TOTAL_RUN_TIMEOUT $PYTEST_CMD" >&2

    # Execute with total timeout; set +e to capture exit code on test failures
    set +e
    if [ "$VERBOSE" = "true" ]; then
        eval "timeout --signal=TERM --kill-after=10 $TOTAL_RUN_TIMEOUT $PYTEST_CMD" 2>&1 | tee "$OUTPUT_DIR/run.log"
        PYTEST_EXIT=${PIPESTATUS[0]}
    else
        eval "timeout --signal=TERM --kill-after=10 $TOTAL_RUN_TIMEOUT $PYTEST_CMD" > "$OUTPUT_DIR/run.log" 2>&1
        PYTEST_EXIT=$?
    fi
    set -e
}

# ── Output directory management ─────────────────────────────────────

setup_output_dir() {
    rm -rf "$OUTPUT_DIR"
    mkdir -p "$OUTPUT_DIR"
}

# ── meta.json writer ────────────────────────────────────────────────

write_meta_json() {
    local GROUP_JSON
    if [ -n "${GROUP:-}" ]; then
        GROUP_JSON="\"$GROUP\""
    else
        GROUP_JSON="null"
    fi

    local PYTEST_CMD_JSON
    if [ -n "${PYTEST_CMD:-}" ]; then
        PYTEST_CMD_JSON="\"$PYTEST_CMD\""
    else
        PYTEST_CMD_JSON="null"
    fi

    python3 -c "
import json
meta = {
    'timestamp': '$TIMESTAMP',
    'scope': '$RESOLVED_TEST_PATHS',
    'scope_type': '$SCOPE_TYPE',
    'group': $GROUP_JSON,
    'duration_seconds': $DURATION,
    'exit_code': ${FINAL_EXIT:-${VALIDATION_EXIT:-0}},
    'validation_status': '${VALIDATION_STATUS:-unknown}',
    'pytest_status': '${PYTEST_STATUS:-not_run}',
    'command': $PYTEST_CMD_JSON,
    'agent': None,
    'iteration': 1,
    'max_iterations': 3
}
with open('$OUTPUT_DIR/meta.json', 'w') as f:
    json.dump(meta, f, indent=2)
"
}

# ── Main ────────────────────────────────────────────────────────────

main() {
    local START_SECONDS=$SECONDS
    local TIMESTAMP
    TIMESTAMP="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

    parse_args "$@"

    setup_output_dir

    # Resolve scope
    if [ -n "$GROUP" ]; then
        validate_group_name
        # shellcheck disable=SC1090
        source "scripts/test-groups/${GROUP}.conf"
        SCOPE_TYPE="group"
        RESOLVED_TEST_PATHS="$TEST_PATHS"
    else
        validate_test_path
        SCOPE_TYPE="path"
        RESOLVED_TEST_PATHS="$TEST_PATH"
    fi

    # Validate integer-typed conf keys
    if [ -n "$GROUP" ]; then
        if ! [[ "${TIMEOUT:-}" =~ ^[0-9]+$ ]]; then
            echo "ERROR: TIMEOUT in ${GROUP}.conf must be a positive integer, got: '${TIMEOUT:-}'" >&2
            exit 2
        fi
        if ! [[ "${RUN_TIMEOUT:-}" =~ ^[0-9]+$ ]]; then
            echo "ERROR: RUN_TIMEOUT in ${GROUP}.conf must be a positive integer, got: '${RUN_TIMEOUT:-}'" >&2
            exit 2
        fi
    fi

    # Apply CLI overrides to config values
    PER_TEST_TIMEOUT="${TIMEOUT_OVERRIDE:-${TIMEOUT:-30}}"
    TOTAL_RUN_TIMEOUT="${RUN_TIMEOUT_OVERRIDE:-${RUN_TIMEOUT:-300}}"

    # Parse validation overrides from group config
    parse_validation_overrides

    # Collect files
    collect_files

    # Run safety validation
    run_validation
    if [ "$VALIDATION_STATUS" != "passed" ]; then
        PYTEST_STATUS="not_run"
        DURATION=$(( SECONDS - START_SECONDS ))
        FINAL_EXIT=1
        [ "$VALIDATION_STATUS" = "error" ] && FINAL_EXIT=2
        write_meta_json
        exit $FINAL_EXIT
    fi

    # Dry-run: stop after validation
    if [ "$DRY_RUN" = "true" ]; then
        PYTEST_STATUS="not_run"
        DURATION=$(( SECONDS - START_SECONDS ))
        FINAL_EXIT=0
        write_meta_json
        echo "Dry run complete. Validation passed." >&2
        exit 0
    fi

    # Run pytest
    run_pytest
    DURATION=$(( SECONDS - START_SECONDS ))

    # Determine pytest status
    if [ $PYTEST_EXIT -eq 0 ]; then
        PYTEST_STATUS="passed"
    elif [ $PYTEST_EXIT -eq 124 ]; then
        PYTEST_STATUS="error"
    elif [ $PYTEST_EXIT -eq 1 ]; then
        PYTEST_STATUS="failed"
    else
        PYTEST_STATUS="error"
    fi

    FINAL_EXIT=$PYTEST_EXIT
    write_meta_json
    exit $PYTEST_EXIT
}

main "$@"
