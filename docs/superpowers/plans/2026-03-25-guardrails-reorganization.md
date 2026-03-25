# Guardrails Reorganization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganize `src/guardrails/` so the guardrail backend is swappable at config level, NeMo-specific code lives in a subdirectory, and shared ML rails are decoupled from any backend runtime.

**Architecture:** A `GuardrailBackend` ABC defines two abstract methods (`run_input_rails`, `run_output_rails`). A config-driven dispatcher in `src/guardrails/__init__.py` instantiates the right backend singleton. `NemoBackend` in `src/guardrails/nemo_guardrails/` implements the ABC and injects the runtime into shared rails at construction. `src/retrieval/rag_chain.py` reduces from 9 guardrail imports to 2.

**Tech Stack:** Python 3.12, pytest, abc.ABC, existing guardrail dependencies (presidio, spaCy, nemoguardrails)

---

## File Map

**Create:**
- `src/guardrails/backend.py` — GuardrailBackend ABC
- `src/guardrails/shared/__init__.py` — empty
- `src/guardrails/shared/pii.py` — moved from `src/guardrails/pii.py`
- `src/guardrails/shared/gliner_pii.py` — moved from `src/guardrails/gliner_pii.py`
- `src/guardrails/shared/faithfulness.py` — moved from `src/guardrails/faithfulness.py`
- `src/guardrails/shared/injection.py` — moved from `src/guardrails/injection.py` (runtime decoupled)
- `src/guardrails/shared/toxicity.py` — moved from `src/guardrails/toxicity.py` (runtime decoupled)
- `src/guardrails/shared/intent.py` — moved from `src/guardrails/intent.py` (runtime decoupled)
- `src/guardrails/shared/topic_safety.py` — moved from `src/guardrails/topic_safety.py` (runtime decoupled)
- `src/guardrails/common/merge_gate.py` — RailMergeGate moved from `src/guardrails/executor.py`
- `src/guardrails/nemo_guardrails/__init__.py` — empty
- `src/guardrails/nemo_guardrails/runtime.py` — moved from `src/guardrails/runtime.py`
- `src/guardrails/nemo_guardrails/executor.py` — moved from `src/guardrails/executor.py` (minus RailMergeGate)
- `src/guardrails/nemo_guardrails/backend.py` — NemoBackend(GuardrailBackend)
- `docs/guardrails/nemo_guardrails/NEMO_GUARDRAILS_SPEC.md` — moved from `docs/retrieval/`
- `docs/guardrails/nemo_guardrails/NEMO_GUARDRAILS_IMPLEMENTATION.md` — moved from `docs/retrieval/`
- `tests/guardrails/test_backend_abc.py` — ABC contract tests
- `tests/guardrails/test_dispatcher.py` — dispatcher routing tests

**Modify:**
- `src/guardrails/__init__.py` — add dispatcher, re-export RailMergeGate + schemas
- `config/settings.py` — add `GUARDRAIL_BACKEND`, retire `RAG_NEMO_ENABLED`
- `src/retrieval/rag_chain.py` — replace 9 internal imports with 2 public API imports

**Delete (Task 9):**
- `src/guardrails/runtime.py`
- `src/guardrails/executor.py`
- `src/guardrails/pii.py`
- `src/guardrails/gliner_pii.py`
- `src/guardrails/faithfulness.py`
- `src/guardrails/injection.py`
- `src/guardrails/toxicity.py`
- `src/guardrails/intent.py`
- `src/guardrails/topic_safety.py`

---

## Task 1: Move docs

**Files:**
- Create: `docs/guardrails/nemo_guardrails/NEMO_GUARDRAILS_SPEC.md`
- Create: `docs/guardrails/nemo_guardrails/NEMO_GUARDRAILS_IMPLEMENTATION.md`
- Delete: `docs/retrieval/NEMO_GUARDRAILS_SPEC.md`
- Delete: `docs/retrieval/NEMO_GUARDRAILS_IMPLEMENTATION.md`

- [ ] **Step 1: Move the docs with git**

```bash
mkdir -p docs/guardrails/nemo_guardrails
git mv docs/retrieval/NEMO_GUARDRAILS_SPEC.md docs/guardrails/nemo_guardrails/NEMO_GUARDRAILS_SPEC.md
git mv docs/retrieval/NEMO_GUARDRAILS_IMPLEMENTATION.md docs/guardrails/nemo_guardrails/NEMO_GUARDRAILS_IMPLEMENTATION.md
```

- [ ] **Step 2: Update any cross-references in docs/retrieval/README.md**

Open `docs/retrieval/README.md` and remove or update any lines referencing `NEMO_GUARDRAILS_SPEC.md` or `NEMO_GUARDRAILS_IMPLEMENTATION.md`. Add a note pointing to `docs/guardrails/nemo_guardrails/` instead.

- [ ] **Step 3: Commit**

