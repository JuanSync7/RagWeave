<!-- @summary
Framework-agnostic LLM composition layer wrapping LangChain/LangGraph
primitives behind stable, project-owned interfaces.
@end-summary -->

# src/common/llm — LLM Composition Layer

Provider- and framework-agnostic wrappers for LLM operations.  Callers
import from `src.common.llm` and never touch LangChain / LangGraph directly.

## Module Map

| Module | Public API | Purpose |
|--------|-----------|---------|
| `provider.py` | `get_llm()` | LangChain ChatModel adapter over existing LLMProvider |
| `output.py` | `structured_output()` | Typed Pydantic output with auto-fix for weak models |
| `parallel.py` | `parallel()`, `aparallel()` | Fan-out/fan-in concurrent execution |
| `cache.py` | `enable_cache()`, `disable_cache()`, `clear_cache()` | SQLite/memory LLM response caching |
| `batch.py` | `batch()`, `abatch()` | Concurrent item processing with throttling |
| `fallback.py` | `fallback_chain()`, `afallback_chain()` | Strategy-level failover (not model-level) |
| `stream.py` | `stream()`, `astream()` | Unified event streaming with callbacks |
| `memory.py` | `conversation()` | Session-based message history |
| `schemas.py` | All public types | Framework-free dataclasses and enums |
| `utils.py` | *(internal)* | Message formatting, timing, error helpers |
| `graph/workflow.py` | `workflow()` | LangGraph StateGraph builder |
| `graph/checkpoint.py` | `get_checkpointer()` | Checkpoint backend factory |
| `graph/interrupt.py` | `human_gate()` | Human-in-the-loop pause/resume |

## Design Principles

1. **Zero framework leakage** — callers never import from `langchain_core`
   or `langgraph`.  If the framework is swapped, only this package changes.
2. **Reuse existing infrastructure** — `get_llm()` wraps the platform's
   `LLMProvider` (LiteLLM Router), inheriting all config, retries, and
   fallback chains already defined in `config/settings.py`.
3. **No new dependencies** — uses only `langchain-core` and `langgraph`,
   both already in `pyproject.toml`.

## Quick Start

```python
from src.common.llm import get_llm, structured_output, parallel, enable_cache

# Enable caching (optional)
enable_cache("sqlite")

# Get an LLM
llm = get_llm("default")

# Structured output with auto-fix
from pydantic import BaseModel
class GateVerdict(BaseModel):
    verdict: str
    reasoning: str

result = structured_output(llm, GateVerdict, "Evaluate this spec...")
print(result.parsed.verdict)    # "APPROVE"
print(result.auto_fixed)        # False (or True if fix model intervened)

# Parallel retrieval
ctx = parallel(
    vectors=lambda: search_weaviate(query),
    keywords=lambda: search_bm25(query),
)
print(ctx.results["vectors"])
print(ctx.timings["keywords"])  # wall-clock seconds
```
