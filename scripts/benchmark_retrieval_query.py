#!/usr/bin/env python3
# @summary
# IMMUTABLE auto-research benchmark harness for the retrieval query pipeline.
# Runs RAGChain.run() over a fixed query set, captures per-stage timings,
# enforces an output-contract regression guard, and runs a logging/error-handling
# /timing lint check on the mutable pipeline files. DO NOT MODIFY during the
# auto-research loop — it is the score authority.
# Exports: main, run_benchmark, capture_baseline, run_lint_check, run_pre_flight
# Deps: src.retrieval.pipeline.rag_chain, orjson, statistics, ast, hashlib
# @end-summary
"""Auto-research benchmark harness for the retrieval query pipeline.

Usage
-----
    # First run — captures baseline as research/baseline_outputs.json + research/baseline_report.json
    python scripts/benchmark_retrieval_query.py --baseline

    # Subsequent iterations — write a per-iteration report and check guards
    python scripts/benchmark_retrieval_query.py \
        --report research/iteration_002_report.json

What it measures
----------------
- ``retrieval_p50_ms`` / ``retrieval_p95_ms`` / ``retrieval_p99_ms``: percentiles of
  the *retrieval-only* latency, defined as the sum of stages 1-5 from
  ``RAGResponse.stage_timings`` (query_processing, kg_expansion, embedding,
  hybrid_search, reranking — generation and visual_retrieval are EXCLUDED).
- ``per_stage_p50_ms`` / ``per_stage_p95_ms``: percentile per individual stage.

What it guards
--------------
1. **Output contract**: per query, ``(action, top_k_doc_id_set)`` must match the
   baseline snapshot for at least ``1 - DRIFT_TOLERANCE`` of queries. Doc IDs are
   stable content hashes of the ranked result text (not metadata-dependent).
2. **Lint**: every function in the mutable file set that touches an external
   service (LLM, vector_db, embeddings, reranker model, file IO) must contain
   a ``logger.<level>`` call AND a timing primitive (``perf_counter``,
   ``TimingPool.record``, ``tracer.span``, etc.). Iterations that touch a
   guarded function and leave it lint-failing are reported as
   ``lint_check_passed: false``.
3. **Pre-flight**: embedded Weaviate seed data directory, local BGE model
   checkpoints (embedding + reranker), and the Ollama/LLM HTTP endpoint
   must all be present before the loop starts. Pre-flight failure produces
   a ``crash`` record and exits non-zero.

Determinism
-----------
At startup the harness forces the LLM-free "heuristic" path in the query
processor by monkey-patching ``query_processor._check_llm_available`` to
return ``False``. Rationale:

- PROGRAM.md scopes the exploration strategies to stages 2-5 (embedding,
  kg_expansion, hybrid_search, reranking). Stage-1 LLM round-trips are
  explicitly out of scope (strategy 4 deferred).
- The heuristic confidence function is purely a function of word count and
  therefore deterministic — the output contract becomes crisp.
- Ollama LLM calls dominate stage 1 latency (~15s each observed); running
  60 samples × 3 reps with the LLM path would take ~15 minutes per iteration,
  making a 30-iteration loop impractically slow.

``config.settings.GENERATION_ENABLED`` is also set to ``False`` — stage 6
is out of scope for the retrieval-only metric and disabling it removes
unnecessary LLM cost on every benchmark run. These are benchmark-only
overrides; the production settings file is never written.

This file is IMMUTABLE during the auto-research loop. Do not edit it from
within an iteration. If the contract is wrong, stop the loop, edit it
deliberately, and restart with a new baseline.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import logging
import os
import socket
import statistics
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import URLError
from urllib.request import urlopen

import orjson

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
RESEARCH_DIR = REPO_ROOT / "research"
BENCHMARK_QUERIES_PATH = RESEARCH_DIR / "benchmark_queries.json"
BASELINE_OUTPUTS_PATH = RESEARCH_DIR / "baseline_outputs.json"
BASELINE_REPORT_PATH = RESEARCH_DIR / "baseline_report.json"

# Stages whose latency rolls into "retrieval-only" total (PROGRAM.md objective).
RETRIEVAL_STAGES = {
    "query_processing",
    "kg_expansion",
    "embedding",
    "hybrid_search",
    "reranking",
}

# Number of repetitions per query — averages out cold-cache jitter.
REPS_PER_QUERY = 3

# Drift tolerance: at most this fraction of queries may diverge from baseline.
DRIFT_TOLERANCE = 0.05

# Mutable files for lint check (must match PROGRAM.md mutable list).
MUTABLE_FILES = [
    "src/retrieval/pipeline/rag_chain.py",
    "src/retrieval/query/nodes/query_processor.py",
    "src/retrieval/query/nodes/reranker.py",
    "src/retrieval/common/utils.py",
    "src/retrieval/common/exceptions.py",
    "src/retrieval/common/__init__.py",
    "src/retrieval/common/schemas.py",
]

# Function-name keywords that mark a function as "performs IO" and so must
# have logging + timing per the contract. We additionally inspect the function
# body for explicit IO calls (see _function_touches_io).
IO_KEYWORD_HINTS = (
    "process",
    "search",
    "embed",
    "rerank",
    "generate",
    "expand",
    "warm",
    "ask",
    "retrieve",
    "call",
    "load",
    "fetch",
    "infer",
    "encode",
)

# Names that — when called inside a function body — flag the function as
# IO-touching for the lint contract.
IO_CALL_MARKERS = {
    "get_llm_provider",
    "search",
    "search_visual",
    "ensure_collection",
    "create_persistent_client",
    "process_query",
    "embed_query",
    "embed_documents",
    "embed_text_query",
    "rerank",
    "generate",
    "open",  # file IO
    "load",
}

# Logger call markers (any logger.<level>(...))
LOGGER_LEVELS = {"info", "warning", "error", "debug", "exception", "critical", "log"}

# Timing primitive markers (any of these used inside the function body)
TIMING_MARKERS = {
    "perf_counter",
    "record",  # TimingPool.record
    "span",  # tracer.span
    "measure_ms",
    "TimingPool",
}


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logger = logging.getLogger("autoresearch.bench")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)


# ---------------------------------------------------------------------------
# Determinism overrides — applied at import time before RAGChain is built
# ---------------------------------------------------------------------------


def _patch_settings_for_determinism() -> None:
    """Force the LLM-free heuristic path in stage 1 and disable stage 6.

    This monkey-patches ``config.settings`` and ``query_processor`` after import;
    we never write either file. Production behavior is unchanged outside this
    process. See the module docstring for full rationale.
    """
    sys.path.insert(0, str(REPO_ROOT))
    from config import settings as _settings  # noqa: E402
    from src.retrieval.query.nodes import query_processor as _qp  # noqa: E402

    # Stage 1: force heuristic path. The pipeline reads
    # ``ollama_available = _check_llm_available()`` once at the top of
    # ``process_query``; overriding the symbol on the module makes subsequent
    # calls return False, which flips ``reformulate_and_evaluate_node`` to the
    # heuristic branch.
    _qp._check_llm_available = lambda: False
    _qp._check_ollama_available = lambda: False

    # Stage 6: disabled for the retrieval-only metric.
    _settings.GENERATION_ENABLED = False

    # Harmless legacy override — kept in case any code path still reads
    # temperature directly.
    _settings.QUERY_PROCESSING_TEMPERATURE = 0.0

    logger.info(
        "Determinism overrides applied: query_processor._check_llm_available=False "
        "(heuristic path forced), GENERATION_ENABLED=False"
    )


# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------


def _http_ready(url: str, timeout: float = 2.0) -> bool:
    try:
        with urlopen(url, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except (URLError, socket.timeout, ConnectionError, OSError):
        return False


def run_pre_flight() -> Tuple[bool, List[str]]:
    """Verify external dependencies are reachable. Returns (ok, error_messages).

    This project uses **embedded Weaviate** (``weaviate.connect_to_embedded``),
    not a separate service on :8080. The "service" for Weaviate is just the
    presence of the seed data directory on disk — the Java process is spawned
    in-process by the RAGChain constructor.
    """
    errors: List[str] = []

    # 1. Embedded Weaviate seed data directory must exist and be writable.
    # Import the settings lazily so the pre-flight respects any overrides
    # applied via environment variables.
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from config import settings as _settings  # noqa: E402
    except Exception as exc:
        errors.append(f"Failed to import config.settings: {exc}")
        return False, errors

    weaviate_data_dir = Path(_settings.WEAVIATE_DATA_DIR)
    if not weaviate_data_dir.exists():
        errors.append(
            f"Weaviate seed data missing: {weaviate_data_dir}. "
            "Copy it from a populated main checkout: "
            f"cp -a /path/to/main_repo/.weaviate_data {weaviate_data_dir}"
        )
    elif not os.access(weaviate_data_dir, os.W_OK):
        errors.append(
            f"Weaviate seed data dir exists but is not writable: {weaviate_data_dir}. "
            "Embedded Weaviate mutates the directory at startup, so it must be writable."
        )

    # 2. Local BGE models (embedding + reranker) must exist.
    embedding_model_path = Path(_settings.EMBEDDING_MODEL_PATH)
    if not embedding_model_path.exists():
        errors.append(
            f"Embedding model missing: {embedding_model_path}. "
            "Set RAG_EMBEDDING_MODEL or place the BAAI/bge-m3 checkpoint there."
        )
    reranker_model_path = Path(_settings.RERANKER_MODEL_PATH)
    if not reranker_model_path.exists():
        errors.append(
            f"Reranker model missing: {reranker_model_path}. "
            "Set RAG_RERANKER_MODEL or place the BAAI/bge-reranker-v2-m3 checkpoint there."
        )

    # 3. Ollama / LLM provider must be reachable (actual HTTP service).
    ollama_url = os.environ.get("OLLAMA_HEALTH_URL", "http://localhost:11434/api/tags")
    if not _http_ready(ollama_url):
        errors.append(
            f"Ollama / LLM provider not reachable at {ollama_url}. "
            "Start Ollama (`ollama serve`) or set OLLAMA_HEALTH_URL."
        )

    # 4. Benchmark query set must exist.
    if not BENCHMARK_QUERIES_PATH.exists():
        errors.append(
            f"Benchmark queries missing: {BENCHMARK_QUERIES_PATH}. "
            "This file is immutable and must be present."
        )

    return (len(errors) == 0), errors


# ---------------------------------------------------------------------------
# Doc-ID hashing — stable, content-derived, metadata-independent
# ---------------------------------------------------------------------------


def _doc_id(text: str) -> str:
    """Stable 16-char SHA1 of the document text. Used for set-equality checks."""
    return hashlib.sha1(text.encode("utf-8", errors="replace")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Benchmark execution
# ---------------------------------------------------------------------------


def _load_queries() -> List[Dict[str, str]]:
    raw = orjson.loads(BENCHMARK_QUERIES_PATH.read_bytes())
    return list(raw["queries"])


def _retrieval_only_ms(stage_timings: List[Dict[str, Any]]) -> float:
    """Sum the ms of stages that count toward the retrieval-only metric."""
    return round(
        sum(float(e.get("ms", 0.0)) for e in stage_timings if e.get("stage") in RETRIEVAL_STAGES),
        1,
    )


def _per_stage_ms(stage_timings: List[Dict[str, Any]]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for entry in stage_timings:
        stage = entry.get("stage")
        if stage in RETRIEVAL_STAGES:
            out[stage] = out.get(stage, 0.0) + float(entry.get("ms", 0.0))
    return out


def _percentile(values: List[float], pct: float) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    k = (len(sorted_vals) - 1) * pct
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return round(sorted_vals[f], 1)
    return round(sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f), 1)


def run_benchmark(reps: int = REPS_PER_QUERY) -> Dict[str, Any]:
    """Execute the benchmark and return a structured report dict.

    The report contains both per-query records (used for the regression
    guard) and aggregate latency statistics (the score).
    """
    _patch_settings_for_determinism()
    sys.path.insert(0, str(REPO_ROOT))
    # Import lazily after patching settings.
    from src.retrieval.pipeline.rag_chain import RAGChain  # noqa: E402

    queries = _load_queries()
    logger.info(
        "Constructing RAGChain (this loads embedding + reranker models, may take 30s)..."
    )
    chain_t0 = time.perf_counter()
    chain = RAGChain(persistent_weaviate=True)
    logger.info("RAGChain ready in %.0fms.", (time.perf_counter() - chain_t0) * 1000)

    # Warm-up pass: run 2 discard-me queries so the first *timed* query is
    # not inflated by cold embedding/reranker forward passes. Without this,
    # query 0's retrieval-ms is ~2x the warm steady-state and p99 becomes
    # noisy in small samples.
    logger.info("Warming up models with 2 discard queries...")
    try:
        chain.run(query="warmup query for embedding and reranker cold start",
                  skip_generation=True, fast_path=False)
        chain.run(query="a second warmup query to steady throughput",
                  skip_generation=True, fast_path=False)
    except Exception as exc:
        logger.warning("Warm-up query failed (continuing): %s", exc)
    logger.info("Warm-up complete. Starting timed benchmark.")

    per_query: List[Dict[str, Any]] = []
    all_retrieval_ms: List[float] = []
    all_per_stage: Dict[str, List[float]] = {s: [] for s in RETRIEVAL_STAGES}

    try:
        for q in queries:
            qid = q["id"]
            qtext = q["text"]
            samples_ms: List[float] = []
            stage_samples: Dict[str, List[float]] = {s: [] for s in RETRIEVAL_STAGES}
            last_action: Optional[str] = None
            last_doc_ids: Optional[List[str]] = None
            last_error: Optional[str] = None

            for rep in range(reps):
                t_query_start = time.perf_counter()
                try:
                    response = chain.run(
                        query=qtext,
                        skip_generation=True,
                        fast_path=False,
                    )
                except Exception as exc:
                    last_error = f"{type(exc).__name__}: {exc}"
                    logger.error(
                        "Query %s rep %d crashed: %s\n%s",
                        qid,
                        rep,
                        last_error,
                        traceback.format_exc(),
                    )
                    continue

                stage_timings = list(response.stage_timings or [])
                retrieval_ms = _retrieval_only_ms(stage_timings)
                samples_ms.append(retrieval_ms)
                all_retrieval_ms.append(retrieval_ms)

                ps = _per_stage_ms(stage_timings)
                for stage, ms in ps.items():
                    stage_samples[stage].append(ms)
                    all_per_stage[stage].append(ms)

                # Capture the last successful run's outputs for the contract.
                last_action = str(response.action)
                last_doc_ids = sorted(_doc_id(r.text) for r in (response.results or []))

                logger.info(
                    "[%s rep %d] retrieval=%.0fms action=%s top_k=%d wall=%.0fms",
                    qid,
                    rep,
                    retrieval_ms,
                    last_action,
                    len(last_doc_ids),
                    (time.perf_counter() - t_query_start) * 1000,
                )

            per_query.append(
                {
                    "id": qid,
                    "kind": q.get("kind", ""),
                    "text": qtext,
                    "samples_ms": samples_ms,
                    "median_ms": round(statistics.median(samples_ms), 1) if samples_ms else None,
                    "per_stage_median_ms": {
                        s: (round(statistics.median(v), 1) if v else None)
                        for s, v in stage_samples.items()
                    },
                    "action": last_action,
                    "top_k_doc_ids": last_doc_ids or [],
                    "error": last_error,
                }
            )

    finally:
        try:
            chain.close()
        except Exception as exc:
            logger.warning("Error closing RAGChain: %s", exc)

    aggregate = {
        "retrieval_p50_ms": _percentile(all_retrieval_ms, 0.50),
        "retrieval_p95_ms": _percentile(all_retrieval_ms, 0.95),
        "retrieval_p99_ms": _percentile(all_retrieval_ms, 0.99),
        "retrieval_mean_ms": round(statistics.mean(all_retrieval_ms), 1) if all_retrieval_ms else 0.0,
        "samples_total": len(all_retrieval_ms),
    }
    per_stage_agg = {
        s: {
            "p50_ms": _percentile(v, 0.50),
            "p95_ms": _percentile(v, 0.95),
            "mean_ms": round(statistics.mean(v), 1) if v else 0.0,
            "samples": len(v),
        }
        for s, v in all_per_stage.items()
    }

    return {
        "schema_version": 1,
        "queries_total": len(queries),
        "reps_per_query": reps,
        "aggregate": aggregate,
        "per_stage": per_stage_agg,
        "per_query": per_query,
    }


# ---------------------------------------------------------------------------
# Regression guard — compare against baseline snapshot
# ---------------------------------------------------------------------------


def capture_baseline(report: Dict[str, Any]) -> Dict[str, Any]:
    """Persist baseline outputs and report. Called once on iteration 001."""
    snapshot = {
        "_comment": (
            "IMMUTABLE baseline snapshot. Captured on iteration 001. "
            "Compared by the regression guard against every subsequent iteration. "
            "DO NOT MODIFY by hand — restart the loop with a new baseline if needed."
        ),
        "queries": {
            q["id"]: {
                "action": q["action"],
                "top_k_doc_ids": q["top_k_doc_ids"],
                "median_ms": q["median_ms"],
            }
            for q in report["per_query"]
        },
    }
    BASELINE_OUTPUTS_PATH.write_bytes(orjson.dumps(snapshot, option=orjson.OPT_INDENT_2))
    BASELINE_REPORT_PATH.write_bytes(orjson.dumps(report, option=orjson.OPT_INDENT_2))
    logger.info(
        "Baseline captured: %s queries, p95=%.0fms",
        len(snapshot["queries"]),
        report["aggregate"]["retrieval_p95_ms"],
    )
    return snapshot


def check_regression_guard(
    report: Dict[str, Any], baseline: Dict[str, Any]
) -> Dict[str, Any]:
    """Diff the current report against the baseline snapshot.

    Returns a guard summary with ``passed: bool``, ``drift_count``, and
    per-query divergence details.
    """
    baseline_queries = baseline.get("queries", {})
    drifts: List[Dict[str, Any]] = []

    for q in report["per_query"]:
        qid = q["id"]
        base = baseline_queries.get(qid)
        if base is None:
            drifts.append({"id": qid, "reason": "missing from baseline"})
            continue

        action_match = q["action"] == base.get("action")
        cur_set = set(q.get("top_k_doc_ids") or [])
        base_set = set(base.get("top_k_doc_ids") or [])
        set_match = cur_set == base_set

        if not action_match or not set_match:
            drifts.append(
                {
                    "id": qid,
                    "action_match": action_match,
                    "set_match": set_match,
                    "missing_from_current": sorted(base_set - cur_set),
                    "extra_in_current": sorted(cur_set - base_set),
                    "current_action": q["action"],
                    "baseline_action": base.get("action"),
                }
            )

    drift_count = len(drifts)
    drift_fraction = drift_count / max(len(baseline_queries), 1)
    passed = drift_fraction <= DRIFT_TOLERANCE

    return {
        "passed": passed,
        "drift_count": drift_count,
        "drift_fraction": round(drift_fraction, 3),
        "tolerance": DRIFT_TOLERANCE,
        "drifts": drifts,
    }


# ---------------------------------------------------------------------------
# Lint check — logging + error handling + timing on IO functions
# ---------------------------------------------------------------------------


class _IoFunctionLinter(ast.NodeVisitor):
    """Walk an AST and report functions that touch IO without proper guards."""

    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.failures: List[Dict[str, Any]] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._check_function(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._check_function(node)
        self.generic_visit(node)

    def _check_function(self, node: ast.AST) -> None:
        name = getattr(node, "name", "<anon>")
        # Skip dunder methods (init, repr, etc.) — they rarely do their own IO
        if name.startswith("__") and name.endswith("__"):
            return

        body_calls = _collect_call_names(node)
        body_attrs = _collect_attr_chains(node)

        touches_io = (
            any(k in name.lower() for k in IO_KEYWORD_HINTS)
            or bool(body_calls & IO_CALL_MARKERS)
        )
        if not touches_io:
            return

        has_logger = any("logger" in chain and any(lvl in chain for lvl in LOGGER_LEVELS) for chain in body_attrs)
        has_timing = bool(body_calls & TIMING_MARKERS) or any(
            any(t in chain for t in TIMING_MARKERS) for chain in body_attrs
        )
        has_try = _has_try(node)

        missing: List[str] = []
        if not has_logger:
            missing.append("logger.<level>")
        if not has_timing:
            missing.append("timing primitive (perf_counter / TimingPool.record / tracer.span)")
        # We require try/except OR delegation to a known guarded helper. We're
        # lenient here — we only flag if the function has zero error handling
        # AND directly calls an IO marker.
        if not has_try and bool(body_calls & IO_CALL_MARKERS):
            missing.append("try/except around external call")

        if missing:
            self.failures.append(
                {
                    "file": str(self.file_path.relative_to(REPO_ROOT)),
                    "function": name,
                    "lineno": getattr(node, "lineno", -1),
                    "missing": missing,
                }
            )


def _collect_call_names(node: ast.AST) -> set:
    names: set = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
    return names


def _collect_attr_chains(node: ast.AST) -> List[str]:
    chains: List[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Attribute):
            parts: List[str] = []
            cur: ast.AST = child
            while isinstance(cur, ast.Attribute):
                parts.append(cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name):
                parts.append(cur.id)
            chains.append(".".join(reversed(parts)))
    return chains


def _has_try(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Try):
            return True
    return False


def run_lint_check() -> Dict[str, Any]:
    """Lint every mutable file. Returns ``{passed, failures, files_checked}``."""
    failures: List[Dict[str, Any]] = []
    files_checked: List[str] = []
    for rel in MUTABLE_FILES:
        path = REPO_ROOT / rel
        if not path.exists():
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            failures.append(
                {
                    "file": rel,
                    "function": "<file>",
                    "lineno": getattr(exc, "lineno", -1),
                    "missing": [f"file does not parse: {exc}"],
                }
            )
            continue
        files_checked.append(rel)
        linter = _IoFunctionLinter(path)
        linter.visit(tree)
        failures.extend(linter.failures)
    return {
        "passed": len(failures) == 0,
        "failures": failures,
        "files_checked": files_checked,
    }


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Auto-research benchmark harness for the retrieval query pipeline. IMMUTABLE."
    )
    parser.add_argument(
        "--baseline",
        action="store_true",
        help="Run benchmark and persist as the baseline snapshot. Use only on iteration 001.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Write the per-iteration report JSON to this path.",
    )
    parser.add_argument(
        "--reps",
        type=int,
        default=REPS_PER_QUERY,
        help=f"Repetitions per query (default {REPS_PER_QUERY}).",
    )
    parser.add_argument(
        "--skip-pre-flight",
        action="store_true",
        help="Skip the Weaviate / Ollama / queries pre-flight (for harness self-tests only).",
    )
    args = parser.parse_args(argv)

    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)

    if not args.skip_pre_flight:
        ok, errors = run_pre_flight()
        if not ok:
            for err in errors:
                logger.error("Pre-flight failed: %s", err)
            return 2

    lint = run_lint_check()
    if not lint["passed"]:
        logger.warning(
            "Lint check failed for %d function(s):", len(lint["failures"])
        )
        for f in lint["failures"]:
            logger.warning(
                "  %s:%d %s — missing: %s",
                f["file"],
                f["lineno"],
                f["function"],
                ", ".join(f["missing"]),
            )

    try:
        report = run_benchmark(reps=args.reps)
    except Exception as exc:
        logger.error("Benchmark crashed: %s\n%s", exc, traceback.format_exc())
        return 3

    report["lint_check"] = lint

    if args.baseline:
        capture_baseline(report)
        report["regression_guard"] = {
            "passed": True,
            "drift_count": 0,
            "drift_fraction": 0.0,
            "tolerance": DRIFT_TOLERANCE,
            "drifts": [],
            "_note": "baseline run — guard trivially passes",
        }
    else:
        if not BASELINE_OUTPUTS_PATH.exists():
            logger.error(
                "Baseline missing at %s. Run with --baseline once before iteration loop.",
                BASELINE_OUTPUTS_PATH,
            )
            return 4
        baseline = orjson.loads(BASELINE_OUTPUTS_PATH.read_bytes())
        report["regression_guard"] = check_regression_guard(report, baseline)

    out_path = args.report or (RESEARCH_DIR / "latest_report.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(orjson.dumps(report, option=orjson.OPT_INDENT_2))

    agg = report["aggregate"]
    rg = report["regression_guard"]
    logger.info(
        "RESULT — p50=%.0fms p95=%.0fms p99=%.0fms samples=%d "
        "drift=%d/%d (passed=%s) lint_passed=%s | report=%s",
        agg["retrieval_p50_ms"],
        agg["retrieval_p95_ms"],
        agg["retrieval_p99_ms"],
        agg["samples_total"],
        rg["drift_count"],
        report["queries_total"],
        rg["passed"],
        lint["passed"],
        out_path,
    )

    return 0 if (rg["passed"] and lint["passed"]) else 1


if __name__ == "__main__":
    sys.exit(main())