```bash
git add docs/
git commit -m "docs: move NeMo Guardrails docs to docs/guardrails/nemo_guardrails/"
```

---

## Task 2: Create GuardrailBackend ABC and tests

**Files:**
- Create: `src/guardrails/backend.py`
- Create: `tests/guardrails/test_backend_abc.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/guardrails/test_backend_abc.py`:

```python
"""Tests for the GuardrailBackend ABC contract."""
import pytest
from unittest.mock import MagicMock


def test_cannot_instantiate_abstract_backend():
    """ABC raises TypeError if abstract methods are not implemented."""
    from src.guardrails.backend import GuardrailBackend
    with pytest.raises(TypeError):
        GuardrailBackend()


def test_incomplete_backend_missing_output_raises():
    """A backend that only implements run_input_rails still raises."""
    from src.guardrails.backend import GuardrailBackend

    class PartialBackend(GuardrailBackend):
        def run_input_rails(self, query, tenant_id=""):
            return MagicMock()

    with pytest.raises(TypeError):
        PartialBackend()


def test_complete_backend_instantiates():
    """A backend implementing all abstract methods instantiates without error."""
    from src.guardrails.backend import GuardrailBackend
    from src.guardrails.common.schemas import InputRailResult, OutputRailResult

    class FullBackend(GuardrailBackend):
        def run_input_rails(self, query, tenant_id=""):
            return InputRailResult()
        def run_output_rails(self, answer, context_chunks):
            return OutputRailResult()
        def redact_pii(self, text):
            return text, []

    backend = FullBackend()
    assert backend is not None


def test_incomplete_backend_missing_redact_pii_raises():
    """A backend missing redact_pii raises TypeError."""
    from src.guardrails.backend import GuardrailBackend
    from src.guardrails.common.schemas import InputRailResult, OutputRailResult

    class NoRedactBackend(GuardrailBackend):
        def run_input_rails(self, query, tenant_id=""):
            return InputRailResult()
        def run_output_rails(self, answer, context_chunks):
            return OutputRailResult()

    with pytest.raises(TypeError):
        NoRedactBackend()


def test_register_rag_chain_default_is_noop():
    """Default register_rag_chain does nothing (no exception)."""
    from src.guardrails.backend import GuardrailBackend
    from src.guardrails.common.schemas import InputRailResult, OutputRailResult

    class FullBackend(GuardrailBackend):
        def run_input_rails(self, query, tenant_id=""):
            return InputRailResult()
        def run_output_rails(self, answer, context_chunks):
            return OutputRailResult()
        def redact_pii(self, text):
            return text, []

    backend = FullBackend()
    backend.register_rag_chain(object())  # must not raise
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/juansync7/RAG && python -m pytest tests/guardrails/test_backend_abc.py -v
```

Expected: `ModuleNotFoundError` — `src.guardrails.backend` does not exist yet.

- [ ] **Step 3: Create `src/guardrails/backend.py`**

