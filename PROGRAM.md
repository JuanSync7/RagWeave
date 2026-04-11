# Retrieval Query Pipeline — Auto-Research Program

## Objective

Reduce **retrieval-only p95 latency** (stages 1–5: query_processing → kg_expansion → embedding → hybrid_search → reranking) of `RAGChain.ask(...)` while preserving the output contract. As a secondary, structural concern, ensure every stage has uniform logging, error handling, and duration tracking, with natural code flow.

Current baseline: **TBD** — recorded in iteration 001 by `scripts/benchmark_retrieval_query.py` against `research/benchmark_queries.json`. Generation (stage 6) is explicitly out of scope for latency optimization but is still invoked end-to-end so the harness measures realistic conditions.

## Scoring mode

**Numerical** — retrieval-only p95 latency in milliseconds, lower is better.

The harness emits a JSON report; the loop reads `retrieval_p95_ms` from it. Score is `retrieval_p95_ms` (lower is better — the loop compares with `<` instead of `>`).

## Metric

**Primary score**: `retrieval_p95_ms` from `research/iteration_<NNN>_report.json`, computed across 20 benchmark queries × 3 repetitions = 60 samples per iteration. Baseline is captured in iteration 001 and stored as `research/baseline_report.json`.

**Iteration kept** if BOTH:
1. **Primary metric** — one of:
   - `retrieval_p95_ms < best_p95_ms` (strict latency improvement), OR
   - `retrieval_p95_ms ≤ best_p95_ms` AND `lint_failure_count < best_lint_failure_count` (latency tied, lint strictly improved), OR
   - **Lint-progress tolerance band** — `lint_failure_count < best_lint_failure_count` AND `retrieval_p95_ms ≤ best_p95_ms × 1.05`. Rationale: the measured noise floor between runs is ±10% (see iter 002 discard in `research/iterations.tsv`), which swamps any single-iteration lint-only change. This band allows structural/lint progress to land as long as p95 is within 5% of the best — tight enough to catch real regressions, loose enough to survive GPU scheduler jitter. When this branch is taken, best_p95_ms is NOT advanced (only best_lint_failure_count is); the latency best remains frozen at the prior iteration.
2. **Hard guards (all must pass)**:
   - Regression guard: per-query `(action, top_k_doc_id_set)` matches baseline snapshot for ≥95% of the guarded (KG) subset (≤5% drift tolerance).
   - `tests/retrieval/` pytest still passes.
   - **Lint monotonicity**: `lint_failure_count ≤ best_lint_failure_count`. The baseline starts with N failures (measured at iteration 001b); kept iterations may not increase that count, only hold or decrease it. This drives the lint count toward zero.

**Iteration discarded** if any hard guard fails OR if neither the latency improvement nor the lint-progress band conditions above are satisfied.

## Regression guard — output contract

Before measuring latency, the harness re-runs the benchmark queries and compares each query's `(action, top_k_doc_id_set)` against `research/baseline_outputs.json`:

- **Scope**: only **KG queries** (`kind == "kg"`, 15 of 20) are asserted. Cold queries (`kind == "cold"`, 5 of 20) contribute latency samples but NO top-K assertion. Rationale: on an off-topic corpus, reranker scores for cold queries are all near-tied (0.03-0.05 range), and microscopic numerical shifts from legitimate optimizations (e.g. FP16 inference) would cause spurious drift without signaling any real quality regression. The 15 KG queries, by contrast, have clearly separated scores and are a meaningful correctness oracle.
- **Action match**: `RAGResponse.action.value` must equal the baseline action for that query.
- **Top-K set match**: the unordered set of `RankedResult.text → SHA1` (stable content hash — metadata-schema-independent) for the top-`RERANK_TOP_K` reranked results must equal the baseline set.
- **Drift tolerance**: at most 5% of the **guarded (KG) subset** may diverge = at most 1 of 15 queries. The diverging query is logged.
- **Stage 1 determinism**: the harness monkey-patches `query_processor._check_llm_available` to return `False` for the duration of the benchmark run, forcing the LLM-free heuristic path in stage 1. The heuristic is a pure function of word count → fully deterministic. This is a benchmark-only override; the production code is never modified. Rationale: strategy 4 (LLM call structure) is deferred, so iterations cannot fix LLM latency anyway, and running 60 samples × N iterations with live LLM (~15s per call observed) would make the loop impractically slow.

## Logging / error-handling / duration lint check

A lightweight static check the harness runs over every modified file in the mutable set. For each top-level function or method in stages 1–5 of the retrieval pipeline that performs I/O or calls an external service, it asserts:

1. There is at least one `logger.<level>(...)` call inside the function body (entry, exit, or both).
2. External calls (LLM, vector DB, model inference, file I/O) are wrapped in `try`/`except` OR delegated to a function that is itself guarded.
3. The function records its duration via `TimingPool.record(...)`, `time.perf_counter()` + `tp.record`, or `get_tracer().span(...)`.

