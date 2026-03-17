# Retrieval Engineering Guide

## Audience and Goal

This guide is for engineers working on query-time retrieval behavior: query processing, KG expansion, hybrid search, reranking, and generation integration.

Primary outcomes:

- understand the retrieval execution path end-to-end,
- modify stages safely without breaking API behavior,
- diagnose latency and correctness issues quickly.

## Retrieval System Map

Core implementation modules:

- `src/retrieval/query_processor.py`: LangGraph query sanitization/reformulation/evaluation loop
- `src/retrieval/rag_chain.py`: orchestration for retrieval and optional generation
- `src/retrieval/reranker.py`: local reranking model wrapper
- `src/retrieval/generator.py`: Ollama answer generation and token streaming
- `server/api.py`: HTTP entrypoints including streaming endpoint
- `server/workflows.py` + `server/activities.py`: Temporal workflow/activity integration

## End-to-End Runtime Flow

1. API receives query request (`/query` or `/query/stream`).
2. Endpoint behavior:
   - `/query`: Temporal workflow executes retrieval plus generation in activity/runtime path.
   - `/query/stream`: Temporal workflow executes retrieval, then API streams generation tokens directly from Ollama.
3. `RAGChain.run(...)` executes retrieval stages:
   - query processing (`process_query`)
   - optional KG query expansion
   - embedding + hybrid search
   - reranking
   - optional generation (non-stream path)
4. Streaming path (`/query/stream`) typically:
   - runs retrieval first,
   - then streams generation tokens directly from Ollama for low latency UX.
5. Timings and observability are emitted per stage.

## Stage Contracts (RAGChain)

`RAGChain.run(...)` returns `RAGResponse` with:

- processed query and confidence details,
- ranked results,
- optional generated answer,
- `stage_timings` and `timing_totals`,
- budget-exhaustion metadata.

Budget and timing model:

- stage budgets are configurable (with per-request overrides),
- retrieval and generation are tracked as separate buckets,
- totals include bucket splits plus overall timing.

## Query Processor Design

`query_processor.py` uses a LangGraph state machine to:

1. sanitize input and detect risky patterns,
2. reformulate and evaluate query confidence (combined LLM call),
3. route to:
   - `SEARCH` when confidence threshold is met,
   - iterative reprocess until limit,
   - `ASK_USER` when exhaustion/failure conditions are hit.

Important design choices:

- prompt files are loaded from `prompts/` and cached at module scope,
- Ollama calls are wrapped with retry provider policies,
- fallback heuristic preserves behavior when Ollama is unavailable.

## Generation Design

`generator.py` supports:

- `generate(...)` for non-stream responses,
- `generate_stream(...)` for token streaming.

Streaming design constraints:

- response stream is always closed in `finally`,
- parse errors are logged without crashing the caller loop,
- prompt format is shared between streaming and non-stream paths.

## Retrieval Configuration Surface

The retrieval system is intentionally configurable through settings and request overrides:

- hybrid search controls (`alpha`, limits, filters),
- query processing limits (`max_query_iterations`, thresholds),
- fast path toggles and stage budgets,
- overall timeout budget (`overall_timeout_ms`),
- generation enable/disable and model endpoint configuration.

Timeout policy behavior:

- if budget is exhausted before search quality can be established (query processing, KG expansion, embedding), retrieval returns deterministic `ask_user`,
- if budget is exhausted after hybrid search, retrieval short-circuits with current ranked search candidates and skips extra expensive stages,
- generation is skipped whenever budget is exhausted.

Rule: avoid embedding runtime decisions as hardcoded constants when they should be policy/config.

## Observability and Performance Signals

Current signals to use first when debugging:

- stage-level pipeline timing (`stage_timings`, metrics buckets),
- query processor logs (`logs/query_processor.log`),
- API latency metrics and worker queue pressure,
- Temporal schedule-to-start latency and backlog.

When triaging slowness:

1. verify whether delay is retrieval bucket or generation bucket,
2. identify the slow stage from stage timings,
3. confirm upstream dependency health (Ollama, vector store, worker saturation),
4. tune replicas/concurrency before deep code changes.

## Safe Change Workflow

1. Pick the right layer:
   - query logic: `query_processor.py`
   - retrieval orchestration: `rag_chain.py`
   - model output shaping: `generator.py`
   - transport/orchestration: server modules
2. Preserve request/response contracts in schemas and API behavior.
3. Keep timing/observability intact when adding stages.
4. Add/adjust tests for regressions.
5. Update docs (`src/retrieval/README.md` + this guide + checklist if needed).

## Common Failure Modes

- Stream path works but non-stream fails:
  - compare `generate(...)` vs `generate_stream(...)` payload/options and response handling.
- Query keeps asking for clarification unexpectedly:
  - inspect confidence threshold, iteration limits, and reformulation output.
- Timeouts violate caller expectation:
  - verify request budget propagation through workflow/activity.
- Good retrieval, poor answer quality:
  - inspect reranked chunks and relevance distribution before changing prompts.
- Temporal healthy but high user latency:
  - check schedule-to-start and worker saturation first.

## Decision Record (Short Form)

- Decision: keep retrieval orchestration in `RAGChain` with explicit stage timing.
  - Why: predictable performance analysis and easier budget enforcement.
- Decision: separate query processing state machine from search orchestration.
  - Why: isolate reformulation logic from vector/reranker mechanics.
- Decision: support direct token streaming while preserving durable retrieval execution.
  - Why: low-latency UX without giving up workflow reliability.