```python
# @summary
# GuardrailBackend ABC — formal contract every guardrail backend must satisfy.
# Exports: GuardrailBackend
# Deps: abc, src.guardrails.common.schemas
# @end-summary
"""Abstract base class for guardrail backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Tuple


class GuardrailBackend(ABC):
    """Contract every guardrail backend must satisfy.

    Backends implement run_input_rails, run_output_rails, and redact_pii.
    register_rag_chain is a no-op by default; NemoBackend overrides it
    to register the chain with Colang action handlers.
    """

    @abstractmethod
    def run_input_rails(self, query: str, tenant_id: str = ""):
        """Run all input rails (intent, injection, PII, toxicity, topic safety).

        Args:
            query: Raw user query string.
            tenant_id: Optional tenant identifier used by some rails.

        Returns:
            InputRailResult with per-rail verdicts and metadata.
        """
        ...

    @abstractmethod
    def run_output_rails(self, answer: str, context_chunks: list[str]):
        """Run all output rails (faithfulness, PII, toxicity).

        Args:
            answer: Proposed assistant answer text.
            context_chunks: Retrieved context snippets used to generate the answer.

        Returns:
            OutputRailResult with per-rail verdicts and optional modified answer.
        """
        ...

    @abstractmethod
    def redact_pii(self, text: str) -> Tuple[str, List[dict]]:
        """Run PII detection and return the redacted text with detections.

        Used as a synchronous pre-LLM gate in rag_chain.py BEFORE the parallel
        input rails run. Backends that do not support PII should return
        (text, []) unchanged.

        Args:
            text: Input text to scan for PII.

        Returns:
            Tuple of (redacted_text, detections) where detections is a list of
            dicts with at least a "type" key.
        """
        ...

    def register_rag_chain(self, rag_chain: object) -> None:
        """Optional hook for backends that need a reference to the RAG chain.

        Default is a no-op. Override in backends that require this
        (e.g., NemoBackend registers the chain with Colang action handlers).

        Args:
            rag_chain: The RAGChain instance to register.
        """
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/guardrails/test_backend_abc.py -v
```

Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/guardrails/backend.py tests/guardrails/test_backend_abc.py
git commit -m "feat: add GuardrailBackend ABC contract"
```

---

## Task 3: Create shared/ — move ML rails, decouple runtime

Move the 7 individual rail files into `src/guardrails/shared/`. For the 4 rails that currently call `GuardrailsRuntime.get()` internally (`injection.py`, `toxicity.py`, `intent.py`, `topic_safety.py`), replace the internal pull with a constructor parameter `runtime=None`.

**Files:**
- Create: `src/guardrails/shared/__init__.py`
- Create: `src/guardrails/shared/pii.py` (moved, no changes)
- Create: `src/guardrails/shared/gliner_pii.py` (moved, no changes)
- Create: `src/guardrails/shared/faithfulness.py` (moved, no changes)
- Create: `src/guardrails/shared/injection.py` (moved + decoupled)
- Create: `src/guardrails/shared/toxicity.py` (moved + decoupled)
- Create: `src/guardrails/shared/intent.py` (moved + decoupled)
- Create: `src/guardrails/shared/topic_safety.py` (moved + decoupled)

- [ ] **Step 1: Create the shared/ package and move unchanged rails**

```bash
mkdir -p src/guardrails/shared
touch src/guardrails/shared/__init__.py
git mv src/guardrails/pii.py src/guardrails/shared/pii.py
git mv src/guardrails/gliner_pii.py src/guardrails/shared/gliner_pii.py
git mv src/guardrails/faithfulness.py src/guardrails/shared/faithfulness.py
```

- [ ] **Step 2: Decouple injection.py from GuardrailsRuntime**

`git mv src/guardrails/injection.py src/guardrails/shared/injection.py`

Then edit `src/guardrails/shared/injection.py`:

1. Remove the import: `from src.guardrails.runtime import GuardrailsRuntime`
2. Add `runtime=None` parameter to `InjectionDetector.__init__` and store as `self._runtime`
3. Replace every occurrence of `GuardrailsRuntime.get()` with `self._runtime`
4. Guard NeMo-specific imports (e.g., `nemoguardrails.library.*`) inside `if self._runtime is not None:` blocks

The pattern for every occurrence of the runtime pull:

```python
# Before
runtime = GuardrailsRuntime.get()
if runtime.initialized and runtime.rails is not None:
    ...

# After
if self._runtime is not None and self._runtime.initialized and self._runtime.rails is not None:
    ...
