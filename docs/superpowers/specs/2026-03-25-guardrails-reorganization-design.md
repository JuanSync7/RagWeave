# Guardrails Reorganization — Design Specification

**Project:** AION RAG Platform
**Date:** 2026-03-25
**Status:** Approved
**Domain:** `src/guardrails/` + `docs/guardrails/`

---

## 1. Problem Statement

NeMo Guardrails code and docs are currently co-located with the retrieval pipeline (`src/guardrails/runtime.py` imported directly by `rag_chain.py`, docs living in `docs/retrieval/`). This creates three problems:

1. **No swappability** — `rag_chain.py`'s `_init_guardrails()` method contains 9 internal guardrail imports. Swapping to a different backend (GuardrailsAI, LlamaGuard) requires changing retrieval code.
2. **NeMo coupling in shared rails** — `injection.py`, `toxicity.py`, `intent.py` call `GuardrailsRuntime.get()` internally, pulling a NeMo dependency into what should be generic ML logic.
3. **Misplaced docs** — NeMo Guardrails spec and implementation docs live in `docs/retrieval/` instead of `docs/guardrails/`.

---

## 2. Goals

- Make the guardrail backend swappable at config level with zero changes to `retrieval/`.
- Separate generic ML rails from NeMo-specific runtime logic.
- Co-locate all guardrail docs under `docs/guardrails/`.
- Add no measurable latency (dispatch overhead is a single Python function call).

---

## 3. Design

### 3.1 Directory Structure

```
src/guardrails/
  __init__.py                  # Public API: run_input_rails(), run_output_rails(), schemas
  backend.py                   # GuardrailBackend ABC — the formal backend contract
  common/
    schemas.py                 # Generic contracts: InputRailResult, OutputRailResult,
                               #   GuardrailsMetadata, RailVerdict, RailExecution (unchanged)
    merge_gate.py              # RailMergeGate — moved from executor.py, generic schema logic
  shared/
    pii.py                     # Moved from guardrails/pii.py — pure ML, no runtime import
    toxicity.py                # Same
    injection.py               # Same (NeMo enhancement extracted out)
    intent.py                  # Same
    faithfulness.py            # Same
    topic_safety.py            # Same
    gliner_pii.py              # Same
  nemo_guardrails/
    __init__.py
    backend.py                 # NemoBackend(GuardrailBackend) — implements the ABC
    runtime.py                 # Moved from guardrails/runtime.py (LLMRails singleton)
    executor.py                # Moved from guardrails/executor.py (parallel rail execution)
  # future peer backends:
  # guardrails_ai/
  #   backend.py               # GuardrailsAIBackend(GuardrailBackend)

docs/guardrails/
  nemo_guardrails/
    NEMO_GUARDRAILS_SPEC.md          # Moved from docs/retrieval/
    NEMO_GUARDRAILS_IMPLEMENTATION.md # Moved from docs/retrieval/
  COLANG_GUARDRAILS_DESIGN.md        # Already here, unchanged
  COLANG_GUARDRAILS_SPEC.md          # Already here, unchanged
  COLANG_GUARDRAILS_ENGINEERING_GUIDE.md  # Already here, unchanged
  COLANG_GUARDRAILS_IMPLEMENTATION.md     # Already here, unchanged
```

### 3.2 Data Flow

The retrieval pipeline interacts with guardrails through exactly three symbols:

```
retrieval/rag_chain.py
  │
  ├─ run_input_rails(query: str, tenant_id: str) → InputRailResult
  │     └─ GuardrailBackend.run_input_rails()  [dispatched by config]
  │           └─ NemoBackend → executor.py → shared/ rails + NeMo LLM layer
  │
  ├─ run_output_rails(answer: str, chunks: list[str]) → OutputRailResult
  │     └─ GuardrailBackend.run_output_rails() [dispatched by config]
  │           └─ NemoBackend → executor.py → shared/ rails + NeMo LLM layer
  │
  └─ RailMergeGate.merge(query_result, rail_result) → routing dict
        (generic schema logic, no backend dependency)
```

