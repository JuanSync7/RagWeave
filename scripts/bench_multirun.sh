#!/usr/bin/env bash
# bench_multirun.sh — Run the retrieval-query benchmark N times and aggregate.
#
# Purpose: single-sample p95 on a shared GPU has ~80% variance between runs
#          (see research/retrieval/iterations.tsv iter 002 discard + iter 003 reruns).
#          The auto-research keep rule needs a noise-resistant score, so every
#          iteration from 004 onward reports `max(p95)` across N samples.
#
# Protocol:
#   - Each sample runs benchmark_retrieval_query.py once (60 queries = 20 × 3 reps).
#   - N samples are independent fresh processes (pays model-load cost each run,
#     but that's the point — we want to see worst-case through jitter).
#   - Reports are written to research/<label>_run<i>.json (i=1..N).
#   - Aggregate prints per-percentile min/median/max across samples and the
#     SETTLED score (max of the per-sample p95) used for keep-rule evaluation.
#
# Usage:
#   scripts/bench_multirun.sh [N] [label]
#     N       number of samples (default 3)
#     label   prefix for report filenames (default: iter_<git-short-sha>)
#
# Example:
#   scripts/bench_multirun.sh 3 iter_004
#
# This script is a THIN WRAPPER around the immutable benchmark harness.
# It does not modify harness logic — only orchestrates repeated invocations
# and computes a cross-run aggregate. PROGRAM.md permits this wrapper.

set -euo pipefail

N="${1:-3}"
LABEL="${2:-iter_$(git rev-parse --short HEAD 2>/dev/null || echo unknown)}"
# Per-sample reports live alongside the loop's other artifacts.
# See research/README.md for the research/ layout convention.
OUTDIR="research/retrieval"
PY="/home/juansync7/RagWeave/.venv/bin/python"
HARNESS="scripts/benchmark_retrieval_query.py"

if [[ ! -x "$PY" ]]; then
  echo "ERROR: venv python not found at $PY" >&2
  exit 1
fi
if [[ ! -f "$HARNESS" ]]; then
  echo "ERROR: harness not found at $HARNESS" >&2
  exit 1
fi

mkdir -p "$OUTDIR"

echo "bench_multirun: N=$N label=$LABEL commit=$(git rev-parse --short HEAD 2>/dev/null || echo ?)"
echo "bench_multirun: writing ${OUTDIR}/${LABEL}_run<i>.json"
echo

reports=()
for i in $(seq 1 "$N"); do
  report="${OUTDIR}/${LABEL}_run${i}.json"
  echo "--- sample $i/$N -> $report ---"
  "$PY" "$HARNESS" --report "$report" 2>&1 | tail -1
  reports+=("$report")
done

echo
echo "=== Aggregate across $N samples (commit $(git rev-parse --short HEAD 2>/dev/null || echo ?)) ==="
"$PY" - "${reports[@]}" <<'PY_EOF'
import json
import sys
import statistics

reports = sys.argv[1:]
samples = []
for r in reports:
    with open(r) as f:
        d = json.load(f)
    a = d["aggregate"]
    samples.append({
        "report": r,
        "p50": a["retrieval_p50_ms"],
        "p95": a["retrieval_p95_ms"],
        "p99": a["retrieval_p99_ms"],
        "mean": a["retrieval_mean_ms"],
        "lint_passed": d["lint_check"]["passed"],
        "lint_failures": len(d["lint_check"]["failures"]),
        "drift": d["regression_guard"]["drift_count"],
        "guarded": d["regression_guard"]["guarded_count"],
    })

print(f"{'run':<42} {'p50':>6} {'p95':>6} {'p99':>6} {'mean':>6} lint drift")
for s in samples:
    print(f"{s['report']:<42} {s['p50']:>6.0f} {s['p95']:>6.0f} {s['p99']:>6.0f} "
          f"{s['mean']:>6.0f} {str(s['lint_failures']):>4} {s['drift']}/{s['guarded']}")

def stats(key):
    xs = [s[key] for s in samples]
    return min(xs), statistics.median(xs), max(xs)

print()
print(f"{'metric':<6} {'min':>7} {'median':>7} {'max':>7}")
for k in ("p50", "p95", "p99", "mean"):
    lo, md, hi = stats(k)
    print(f"{k:<6} {lo:>7.0f} {md:>7.0f} {hi:>7.0f}")

settled_p95 = max(s["p95"] for s in samples)
any_lint_fail = any(not s["lint_passed"] for s in samples)
total_drift = sum(s["drift"] for s in samples)

print()
print(f"SETTLED p95 (max across samples) = {settled_p95:.0f} ms")
print(f"lint_passed_all = {not any_lint_fail}")
print(f"drift_total = {total_drift}")
PY_EOF