```

- [ ] **Step 3: Decouple toxicity.py, intent.py, topic_safety.py**

Repeat the same pattern for each:

```bash
git mv src/guardrails/toxicity.py src/guardrails/shared/toxicity.py
git mv src/guardrails/intent.py src/guardrails/shared/intent.py
git mv src/guardrails/topic_safety.py src/guardrails/shared/topic_safety.py
```

For each file:
- Remove `from src.guardrails.runtime import GuardrailsRuntime`
- Add `runtime=None` to `__init__`, store as `self._runtime`
- Replace all `GuardrailsRuntime.get()` with `self._runtime`

- [ ] **Step 4: Update `@summary` Deps lines in all 4 decoupled files**

In each decoupled file, change `Deps: src.guardrails.runtime, ...` to remove `src.guardrails.runtime`. Add `runtime: optional GuardrailsRuntime injected at construction` to the `@summary` description.

- [ ] **Step 5: Verify existing guardrail tests still pass**

```bash
python -m pytest tests/guardrails/ -v
```

Expected: all previously passing tests still pass (the colang tests import from `config.guardrails.actions`, not from `src.guardrails.*` directly, so they are unaffected).

- [ ] **Step 6: Commit**

```bash
git add src/guardrails/shared/ src/guardrails/
git commit -m "refactor: move ML rails to shared/, decouple GuardrailsRuntime via constructor injection"
```

---

## Task 4: Move RailMergeGate to common/merge_gate.py

**Files:**
- Create: `src/guardrails/common/merge_gate.py`
- Modify: `src/guardrails/executor.py` (remove RailMergeGate class)

- [ ] **Step 1: Create merge_gate.py**

Create `src/guardrails/common/merge_gate.py` and copy the `RailMergeGate` class verbatim from `src/guardrails/executor.py` into it. Update its imports to use `src.guardrails.common.schemas` and `src.guardrails.shared.intent` as needed.

The file header:

```python
# @summary
# Generic merge gate that combines QueryResult and InputRailResult into a routing decision.
# Exports: RailMergeGate
# Deps: src.guardrails.common.schemas, src.retrieval.common.schemas, logging
# @end-summary
"""Rail merge gate — routes based on combined query + input rail results."""
```

- [ ] **Step 2: Remove RailMergeGate from executor.py**

Delete the `RailMergeGate` class from `src/guardrails/executor.py`. Do NOT add a re-export — `executor.py` is moved to `nemo_guardrails/executor.py` in Task 5 (not deleted until Task 9), and a dangling re-export in the moved file would be confusing. Nothing imports `RailMergeGate` from `executor.py` directly except the old `rag_chain.py`, which is updated in Task 8 to use the top-level `src.guardrails` API instead.

- [ ] **Step 3: Verify tests pass**

```bash
python -m pytest tests/guardrails/ -v
```

- [ ] **Step 4: Commit**

```bash
git add src/guardrails/common/merge_gate.py src/guardrails/executor.py
git commit -m "refactor: move RailMergeGate to guardrails/common/merge_gate.py"
```

---

## Task 5: Create nemo_guardrails/ — move runtime and executor, create NemoBackend

**Files:**
- Create: `src/guardrails/nemo_guardrails/__init__.py`
- Create: `src/guardrails/nemo_guardrails/runtime.py` (moved)
- Create: `src/guardrails/nemo_guardrails/executor.py` (moved, minus RailMergeGate)
- Create: `src/guardrails/nemo_guardrails/backend.py`

- [ ] **Step 1: Move runtime.py and executor.py**

```bash
mkdir -p src/guardrails/nemo_guardrails
touch src/guardrails/nemo_guardrails/__init__.py
git mv src/guardrails/runtime.py src/guardrails/nemo_guardrails/runtime.py
git mv src/guardrails/executor.py src/guardrails/nemo_guardrails/executor.py
```

- [ ] **Step 2: Fix imports inside the moved files**

In `src/guardrails/nemo_guardrails/executor.py`, update every import of the form `from src.guardrails.X import Y` to use the new paths:
- `from src.guardrails.shared.faithfulness import FaithfulnessChecker`
- `from src.guardrails.shared.injection import InjectionDetector`
- `from src.guardrails.shared.intent import IntentClassifier`
- `from src.guardrails.shared.pii import PIIDetector`
- `from src.guardrails.shared.topic_safety import TopicSafetyChecker`
- `from src.guardrails.shared.toxicity import ToxicityFilter`

Remove any remaining `RailMergeGate` import/class from this file (it now lives in `common/merge_gate.py`).

- [ ] **Step 3: Create NemoBackend**

Create `src/guardrails/nemo_guardrails/backend.py`:

```python
# @summary
# NeMo Guardrails backend — implements GuardrailBackend using NeMo LLMRails runtime.
# Wires shared ML rails with the NeMo runtime injected at construction.
# Exports: NemoBackend
# Deps: src.guardrails.backend, src.guardrails.nemo_guardrails.runtime,
#       src.guardrails.nemo_guardrails.executor, src.guardrails.shared.*, config.settings
# @end-summary
"""NeMo Guardrails backend implementation."""

from __future__ import annotations

import logging

from src.guardrails.backend import GuardrailBackend
from src.guardrails.common.schemas import InputRailResult, OutputRailResult
from src.guardrails.nemo_guardrails.executor import InputRailExecutor, OutputRailExecutor
from src.guardrails.nemo_guardrails.runtime import GuardrailsRuntime
from src.guardrails.shared.faithfulness import FaithfulnessChecker
from src.guardrails.shared.injection import InjectionDetector
from src.guardrails.shared.intent import IntentClassifier
from src.guardrails.shared.pii import PIIDetector
from src.guardrails.shared.topic_safety import TopicSafetyChecker
from src.guardrails.shared.toxicity import ToxicityFilter

logger = logging.getLogger("rag.guardrails.nemo_backend")