`rag_chain.py` never imports from backend-specific modules. Swapping backends requires only a config key change (`GUARDRAIL_BACKEND`).

### 3.3 Backend ABC (`src/guardrails/backend.py`)

```python
from abc import ABC, abstractmethod
from src.guardrails.common.schemas import InputRailResult, OutputRailResult

class GuardrailBackend(ABC):

    @abstractmethod
    def run_input_rails(self, query: str, tenant_id: str = "") -> InputRailResult:
        """Run all input rails (intent, injection, PII, toxicity, topic safety)."""
        ...

    @abstractmethod
    def run_output_rails(self, answer: str, context_chunks: list[str]) -> OutputRailResult:
        """Run all output rails (faithfulness, PII, toxicity)."""
        ...

    def register_rag_chain(self, rag_chain: object) -> None:
        """Optional hook for backends that need a reference to the RAG chain.

        Default is a no-op. NemoBackend overrides this to call
        config.guardrails.actions.set_rag_chain(rag_chain), which registers
        the chain reference with Colang action handlers.
        """
```

Python raises `TypeError` at instantiation if a backend omits either abstract method. `register_rag_chain` is a concrete no-op by default — only NeMo overrides it. Adding a new backend = implement the two abstract methods; override `register_rag_chain` only if the backend needs a RAG chain reference.

### 3.4 Top-Level Dispatcher (`src/guardrails/__init__.py`)

```python
_backend: GuardrailBackend | None = None

def _get_backend() -> GuardrailBackend:
    global _backend
    if _backend is None:
        from config.settings import GUARDRAIL_BACKEND
        if GUARDRAIL_BACKEND == "nemo":
            from src.guardrails.nemo_guardrails.backend import NemoBackend
            _backend = NemoBackend()
        else:
            raise ValueError(
                f"Unknown GUARDRAIL_BACKEND: {GUARDRAIL_BACKEND!r}. "
                "Valid values: 'nemo'"
            )
    return _backend

def run_input_rails(query: str, tenant_id: str = "") -> InputRailResult:
    return _get_backend().run_input_rails(query, tenant_id)

def run_output_rails(answer: str, context_chunks: list[str]) -> OutputRailResult:
    return _get_backend().run_output_rails(answer, context_chunks)

def register_rag_chain(rag_chain: object) -> None:
    """Forward RAG chain registration to the active backend (NeMo-specific hook)."""
    _get_backend().register_rag_chain(rag_chain)
```

### 3.5 NeMo Backend (`src/guardrails/nemo_guardrails/backend.py`)

`NemoBackend` wires up shared rails with the NeMo runtime injected at construction — rather than the shared rails pulling the runtime themselves. It also overrides `register_rag_chain` to forward the call into the Colang action handlers:

```python
class NemoBackend(GuardrailBackend):

    def __init__(self):
        runtime = GuardrailsRuntime.get()
        self._input_executor = InputRailExecutor(
            intent_classifier=IntentClassifier(runtime=runtime),
            injection_detector=InjectionDetector(runtime=runtime),
            pii_detector=PIIDetector(),
            toxicity_filter=ToxicityFilter(runtime=runtime),
            topic_safety_checker=TopicSafetyChecker(runtime=runtime),
        )
        self._output_executor = OutputRailExecutor(
            faithfulness_checker=FaithfulnessChecker(),
            pii_detector=PIIDetector(),
            toxicity_filter=ToxicityFilter(runtime=runtime),
        )

    def run_input_rails(self, query: str, tenant_id: str = "") -> InputRailResult:
        return self._input_executor.execute(query, tenant_id)

    def run_output_rails(self, answer: str, context_chunks: list[str]) -> OutputRailResult:
        return self._output_executor.execute(answer, context_chunks)

    def register_rag_chain(self, rag_chain: object) -> None:
        try:
            from config.guardrails.actions import set_rag_chain
            set_rag_chain(rag_chain)
        except ImportError:
            logger.warning("Could not register RAG chain reference — config.guardrails.actions not found")
```