The lint check is implemented as a Python AST walk in the harness — see `scripts/benchmark_retrieval_query.py::run_lint_check()`. It is **immutable**.

## Mutable files

Only modify these — everything else is locked:

- `src/retrieval/pipeline/rag_chain.py` — orchestration
- `src/retrieval/query/nodes/query_processor.py` — stage 1 (sanitize, reformulate, evaluate)
- `src/retrieval/query/nodes/reranker.py` — stage 5 (BGE reranker; logging/error-handling/timing only — DO NOT swap the model or change the math)
- `src/retrieval/common/utils.py` — shared utilities for the retrieval feature
- `src/retrieval/common/exceptions.py` — exception types
- `src/retrieval/common/__init__.py` and `src/retrieval/common/schemas.py` — only if a new shared helper or contract requires it
- New files under `src/retrieval/common/` for genuinely-shared helpers (caching, profiling, parallel-stage utilities)
- `requirements-api.txt`, `requirements.txt` — to add dependencies (must be pinned, must be justified in the iteration commit)
- `config/settings.py` — **scoped exception**: additive precision-mode keys only (`EMBEDDING_PRECISION_QUERY`, `EMBEDDING_PRECISION_INGEST`, `RERANKER_PRECISION`, `VISUAL_RETRIEVAL_PRECISION`, `GENERATION_PRECISION`) and their validator. Default values MUST preserve baseline behavior (`fp32`). No threshold tuning, no behavior toggles, no existing-key modification — if a change would alter any pre-existing key's default or type, it belongs in a different iteration and must be justified separately.

## Immutable files (DO NOT MODIFY)

- `PROGRAM.md` — this file
- `scripts/benchmark_retrieval_query.py` — the scoring harness
- `research/benchmark_queries.json` — fixed query set
- `research/baseline_outputs.json` — baseline `(action, top_k_ids)` snapshot
- `research/baseline_report.json` — baseline latency report
- All files under `tests/` — correctness suite (must continue to pass)
- `config/settings.py` — configuration is frozen EXCEPT for the additive precision-mode exception listed under "Mutable files" above
- `src/core/embeddings.py`, `src/core/knowledge_graph/` — shared infrastructure
- `src/vector_db/` — Weaviate client and contracts
- `src/platform/llm/` — LiteLLM provider
- `src/platform/timing.py`, `src/platform/observability/` — measurement infrastructure
- `src/retrieval/generation/**` — out of scope (stages 1–5 only)
- `src/guardrails/` — out of scope

## Exploration directions

User-provided strategies, in priority order. The loop picks one per iteration. **Do not invent strategies outside this list** unless all three are exhausted with no improvement.