class NemoBackend(GuardrailBackend):
    """GuardrailBackend implementation backed by NVIDIA NeMo Guardrails."""

    def __init__(self) -> None:
        from config.settings import (
            RAG_NEMO_CONFIG_DIR,
            RAG_NEMO_FAITHFULNESS_ACTION,
            RAG_NEMO_FAITHFULNESS_ENABLED,
            RAG_NEMO_FAITHFULNESS_SELF_CHECK,
            RAG_NEMO_FAITHFULNESS_THRESHOLD,
            RAG_NEMO_INJECTION_ENABLED,
            RAG_NEMO_INJECTION_LP_THRESHOLD,
            RAG_NEMO_INJECTION_MODEL_ENABLED,
            RAG_NEMO_INJECTION_PERPLEXITY_ENABLED,
            RAG_NEMO_INJECTION_PS_PPL_THRESHOLD,
            RAG_NEMO_INJECTION_SENSITIVITY,
            RAG_NEMO_INTENT_CONFIDENCE_THRESHOLD,
            RAG_NEMO_OUTPUT_PII_ENABLED,
            RAG_NEMO_OUTPUT_TOXICITY_ENABLED,
            RAG_NEMO_PII_ENABLED,
            RAG_NEMO_PII_EXTENDED,
            RAG_NEMO_PII_GLINER_ENABLED,
            RAG_NEMO_PII_SCORE_THRESHOLD,
            RAG_NEMO_RAIL_TIMEOUT_SECONDS,
            RAG_NEMO_TOPIC_SAFETY_ENABLED,
            RAG_NEMO_TOPIC_SAFETY_INSTRUCTIONS,
            RAG_NEMO_TOXICITY_ENABLED,
            RAG_NEMO_TOXICITY_THRESHOLD,
        )

        runtime = GuardrailsRuntime.get()
        runtime.initialize(RAG_NEMO_CONFIG_DIR)

        intent_classifier = IntentClassifier(
            confidence_threshold=RAG_NEMO_INTENT_CONFIDENCE_THRESHOLD,
            runtime=runtime,
        )
        injection_detector = (
            InjectionDetector(
                sensitivity=RAG_NEMO_INJECTION_SENSITIVITY,
                enable_perplexity=RAG_NEMO_INJECTION_PERPLEXITY_ENABLED,
                enable_model_classifier=RAG_NEMO_INJECTION_MODEL_ENABLED,
                lp_threshold=RAG_NEMO_INJECTION_LP_THRESHOLD,
                ps_ppl_threshold=RAG_NEMO_INJECTION_PS_PPL_THRESHOLD,
                runtime=runtime,
            )
            if RAG_NEMO_INJECTION_ENABLED
            else None
        )
        pii_detector = (
            PIIDetector(
                extended=RAG_NEMO_PII_EXTENDED,
                score_threshold=RAG_NEMO_PII_SCORE_THRESHOLD,
                use_gliner=RAG_NEMO_PII_GLINER_ENABLED,
            )
            if RAG_NEMO_PII_ENABLED
            else None
        )
        toxicity_filter = (
            ToxicityFilter(threshold=RAG_NEMO_TOXICITY_THRESHOLD, runtime=runtime)
            if RAG_NEMO_TOXICITY_ENABLED
            else None
        )
        topic_safety_checker = (
            TopicSafetyChecker(
                custom_instructions=RAG_NEMO_TOPIC_SAFETY_INSTRUCTIONS,
                runtime=runtime,
            )
            if RAG_NEMO_TOPIC_SAFETY_ENABLED
            else None
        )

        self._input_executor = InputRailExecutor(
            intent_classifier=intent_classifier,
            injection_detector=injection_detector,
            pii_detector=pii_detector,
            toxicity_filter=toxicity_filter,
            topic_safety_checker=topic_safety_checker,
            timeout_seconds=RAG_NEMO_RAIL_TIMEOUT_SECONDS,
        )

        faithfulness_checker = (
            FaithfulnessChecker(
                threshold=RAG_NEMO_FAITHFULNESS_THRESHOLD,
                action=RAG_NEMO_FAITHFULNESS_ACTION,
                use_self_check=RAG_NEMO_FAITHFULNESS_SELF_CHECK,
            )
            if RAG_NEMO_FAITHFULNESS_ENABLED
            else None
        )
        output_pii = pii_detector if RAG_NEMO_OUTPUT_PII_ENABLED else None
        output_toxicity = toxicity_filter if RAG_NEMO_OUTPUT_TOXICITY_ENABLED else None

        self._output_executor = OutputRailExecutor(
            faithfulness_checker=faithfulness_checker,
            pii_detector=output_pii,
            toxicity_filter=output_toxicity,
            timeout_seconds=RAG_NEMO_RAIL_TIMEOUT_SECONDS,
        )

        logger.info("NemoBackend initialized")

    def run_input_rails(self, query: str, tenant_id: str = "") -> InputRailResult:
        return self._input_executor.execute(query, tenant_id)

    def run_output_rails(self, answer: str, context_chunks: list[str]) -> OutputRailResult:
        return self._output_executor.execute(answer, context_chunks)

    def redact_pii(self, text: str):
        """Run PII detection synchronously (used as a pre-LLM gate in rag_chain)."""
        if self._input_executor.pii_detector is not None:
            return self._input_executor.pii_detector.redact(text)
        return text, []

    def register_rag_chain(self, rag_chain: object) -> None:
        try:
            from config.guardrails.actions import set_rag_chain
            set_rag_chain(rag_chain)
            logger.info("RAG chain reference registered with Colang action handlers")
        except ImportError:
            logger.warning(
                "Could not register RAG chain reference — config.guardrails.actions not found"
            )
