# Retrieval New Engineer Onboarding Checklist

## Purpose

Use this one-page checklist to onboard quickly to the retrieval and query-serving stack.

## Day 1 Setup

- [ ] Set up environment and dependencies (`uv sync` or team-standard flow).
- [ ] Ensure required local runtime dependencies are reachable:
  - Temporal server
  - API server
  - worker process(es)
  - Ollama endpoint
- [ ] Read in order:
  1. `src/retrieval/README.md`
  2. `docs/retrieval/RETRIEVAL_ENGINEERING_GUIDE.md`
  3. `server/README.md`
- [ ] Run retrieval-focused tests available in repo and verify baseline behavior.

## First Change Flow (Safe Path)

- [ ] Choose the correct change location:
  - query behavior and confidence loop: `src/retrieval/query_processor.py`
  - retrieval orchestration/timing: `src/retrieval/rag_chain.py`
  - answer generation and streaming: `src/retrieval/generator.py`
  - API/workflow wiring: `server/api.py`, `server/workflows.py`, `server/activities.py`
- [ ] Preserve request/response schema compatibility.
- [ ] Keep stage timing and bucket totals complete when adding/modifying stages.
- [ ] Keep generation streaming path behavior equivalent to non-stream prompt semantics.
- [ ] Add/adjust tests and verify no regressions.
- [ ] Update README/docs for behavior or architecture changes.

## Common Gotchas

- [ ] Clarification loops trigger too often:
  - check confidence threshold, iteration cap, and reformulation payload parsing.
- [ ] Time budget behavior feels wrong:
  - verify timeout propagation (`overall_timeout_ms`) across API -> workflow -> activity -> chain.
- [ ] Streaming path differs from non-stream:
  - compare message building and response parsing code paths.
- [ ] Latency spikes with no code changes:
  - inspect Temporal schedule-to-start and worker saturation before modifying retrieval logic.
- [ ] Reranking looks off:
  - validate the retrieved chunk set and score distribution before adjusting prompts/models.

## Definition of Done (Retrieval PR)

- [ ] Changes preserve schema/API compatibility or include explicit migration notes.
- [ ] Observability/timing remains intact and still explains latency splits.
- [ ] Relevant tests pass locally.
- [ ] Documentation is updated (`src/retrieval/README.md` and docs in `docs/retrieval/`).