1. **Parallelize independent stages.** Identify pairs of stages with no data dependency between them and run concurrently via `ThreadPoolExecutor` or `asyncio`. Candidates suggested by reading `rag_chain.py`:
   - `kg_expansion` || `query embedding` (both consume the processed query, neither feeds the other)
   - PII rail || query processing (already partially parallelized — verify it's optimal)
   - `visual_retrieval` || `hybrid_search` (if visual is enabled — independent backends)
   - Verify each candidate by tracing data dependencies before parallelizing.

2. **Pre-warm and cache.**
   - Extend the existing `warm_up_ollama()` to also warm: BGE embedding model, BGE reranker model, KG term inverted index, prompt template files.
   - Add an in-memory LRU cache (`functools.lru_cache` or `cachetools.LRUCache`) for: `_get_kg_terms()` already cached; `_load_injection_patterns()` already cached; `_match_kg_terms(query, max_terms)` for repeated queries; embedding for repeated queries (if not already cached at the embedding layer).
   - Cache invariants: cache must be safe across processes (or scoped per-worker); cache must be bounded; cached values must be immutable copies, not references.

3. **Faster libraries.**
   - `orjson` — already in use for KG load. Check whether all JSON paths in stages 1–5 use it (search for `json.loads`, `json.dumps`).
   - `msgspec` for `QueryState` and `QueryResult` schemas — claims 5–10× faster than dataclass+orjson for serialization. Only adopt if it doesn't break LangGraph state-merging.
   - `uvloop` if any stage uses `asyncio` — drop-in replacement for the default event loop.
   - **Excluded**: `google-re2` (not worth the dependency for sub-millisecond regex wins on patterns that run once per query).
   - **Excluded**: replacing the BGE reranker (out of scope per user).
   - **Excluded**: changing LLM call structure or threshold heuristics (deferred to a separate investigation).

## Constraints

- **Do not modify the LLM call structure** (no removing reformulation, no changing confidence thresholds, no swapping models). This is a separate investigation.
- **Do not replace the BGE reranker**. It is the dominant compute cost in stage 5 but is out of scope per user instruction.
- **`config/settings.py` is frozen EXCEPT for additive precision-mode keys** as defined in "Mutable files" above. All other optimizations must be expressible in code.
- **Do not introduce dependencies** without pinning the version in `requirements*.txt` and recording the version + rationale in the commit message.
- **Preserve all public API signatures** of `RAGChain.ask`, `process_query`, `LocalBGEReranker.rerank`. Internal helper signatures may change.
- **Preserve `@summary` blocks** at the top of every modified file. Update them if exports change.
- **Do not break `tests/retrieval/`**. The pytest suite is the secondary regression guard.
- **Logging contract**: every function modified by an iteration must satisfy the logging/error-handling/duration lint check. Iterations that touch a function and leave it lint-failing are discarded.

## Loop mechanics

1. Read `research/iterations.tsv` to see what's been tried; read git log for context.
2. Pick a strategy from exploration directions (or the most promising sub-strategy if the parent strategy has been partially tried).
3. Make a focused, single-idea change. Update modified files' `@summary` blocks if exports changed.
4. `git commit -m "iter NNN: <one-line summary>"` with a body explaining the change.
5. Pre-flight: verify Weaviate, Ollama, and local BGE models are reachable. If not, abort iteration with status `crash`.
6. Run `python scripts/benchmark_retrieval_query.py --report research/iteration_<NNN>_report.json`.
7. Read the report. Extract `retrieval_p95_ms`, `regression_guard_passed`, `lint_check_passed`.
8. Run `pytest tests/retrieval/ -q` — capture pass/fail.
9. Compare to previous best:
   - If `retrieval_p95_ms < best_p95_ms` AND all guards pass → status `keep`, advance best.
   - Else → status `discard`, `git reset --hard <best_commit>`.
10. Append a row to `research/iterations.tsv`: `iteration | commit | retrieval_p95_ms | retrieval_p50_ms | drift_count | lint_pass | tests_pass | status | summary`.
11. Check stop conditions; if not met, repeat.

## Stop conditions

- **Success**: `retrieval_p95_ms ≤ baseline_retrieval_p95_ms × 0.80` (≥20% reduction). Stop and write `changelog.md`.
- **No-progress**: 15 consecutive iterations with no improvement. Stop and write `changelog.md`.
- **Hard cap**: 30 total iterations. Stop and write `changelog.md`.
- **Service outage**: 2 consecutive iterations crash on pre-flight (Weaviate or Ollama down). Stop, write `changelog.md` noting the outage, and exit so the user can restart services.
- **Lint zero (bonus success)**: if `retrieval_p95_ms` target is met AND `lint_failure_count == 0`, this is a "perfect" stop — both objectives achieved. Stop immediately and write `changelog.md`.

## Pre-flight requirements (for `auto-research run`)

**Important**: this project uses **embedded Weaviate** (`weaviate.connect_to_embedded`). There is no separate Weaviate container — the Java process is spawned in-process by `RAGChain.__init__` from the `WEAVIATE_DATA_DIR` seed directory. The harness verifies filesystem paths, not HTTP endpoints, for Weaviate.

The harness `scripts/benchmark_retrieval_query.py` requires these before the loop starts:

1. **Weaviate seed data dir**: `config.settings.WEAVIATE_DATA_DIR` (default `<PROJECT_ROOT>/.weaviate_data`) exists AND is writable. Embedded Weaviate mutates this directory on startup. If the worktree was just created, copy it from a populated main checkout: `cp -a /path/to/main_repo/.weaviate_data ./.weaviate_data`.
2. **Ollama** (or LiteLLM proxy backing the `query` model alias): `curl http://localhost:11434/api/tags` returns 200. Override with `OLLAMA_HEALTH_URL` env var.
3. **Local BGE embedding model**: `EMBEDDING_MODEL_PATH` (default `~/models/baai/bge-m3`) exists.
4. **Local BGE reranker model**: `RERANKER_MODEL_PATH` (default `~/models/baai/bge-reranker-v2-m3`) exists.
5. **A populated Weaviate collection**: the seed data must include the `RAGDocuments` (or `VECTOR_COLLECTION_DEFAULT`) collection with documents. Otherwise `hybrid_search` returns 0 results and reranking is a no-op — the output contract would become trivially satisfied (all empty sets match all empty sets) and any iteration would "pass" the guard.
6. **Python environment**: the main repo's existing venv at `/home/juansync7/RagWeave/.venv` has all the required deps. Run the harness with `/home/juansync7/RagWeave/.venv/bin/python scripts/benchmark_retrieval_query.py ...`.

If pre-flight fails, the run loop refuses to start and prints clear error messages — it does not silently continue with mocks.