```

- [ ] **Step 4: Run existing guardrail tests**

```bash
python -m pytest tests/guardrails/ -v
```

Expected: all tests pass. The colang tests import from `config.guardrails.actions`, which is unaffected.

- [ ] **Step 5: Commit**

```bash
git add src/guardrails/nemo_guardrails/
git commit -m "feat: create nemo_guardrails/ subdirectory with NemoBackend, moved runtime and executor"
```

---

## Task 6: Update `src/guardrails/__init__.py` — dispatcher and public API

Write tests first, then wire the dispatcher.

**Files:**
- Create: `tests/guardrails/test_dispatcher.py`
- Modify: `src/guardrails/__init__.py`

- [ ] **Step 1: Write failing dispatcher tests**

Create `tests/guardrails/test_dispatcher.py`:

```python
"""Tests for the guardrails top-level dispatcher."""
import pytest
from unittest.mock import patch, MagicMock
from src.guardrails.common.schemas import InputRailResult, OutputRailResult


def _make_full_backend():
    from src.guardrails.backend import GuardrailBackend

    class StubBackend(GuardrailBackend):
        def run_input_rails(self, query, tenant_id=""):
            return InputRailResult()
        def run_output_rails(self, answer, context_chunks):
            return OutputRailResult()

    return StubBackend()


def test_run_input_rails_delegates_to_backend():
    import src.guardrails as grd
    stub = _make_full_backend()
    grd._backend = stub
    result = grd.run_input_rails("test query")
    assert isinstance(result, InputRailResult)
    grd._backend = None  # reset


def test_run_output_rails_delegates_to_backend():
    import src.guardrails as grd
    stub = _make_full_backend()
    grd._backend = stub
    result = grd.run_output_rails("answer", ["chunk"])
    assert isinstance(result, OutputRailResult)
    grd._backend = None


def test_unknown_backend_raises_value_error():
    import src.guardrails as grd
    grd._backend = None
    with patch("config.settings.GUARDRAIL_BACKEND", "unknown_backend"):
        with pytest.raises(ValueError, match="Unknown GUARDRAIL_BACKEND"):
            grd._get_backend()
    grd._backend = None


def test_none_backend_returns_noop():
    import src.guardrails as grd
    grd._backend = None
    with patch("config.settings.GUARDRAIL_BACKEND", "none"):
        backend = grd._get_backend()
    result = backend.run_input_rails("query")
    assert isinstance(result, InputRailResult)
    redacted, detections = backend.redact_pii("some text")
    assert redacted == "some text"
    assert detections == []
    grd._backend = None


def test_rail_merge_gate_importable_from_top_level():
    from src.guardrails import RailMergeGate
    assert RailMergeGate is not None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/guardrails/test_dispatcher.py -v
