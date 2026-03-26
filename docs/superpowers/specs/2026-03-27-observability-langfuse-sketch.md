# Brainstorm Sketch: Swappable Observability Subsystem with Langfuse

**Date:** 2026-03-27
**Goal:** Provider-agnostic observability with Langfuse as first backend; local Docker UI;
generic decorators in consumers (ingest, retrieval).

---

## Current State

`src/platform/observability/` has a flat structure:
- `contracts.py` — Span + Tracer ABC
- `providers.py` — `get_tracer()` factory
- `langfuse_tracer.py` — Langfuse implementation (flat, not isolated)
- `noop_tracer.py` — No-op fallback

**Gaps vs requirements:**
1. No `langfuse/` subdirectory — Langfuse code is not isolated
2. Consumers import from `.providers` (not the public `__init__`)
3. No context manager on Span (no `with tracer.span() as s:`)
4. No `@observe` decorator for simple function-level tracing
5. No `trace` concept (grouping spans into a logical request trace)
6. No generation tracing (LLM input/output/model/tokens)
7. No Langfuse Docker service in docker-compose
8. `noop_tracer.py` not isolated in `noop/` subdirectory

---

## Chosen Approach: Guardrails-Mirror Pattern

Mirror the `src/guardrails/` architecture:

```
src/platform/observability/
├── __init__.py          # public API: get_tracer, observe, Tracer, Span, GenerationTrace
├── backend.py           # ObservabilityBackend ABC (replaces contracts.py)
├── schemas.py           # SpanRecord, TraceRecord, GenerationRecord (moves from platform/schemas/)
├── noop/
│   ├── __init__.py
│   └── backend.py       # NoopBackend (all methods are no-ops)
└── langfuse/
    ├── __init__.py      # exposes: LangfuseBackend
    └── backend.py       # LangfuseBackend (all Langfuse SDK imports confined here)
```

**ABC contract (`backend.py`):**
- `start_span(name, attributes, parent) -> Span`
- `start_trace(name, metadata) -> TraceContext` (groups spans under a request trace)
- `observe(func, name, capture_input, capture_output)` — decorator factory hook
- `flush()` — drain pending observations (important for Temporal workers)

**Generic `@observe` decorator (in `__init__.py`):**
```python
@observe("reranker.rerank")
def rerank(self, query, documents): ...
```
Uses `_get_backend()` singleton internally — no provider import in consumer.

**Context manager on Span:**
```python
with get_tracer().span("name") as span:
    span.set_attribute("key", value)
```
`Span.__enter__/exit__` added to ABC.

**Consumer update:** All imports change from:
```python
from src.platform.observability.providers import get_tracer
```
to:
```python
from src.platform.observability import get_tracer, observe
```

---

## Infrastructure: Langfuse Docker Service

Add to `docker-compose.yml`:
- `langfuse-db` (PostgreSQL 16) — dedicated DB for Langfuse state
- `langfuse` (langfuse/langfuse:3) — UI + API on port 3000 (same as Temporal UI on 8080)
- Profile: `observability` (opt-in, like `monitoring`)
- Environment variables from `.env`

---

## Smell Test

**Recommendation:** Full reorganization as described.
**Counter:** Existing code works; just adding Docker + moving one file is simpler.
**Defense:** User explicitly requires `langfuse/` isolation, generic decorators, and swappable
architecture. A partial fix leaves langfuse imports scattered, making a future LangSmith swap
still require source changes. The full reorganization costs one refactor now vs. N refactors per
swap. The existing public API surface is tiny (only `get_tracer`), so the migration is bounded.

---

## Scope Boundary

**In scope:**
- Reorganize `observability/` per above structure
- Add `@observe` decorator + context manager
- Add `start_trace` / `flush` to backend ABC
- Langfuse Docker service (with PostgreSQL)
- Update all consumer imports (ingest + retrieval)
- `@summary` blocks + README update

**Out of scope:**
- LangSmith backend implementation
- Multi-tenant trace isolation
- Prometheus → Langfuse bridging
- OpenTelemetry exporter