### 3.6 Shared Rails — Breaking the NeMo Coupling

Each shared rail (`injection.py`, `toxicity.py`, `intent.py`, `topic_safety.py`) currently calls `GuardrailsRuntime.get()` internally. This coupling is removed: each rail accepts an optional `runtime` parameter in its constructor. When `runtime=None`, it runs pure ML/regex only.

```python
# Before (inside injection.py)
runtime = GuardrailsRuntime.get()
if runtime.initialized: ...

# After (injected at construction)
class InjectionDetector:
    def __init__(self, runtime=None):
        self._runtime = runtime
```

### 3.7 RailMergeGate

Moves from `executor.py` to `src/guardrails/common/merge_gate.py`. No logic changes — it operates only on `QueryResult` and `InputRailResult` (generic schemas) and has no backend dependency.

### 3.8 Impact on `rag_chain.py`

All 9 guardrail imports are inside `_init_guardrails()`, a lazy-init method called from `__init__`. They are replaced with 2 top-level imports and the `register_rag_chain` call moves to `_init_guardrails()`:

```python
# Before — 9 imports inside _init_guardrails() + a call site import
# (inside _init_guardrails)
from src.guardrails.executor import InputRailExecutor, OutputRailExecutor, RailMergeGate
from src.guardrails.faithfulness import FaithfulnessChecker
from src.guardrails.injection import InjectionDetector
from src.guardrails.intent import IntentClassifier
from src.guardrails.pii import PIIDetector
from src.guardrails.runtime import GuardrailsRuntime
from src.guardrails.topic_safety import TopicSafetyChecker
from src.guardrails.toxicity import ToxicityFilter
# (at call site, line 473)
from src.guardrails.common.schemas import GuardrailsMetadata

# After — 2 imports from public API, at module top-level
from src.guardrails import run_input_rails, run_output_rails, register_rag_chain, RailMergeGate
from src.guardrails.common.schemas import GuardrailsMetadata
```

`RailMergeGate` is re-exported from `src.guardrails.__init__` so `rag_chain.py` never imports from a sub-module directly. The `_init_guardrails()` method shrinks to backend initialization + `register_rag_chain(self)`.

---

## 4. SystemVerilog Analogy Summary

| SW Layer | SV Analogy |
|---|---|
| `common/schemas.py` | `typedef struct` / port type definitions |
| `backend.py` (ABC) | Module port list declaration |
| `shared/` | Reusable IP blocks (backend-agnostic) |
| `nemo_guardrails/backend.py` | Module instantiation with port connections |
| `__init__.py` dispatcher | Top-level wrapper module |
| `rag_chain.py` | Testbench / consumer |

---

## 5. What Does Not Change

- `common/schemas.py` — no changes to `InputRailResult`, `OutputRailResult`, `GuardrailsMetadata`, `RailVerdict`, `RailExecution`
- `executor.py` logic — moves to `nemo_guardrails/executor.py`, no logic changes
- `runtime.py` logic — moves to `nemo_guardrails/runtime.py`, no logic changes
- Colang configs (`config/guardrails/`) — untouched
- All existing rail behavior — unchanged, only import paths and construction patterns shift

---

## 6. Config Changes

```python
# config/settings.py
GUARDRAIL_BACKEND: str = os.getenv("GUARDRAIL_BACKEND", "nemo")
```

Default is `"nemo"` to preserve current behavior with no env var change required.

`RAG_NEMO_ENABLED` is retired. Its role — enabling/disabling the guardrail layer entirely — is subsumed by `GUARDRAIL_BACKEND`. Setting `GUARDRAIL_BACKEND=""` or `"none"` (to be handled in the dispatcher's `else` branch as a no-op backend) is the new way to disable guardrails. Keeping both flags would risk `GUARDRAIL_BACKEND=nemo` + `RAG_NEMO_ENABLED=false` producing contradictory behavior.