```

Expected: failures because `_backend`, `_get_backend`, `RailMergeGate` not yet in `__init__.py`.

- [ ] **Step 3: Update `src/guardrails/__init__.py`**

Replace the entire file with:

```python
# @summary
# Public API for the guardrails subsystem. Config-driven dispatcher selects the
# active backend (default: "nemo"). Exposes run_input_rails, run_output_rails,
# register_rag_chain, RailMergeGate, and common schemas.
# Exports: run_input_rails, run_output_rails, register_rag_chain, RailMergeGate,
#          GuardrailsMetadata, InputRailResult, OutputRailResult, RailExecution, RailVerdict
# Deps: src.guardrails.backend, src.guardrails.common, config.settings
# @end-summary
"""Public guardrails API — backend-agnostic entry point for the retrieval pipeline."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.guardrails.common.schemas import (
    GuardrailsMetadata,
    InputRailResult,
    OutputRailResult,
    RailExecution,
    RailVerdict,
)
from src.guardrails.common.merge_gate import RailMergeGate

if TYPE_CHECKING:
    from src.guardrails.backend import GuardrailBackend

_backend: "GuardrailBackend | None" = None


class _NoOpBackend(GuardrailBackend):
    """Pass-through backend used when GUARDRAIL_BACKEND is '' or 'none'."""
    def run_input_rails(self, query, tenant_id=""):
        return InputRailResult()
    def run_output_rails(self, answer, context_chunks):
        return OutputRailResult()
    def redact_pii(self, text):
        return text, []


def _get_backend() -> "GuardrailBackend":
    global _backend
    if _backend is None:
        from config.settings import GUARDRAIL_BACKEND
        if GUARDRAIL_BACKEND == "nemo":
            from src.guardrails.nemo_guardrails.backend import NemoBackend
            _backend = NemoBackend()
        elif GUARDRAIL_BACKEND in ("", "none"):
            _backend = _NoOpBackend()
        else:
            raise ValueError(
                f"Unknown GUARDRAIL_BACKEND: {GUARDRAIL_BACKEND!r}. "
                "Valid values: 'nemo', 'none', ''"
            )
    return _backend


def run_input_rails(query: str, tenant_id: str = "") -> InputRailResult:
    """Run all configured input rails against the user query.

    Args:
        query: Raw user query string.
        tenant_id: Optional tenant identifier.

    Returns:
        InputRailResult with per-rail verdicts and metadata.
    """
    return _get_backend().run_input_rails(query, tenant_id)


def run_output_rails(answer: str, context_chunks: list[str]) -> OutputRailResult:
    """Run all configured output rails against the generated answer.

    Args:
        answer: Proposed assistant answer text.
        context_chunks: Retrieved context snippets used to generate the answer.

    Returns:
        OutputRailResult with per-rail verdicts and optional modified answer.
    """
    return _get_backend().run_output_rails(answer, context_chunks)


def redact_pii(text: str):
    """Run PII detection synchronously against the given text.

    Used as a pre-LLM gate in rag_chain.py before parallel input rails run.
    Returns (redacted_text, detections). If no PII backend is configured,
    returns (text, []) unchanged.

    Args:
        text: Input text to scan for PII.

    Returns:
        Tuple of (redacted_text, list[dict]).
    """
    return _get_backend().redact_pii(text)


def register_rag_chain(rag_chain: object) -> None:
    """Forward RAG chain registration to the active backend.

    NemoBackend uses this to register the chain with Colang action handlers.
    Other backends may no-op this call.

    Args:
        rag_chain: The RAGChain instance to register.
    """
    _get_backend().register_rag_chain(rag_chain)


__all__ = [
    "run_input_rails",
    "run_output_rails",
    "redact_pii",
    "register_rag_chain",
    "RailMergeGate",
    "GuardrailsMetadata",
    "InputRailResult",
    "OutputRailResult",
    "RailExecution",
    "RailVerdict",
]
```

- [ ] **Step 4: Run dispatcher tests**

```bash
python -m pytest tests/guardrails/test_dispatcher.py -v
```

Expected: 4 tests PASS.

- [ ] **Step 5: Run full guardrails test suite**

```bash
python -m pytest tests/guardrails/ -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/guardrails/__init__.py tests/guardrails/test_dispatcher.py
git commit -m "feat: add config-driven dispatcher to guardrails public API"
```

---

## Task 7: Update config/settings.py — add GUARDRAIL_BACKEND, retire RAG_NEMO_ENABLED

**Files:**
- Modify: `config/settings.py`

- [ ] **Step 1: Add GUARDRAIL_BACKEND**

In `config/settings.py`, find the block where `RAG_NEMO_ENABLED` is defined (around line 398) and add `GUARDRAIL_BACKEND` directly above it:

```python
# --- Guardrail Backend ---
GUARDRAIL_BACKEND: str = os.environ.get("GUARDRAIL_BACKEND", "nemo")
```

Do NOT remove `RAG_NEMO_ENABLED` yet — it is still referenced in `rag_chain.py` which is updated in Task 8.

- [ ] **Step 2: Run tests to confirm no regression**

```bash
python -m pytest tests/ -v -x --ignore=tests/test_rag_chain_integration.py
```

- [ ] **Step 3: Commit**

```bash
git add config/settings.py
git commit -m "feat: add GUARDRAIL_BACKEND config key (defaults to 'nemo')"
```

---

## Task 8: Update rag_chain.py — replace 9 internal imports with public API

**Files:**
- Modify: `src/retrieval/rag_chain.py`

- [ ] **Step 1: Add the two new top-level imports**

At the top of `src/retrieval/rag_chain.py`, after the existing imports block, add:

```python
from src.guardrails import run_input_rails, run_output_rails, register_rag_chain, RailMergeGate
from src.guardrails.common.schemas import GuardrailsMetadata
```

- [ ] **Step 2: Replace the `RAG_NEMO_ENABLED` guard and rewrite `_init_guardrails`**

Find the block in `__init__`:
```python
if RAG_NEMO_ENABLED:
    self._init_guardrails()
```

Replace with:
```python
if GUARDRAIL_BACKEND:
    self._init_guardrails()
```

Also update the `RAG_NEMO_ENABLED` import at the top of the file — replace `from config.settings import RAG_NEMO_ENABLED` with `from config.settings import GUARDRAIL_BACKEND`.

Rewrite `_init_guardrails` to use the public API. The entire method body collapses to:

```python
def _init_guardrails(self) -> None:
    """Initialize the configured guardrail backend."""
    logger.info("Initializing guardrails (backend=%s)...", GUARDRAIL_BACKEND)
    # Backend initialization happens lazily inside _get_backend() on first call.
    # Register this chain instance with the backend for action handler access.
    register_rag_chain(self)
    self._guardrails_merge_gate = RailMergeGate()
    logger.info("Guardrails initialized successfully")
```

Remove `self._guardrails_input_executor` and `self._guardrails_output_executor` instance variables — replace every usage site with direct calls to `run_input_rails()` and `run_output_rails()`.

- [ ] **Step 3: Update call sites throughout rag_chain.py**

Find every reference to `self._guardrails_input_executor.execute(...)` and replace with `run_input_rails(query, tenant_id)`. Find every reference to `self._guardrails_output_executor.execute(...)` and replace with `run_output_rails(answer, context_chunks)`.

Replace the `pii_detector = getattr(self._guardrails_input_executor, 'pii_detector', None)` block with a call to the public `redact_pii()` function. This block runs a **synchronous pre-LLM PII gate** before the parallel input rails stage — it redacts the raw query before sending it to the LLM. The replacement is:

```python
# Before (lines ~418-432)
pii_detector = getattr(self._guardrails_input_executor, 'pii_detector', None)
if pii_detector is not None:
    redacted_text, pii_detections = pii_detector.redact(query)
    if pii_detections:
        pii_gated_query = redacted_text
        ...

# After
from src.guardrails import redact_pii as _redact_pii  # already at module top-level after Step 1
redacted_text, pii_detections = _redact_pii(query)
if pii_detections:
    pii_gated_query = redacted_text
    ...
```

Remove the `if pii_detector is not None:` guard — `redact_pii()` always returns `(text, [])` when no PII detector is configured (no-op backend or disabled rail).

Remove the `GuardrailsMetadata` import at line 473 (now at module top-level). Remove the `self._guardrails_input_executor is not None` guard and replace with `GUARDRAIL_BACKEND` truthiness checks.

- [ ] **Step 4: Run the rag chain unit tests**

```bash
python -m pytest tests/test_rag_chain_budget.py tests/test_rag_chain_integration.py -v
```

Expected: all pass.

- [ ] **Step 5: Run the full test suite**

```bash
python -m pytest tests/ -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/retrieval/rag_chain.py config/settings.py
git commit -m "refactor: rag_chain uses guardrails public API (run_input_rails/run_output_rails)"
```

---

## Task 9: Delete old top-level files, update @summary blocks and READMEs

**Files:**
- Delete: 9 old source files at `src/guardrails/` top level
- Modify: `src/guardrails/common/schemas.py` — update `@summary` Deps
- Modify: `src/guardrails/README.md` — update directory map
- Modify: `docs/retrieval/README.md` — confirm NeMo references removed
- Modify: `config/settings.py` — remove `RAG_NEMO_ENABLED`

- [ ] **Step 1: Retire RAG_NEMO_ENABLED from config/settings.py**

Delete the `RAG_NEMO_ENABLED` lines from `config/settings.py` (around line 398). Verify no remaining references:

```bash
grep -r "RAG_NEMO_ENABLED" src/ config/ tests/
```

Fix any remaining references (should be none after Task 8).

- [ ] **Step 2: Delete old top-level rail files**

```bash
git rm src/guardrails/runtime.py
git rm src/guardrails/executor.py
git rm src/guardrails/pii.py
git rm src/guardrails/gliner_pii.py
git rm src/guardrails/faithfulness.py
git rm src/guardrails/injection.py
git rm src/guardrails/toxicity.py
git rm src/guardrails/intent.py
git rm src/guardrails/topic_safety.py
```

- [ ] **Step 3: Verify full test suite still passes**

```bash
python -m pytest tests/ -v
```

Expected: all pass. This is the final confirmation that no remaining code imports from the deleted paths.

- [ ] **Step 4: Update @summary blocks**

Update the `@summary` block in `src/guardrails/__init__.py` if anything changed from what was written in Task 6.

Update `src/guardrails/common/schemas.py` — its `@summary` says `NeMo Guardrails integration`. Change to `Shared guardrails schema contracts` (the file itself is already correct; just the summary was NeMo-specific).

- [ ] **Step 5: Update READMEs**

Run `context-agent update` to regenerate affected directory READMEs:

```bash
cd /home/juansync7/RAG && context-agent update
```

If `context-agent` is not available, manually update:
- `src/guardrails/README.md` — reflect new directory structure (`shared/`, `nemo_guardrails/`, `common/`)
- `docs/retrieval/README.md` — confirm NeMo references are removed/redirected

- [ ] **Step 6: Final commit**

```bash
git add -A
git commit -m "refactor: remove old guardrails top-level files, retire RAG_NEMO_ENABLED, update docs"
```

---

## Verification Checklist

After all tasks are complete, verify:

- [ ] `python -m pytest tests/ -v` — all tests pass
- [ ] `grep -r "from src.guardrails.runtime\|from src.guardrails.executor\|from src.guardrails.injection\|from src.guardrails.toxicity\|from src.guardrails.intent\|from src.guardrails.pii\|from src.guardrails.faithfulness\|from src.guardrails.topic_safety\|from src.guardrails.gliner_pii" src/ tests/` — no results (all old import paths gone)
- [ ] `grep -r "RAG_NEMO_ENABLED" src/ config/ tests/` — no results
- [ ] `python -c "from src.guardrails import run_input_rails, run_output_rails, redact_pii, RailMergeGate; print('OK')"` — prints OK
- [ ] `ls src/guardrails/` shows only: `__init__.py backend.py common/ shared/ nemo_guardrails/`
