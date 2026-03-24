<!-- @summary
Observability provider: Langfuse tracing or no-op fallback. Defines the Tracer contract and SpanRecord schema. Configured via RAG_OBSERVABILITY_PROVIDER.
@end-summary -->

# platform/observability

## Overview

This package provides pluggable LLM pipeline tracing. All instrumented call sites use `get_tracer()` to obtain a `Tracer` instance — the actual backend (Langfuse or no-op) is selected at runtime.

## Files

| File | Purpose | Key Exports |
| --- | --- | --- |
| `contracts.py` | Abstract `Tracer` protocol defining the tracing interface | `Tracer` |
| `providers.py` | Provider factory: selects Langfuse or no-op based on config | `get_tracer` |
| `langfuse_tracer.py` | Langfuse backend (lazy-imported to avoid hard dependency) | `LangfuseTracer` |
| `noop_tracer.py` | No-op fallback tracer (all calls are safe no-ops) | `NoopTracer` |
| `__init__.py` | Package facade | `get_tracer` |

## Configuration

| Env Var | Default | Description |
|---------|---------|-------------|
| `RAG_OBSERVABILITY_PROVIDER` | `langfuse` | Backend: `langfuse` or `noop` |
| `LANGFUSE_HOST` | `http://localhost:3000` | Langfuse server URL |
| `LANGFUSE_PUBLIC_KEY` | — | Langfuse project public key |
| `LANGFUSE_SECRET_KEY` | — | Langfuse project secret key |

## Usage

```python
from src.platform.observability import get_tracer

tracer = get_tracer()
with tracer.span("retrieval") as span:
    span.set_attribute("query", query_text)
    result = run_retrieval(...)
```
