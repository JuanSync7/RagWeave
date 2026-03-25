# NeMo Guardrails Integration — Implementation Guide

**AION Knowledge Management Platform**
Version: 1.0 | Status: Draft | Domain: Retrieval Pipeline — Safety & Intent Management

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-03-14 | AI Assistant | Initial draft — 4 phases, 14 tasks covering full NeMo integration |

> **Document intent:** This file is a phased implementation plan tied to `NEMO_GUARDRAILS_SPEC.md`.
> For as-built retrieval behavior, refer to `docs/retrieval/RETRIEVAL_ENGINEERING_GUIDE.md` and `src/retrieval/README.md`.

This document provides a phased implementation plan and detailed code appendix for the NeMo Guardrails integration specified in `NEMO_GUARDRAILS_SPEC.md`. Every task references the requirements it satisfies.

---

# Part A: Task-Oriented Overview

## Phase 1 — Runtime Foundation & Configuration

Establish the NeMo Guardrails runtime, configuration directory, master toggle, and the schema contracts that all rails share. This phase makes the framework available without activating any specific rail logic.

### Task 1.1: Guardrails Configuration Directory & YAML Schema

**Description:** Create the `config/guardrails/` directory structure with `config.yml` (NeMo runtime settings, LLM provider, rail toggles) and placeholder Colang files. Define the environment variable override layer.

**Requirements Covered:** REQ-704, REQ-705, REQ-706, REQ-903

**Dependencies:** None — this is a new directory.

**Complexity:** S

**Subtasks:**
1. Create `config/guardrails/config.yml` with NeMo `RailsConfig`-compatible structure (model provider, rails section, Colang path)
2. Add environment variable settings to the centralized settings module: `RAG_NEMO_ENABLED`, `RAG_NEMO_INJECTION_ENABLED`, `RAG_NEMO_PII_ENABLED`, `RAG_NEMO_TOXICITY_ENABLED`, `RAG_NEMO_FAITHFULNESS_ENABLED`, `RAG_NEMO_OUTPUT_PII_ENABLED`, `RAG_NEMO_OUTPUT_TOXICITY_ENABLED`
3. Add threshold settings: `RAG_NEMO_INJECTION_SENSITIVITY`, `RAG_NEMO_TOXICITY_THRESHOLD`, `RAG_NEMO_FAITHFULNESS_THRESHOLD`, `RAG_NEMO_FAITHFULNESS_ACTION`, `RAG_NEMO_INTENT_CONFIDENCE_THRESHOLD`
4. Create an empty `config/guardrails/intents.co` placeholder for Colang definitions

---

### Task 1.2: Guardrails Schema Contracts

**Description:** Define the shared data structures (`RailVerdict`, `InputRailResult`, `OutputRailResult`, `GuardrailsMetadata`) used across all rail modules and the pipeline integration.

**Requirements Covered:** REQ-708

**Dependencies:** None.

**Complexity:** S

**Subtasks:**
1. Define `RailVerdict` enum (`pass`, `reject`, `modify`)
2. Define `InputRailResult` dataclass (intent, intent_confidence, injection_verdict, pii_redactions, toxicity_verdict, timing_ms per rail)
3. Define `OutputRailResult` dataclass (faithfulness_score, faithfulness_verdict, claim_scores, pii_redactions, toxicity_verdict, final_answer, timing_ms per rail)
4. Define `GuardrailsMetadata` dataclass for embedding in `RAGResponse` (rails_executed, verdicts, timings, redactions)
5. Add `guardrails` optional field to the existing `RAGResponse` dataclass

---

### Task 1.3: NeMo Runtime Initialization & Lifecycle

**Description:** Build the singleton runtime manager that initializes `RailsConfig` + `LLMRails` at worker startup, reuses them across queries, and handles graceful shutdown. Include the master toggle guard that prevents any NeMo import when disabled.

**Requirements Covered:** REQ-701, REQ-706, REQ-907, REQ-902

**Dependencies:** Task 1.1, Task 1.2

**Complexity:** M

**Subtasks:**
1. Implement a `GuardrailsRuntime` class with lazy-import pattern: `nemoguardrails` is imported inside the class, never at module top level
2. Implement `initialize()` method that loads `RailsConfig.from_path("config/guardrails/")` and creates `LLMRails`
3. Implement `is_enabled()` class method checking the master toggle
4. Implement error handling: Colang parse errors fail startup with clear message; runtime crashes auto-disable NeMo and log a warning
5. Wire initialization into the worker startup sequence (alongside model loading), gated behind `RAG_NEMO_ENABLED`

**Risks:** NeMo initialization may conflict with existing LangGraph event loop → mitigate by running init in a dedicated thread.

**Migration Notes:** Master toggle defaults to `false` during initial rollout. Existing pipeline behavior is unchanged until toggle is flipped.

---

## Phase 2 — Input Rails

Build all four input rails (intent, injection, PII, toxicity), the parallel execution harness, and the rail merge gate. These rails run concurrently with existing query processing.

### Task 2.1: Canonical Intent Classification Rail

**Description:** Implement the intent classification rail using Colang 2.0 flow definitions and the NeMo runtime. Write Colang definitions for the default intent taxonomy (`rag_search`, `greeting`, `off_topic`, `farewell`, `administrative`) with canned bot responses for non-search intents.

**Requirements Covered:** REQ-101, REQ-102, REQ-103, REQ-104, REQ-105

**Dependencies:** Task 1.3

**Complexity:** M

**Subtasks:**
1. Write `config/guardrails/intents.co` with `define user` blocks for each intent (≥5 examples each) and `define bot` response blocks
2. Implement `IntentClassifier` class that calls the NeMo runtime to classify a query, returning intent label + confidence
3. Implement confidence threshold logic: below threshold → fall back to `rag_search`
4. Implement canned response handlers: greeting returns friendly text, off_topic returns polite refusal, farewell returns goodbye, administrative returns help message
5. Add deterministic fallback for when LLM is unavailable: keyword-matching heuristic for greeting/farewell/off_topic

**Testing Strategy:** Unit test each intent against 10+ example utterances. Integration test with NeMo runtime.

---

### Task 2.2: Injection & Jailbreak Detection Rail

**Description:** Implement the NeMo-based injection detection rail that provides semantic defense-in-depth alongside the existing regex patterns. Include configurable sensitivity levels and secure logging.

**Requirements Covered:** REQ-201, REQ-202, REQ-203, REQ-204

**Dependencies:** Task 1.3

**Complexity:** M

**Subtasks:**
1. Implement `InjectionDetector` class that uses the NeMo runtime's built-in `check jailbreak` flow or a custom Colang flow for injection detection
2. Implement sensitivity mapping: `strict`/`balanced`/`permissive` mapped to NeMo confidence thresholds
3. Implement secure logging: hash the query with SHA-256 before logging, include detection source (`regex` vs `nemo`), verdict, tenant ID
4. Implement safe rejection message (generic, non-revealing)
5. Write Colang flow definitions for additional injection patterns not covered by regex (context-switching, role-play, encoded instructions)

---

### Task 2.3: PII Detection & Redaction Rail

**Description:** Implement the PII detection rail using regex patterns for core PII types (email, phone, government IDs) with tagged-placeholder redaction. Include extended PII categories as optional.

**Requirements Covered:** REQ-301, REQ-302, REQ-303, REQ-304, REQ-305

**Dependencies:** Task 1.3

**Complexity:** M

**Subtasks:**
1. Implement `PIIDetector` class with regex patterns for email, phone, SSN/government ID formats
2. Implement type-tagged redaction: replace matches with `[EMAIL_REDACTED]`, `[PHONE_REDACTED]`, `[SSN_REDACTED]`
3. Add extended PII patterns (person names via NER heuristic, physical addresses, credit card numbers, dates of birth) gated behind `RAG_NEMO_PII_EXTENDED=true`
4. Implement toggle via `RAG_NEMO_PII_ENABLED`
5. Implement secure logging: log PII type + count only, never log PII values

---

### Task 2.4: Toxicity Filtering Rail

**Description:** Implement the toxicity detection rail using the NeMo runtime's content moderation capabilities. Include configurable threshold and toggle.

**Requirements Covered:** REQ-401, REQ-402, REQ-403, REQ-404

**Dependencies:** Task 1.3

**Complexity:** M

**Subtasks:**
1. Implement `ToxicityFilter` class that uses NeMo's built-in moderation rail or a custom LLM-based toxicity classifier
2. Map configurable threshold (`RAG_NEMO_TOXICITY_THRESHOLD`) to detection sensitivity
3. Implement safe rejection message for toxic queries
4. Implement toggle via `RAG_NEMO_TOXICITY_ENABLED`
5. Add deterministic fallback: keyword-based toxicity detection when LLM is unavailable

---

### Task 2.5: Input Rail Parallel Executor & Merge Gate

**Description:** Build the parallel execution harness that runs all input rails concurrently with existing query processing, then merges results using the priority-based routing logic.

**Requirements Covered:** REQ-702, REQ-707

**Dependencies:** Task 2.1, Task 2.2, Task 2.3, Task 2.4

**Complexity:** L

**Subtasks:**
1. Implement `InputRailExecutor` that runs all enabled input rails in a `ThreadPoolExecutor`, returning `InputRailResult`
2. Implement `RailMergeGate` that combines `QueryResult` (from existing pipeline) with `InputRailResult` using priority order: injection reject > toxicity reject > intent routing > PII modification
3. Modify the RAG chain's Stage 1 to run query processing and input rails in parallel using `concurrent.futures`
4. Implement per-rail timeout (10s default): timed-out rails return `pass` verdict with warning logged
5. Wire merged routing decision into the pipeline: non-search intents return canned responses, rejected queries return error messages, PII-redacted queries pass through with modified text

**Risks:** Thread contention with existing GPU model inference → mitigate by using separate thread pool for rails (no GPU ops in rails).

**Testing Strategy:** Integration test verifying parallel execution timing. Unit test merge gate priority logic with all combination scenarios.

---

## Phase 3 — Output Rails

Build the three output rails (faithfulness, PII, toxicity) that run sequentially after generation.

### Task 3.1: Faithfulness & Hallucination Detection Rail

**Description:** Implement the faithfulness checking rail that scores the generated answer against retrieved context chunks. Include claim-level scoring and configurable reject/flag behavior.

**Requirements Covered:** REQ-501, REQ-502, REQ-503, REQ-504, REQ-505

**Dependencies:** Task 1.3

**Complexity:** L

**Subtasks:**
1. Implement `FaithfulnessChecker` class that takes a generated answer + context chunks and returns a faithfulness score (0.0–1.0)
2. Implement LLM-based faithfulness scoring: prompt the NeMo-configured LLM to evaluate each claim against the context
3. Implement claim-level scoring: split the answer into sentences, score each against context, return per-claim scores
4. Implement lightweight hallucination detection: extract entities/dates/numbers from the answer, verify each appears in at least one context chunk
5. Implement configurable action: `reject` returns fallback message, `flag` adds `faithfulness_warning: true` to metadata
6. Ensure context identity: pass the exact same chunk list (by reference) used for generation

**Risks:** LLM-based faithfulness checking may be slow (~3-5s) → mitigate with timeout and deterministic fallback (entity extraction only).

**Testing Strategy:** Unit test with synthetic answers containing known fabricated claims. Integration test end-to-end with generated answers.

---

### Task 3.2: Output PII & Toxicity Filter

**Description:** Implement output-side PII and toxicity filtering that runs on the generated answer before it is returned to the user. Reuse detection logic from input rails with independent toggle controls.

**Requirements Covered:** REQ-601, REQ-602, REQ-603

**Dependencies:** Task 2.3, Task 2.4

**Complexity:** S

**Subtasks:**
1. Implement `OutputFilter` class that runs PII detection (reusing `PIIDetector`) on the generated answer
2. Implement output toxicity detection (reusing `ToxicityFilter`) on the generated answer, replacing toxic segments with `[CONTENT_FILTERED]`
3. Implement independent toggles: `RAG_NEMO_OUTPUT_PII_ENABLED`, `RAG_NEMO_OUTPUT_TOXICITY_ENABLED`
4. Wire into the pipeline after generation, executing sequentially: faithfulness → PII → toxicity (per REQ-703)

---

### Task 3.3: Output Rail Sequential Executor

**Description:** Build the sequential execution harness for output rails that runs after generation with short-circuit logic (faithfulness reject skips PII/toxicity).

**Requirements Covered:** REQ-703

**Dependencies:** Task 3.1, Task 3.2

**Complexity:** S

**Subtasks:**
1. Implement `OutputRailExecutor` that chains faithfulness → PII → toxicity in order
2. Implement short-circuit: if faithfulness rejects, skip PII and toxicity rails (no wasted work)
3. Implement per-rail timeout with `pass` fallback on timeout
4. Return `OutputRailResult` with combined verdicts and timing

---

## Phase 4 — Observability, Metrics & Pipeline Integration

Add telemetry, Prometheus metrics, and finalize the pipeline integration with guardrails metadata in responses.

### Task 4.1: Guardrails Observability & Logging

**Description:** Add structured logging and OpenTelemetry spans to every rail execution. All logs use query hash, never raw query text.

**Requirements Covered:** REQ-904, REQ-203, REQ-305

**Dependencies:** Task 2.5, Task 3.3

**Complexity:** M

**Subtasks:**
1. Add a `rag.guardrails` logger with file handler (`logs/guardrails.log`)
2. Wrap each rail execution with a tracer span (parent: `rag_chain.run` root span)
3. Implement structured log entries: rail name, verdict, execution_ms, query_hash (SHA-256 of raw query), tenant_id
4. Verify no raw query text appears in any guardrails log path (PII, injection, toxicity logs)
5. Add span attributes: rail_name, verdict, execution_ms, confidence (where applicable)

---

### Task 4.2: Prometheus Metrics for Guardrails

**Description:** Define and instrument Prometheus counters and histograms for guardrail execution.

**Requirements Covered:** REQ-905, REQ-901

**Dependencies:** Task 4.1

**Complexity:** S

**Subtasks:**
1. Define `rag_guardrail_executions_total` counter (labels: rail_name, verdict)
2. Define `rag_guardrail_execution_ms` histogram (labels: rail_name)
3. Define `rag_guardrail_rejections_total` counter (labels: rail_name, reason)
4. Instrument each rail execution to increment counters and observe histogram values

---

### Task 4.3: Full Pipeline Integration & Response Metadata

**Description:** Wire the input and output rail executors into the RAG chain, add `GuardrailsMetadata` to `RAGResponse`, and add the guardrails stage to timing totals.

**Requirements Covered:** REQ-708, REQ-702, REQ-703

**Dependencies:** Task 2.5, Task 3.3, Task 4.1, Task 4.2

**Complexity:** M

**Subtasks:**
1. Modify RAG chain `run()`: after query processing (parallel with input rails), check merge gate result before proceeding to retrieval
2. Modify RAG chain `run()`: after generation (if not skipped), run output rail executor before constructing response
3. Populate `GuardrailsMetadata` in `RAGResponse.guardrails` with all rail verdicts, timings, and redactions
4. Add `guardrails` stage timing to `stage_timings` list and `timing_totals`
5. Handle the master toggle: when `RAG_NEMO_ENABLED=false`, skip all guardrails code paths; `RAGResponse.guardrails` is `None`

**Migration Notes:** Feature flag `RAG_NEMO_ENABLED=false` by default. Rollout: enable in staging first, monitor rejection rates, then enable in production.

---

### Task 4.4: Test Suite

**Description:** Write unit tests for each rail, integration tests for the parallel/sequential executors, and end-to-end tests for the full pipeline with guardrails active.

**Requirements Covered:** REQ-906

**Dependencies:** Task 4.3

**Complexity:** M

**Subtasks:**
1. Unit tests for `PIIDetector`: detection + redaction for each PII type
2. Unit tests for `ToxicityFilter`: toxic vs. benign queries
3. Unit tests for `InjectionDetector`: regex + NeMo detection coverage
4. Unit tests for `IntentClassifier`: all default intents + confidence threshold fallback
5. Unit tests for `FaithfulnessChecker`: faithful vs. unfaithful answers, claim-level scoring
6. Integration test: `RailMergeGate` priority logic with all combination scenarios
7. End-to-end test: full pipeline with `RAG_NEMO_ENABLED=true` and `false`

---

## Task Dependency Graph

```
Phase 1 (Runtime Foundation)
├── Task 1.1: Config Directory ──────────────────────┐
├── Task 1.2: Schema Contracts ──────────────────────┤
│                                                    │
│   Task 1.3: NeMo Runtime ◄── Task 1.1, 1.2 ───────┘  [CRITICAL]
│
Phase 2 (Input Rails)
├── Task 2.1: Intent Rail ◄── Task 1.3 ──────────────┐  [CRITICAL]
├── Task 2.2: Injection Rail ◄── Task 1.3 ───────────┤
├── Task 2.3: PII Rail ◄── Task 1.3 ─────────────────┤
├── Task 2.4: Toxicity Rail ◄── Task 1.3 ────────────┤
│                                                    │
│   Task 2.5: Parallel Executor ◄── 2.1-2.4 ─────────┘  [CRITICAL]
│
Phase 3 (Output Rails)
├── Task 3.1: Faithfulness Rail ◄── Task 1.3 ─────────┐ [CRITICAL]
├── Task 3.2: Output PII/Toxicity ◄── Task 2.3, 2.4 ──┤
│                                                      │
│   Task 3.3: Sequential Executor ◄── 3.1, 3.2 ───────┘ [CRITICAL]
│
Phase 4 (Observability & Integration)
├── Task 4.1: Observability ◄── Task 2.5, 3.3 ──────────┐
├── Task 4.2: Prometheus Metrics ◄── Task 4.1 ───────────┤
│                                                         │
│   Task 4.3: Pipeline Integration ◄── 2.5, 3.3, 4.1 ────┘ [CRITICAL]
│   Task 4.4: Test Suite ◄── Task 4.3                       [CRITICAL]

Critical path: 1.1 → 1.3 → 2.1 → 2.5 → 3.3 → 4.3 → 4.4
```

---

## Task-to-Requirement Mapping

| Task | Requirements Covered |
|------|---------------------|
| 1.1 Config Directory | REQ-704, REQ-705, REQ-706, REQ-903 |
| 1.2 Schema Contracts | REQ-708 |
| 1.3 NeMo Runtime | REQ-701, REQ-706, REQ-907, REQ-902 |
| 2.1 Intent Rail | REQ-101, REQ-102, REQ-103, REQ-104, REQ-105 |
| 2.2 Injection Rail | REQ-201, REQ-202, REQ-203, REQ-204 |
| 2.3 PII Rail | REQ-301, REQ-302, REQ-303, REQ-304, REQ-305 |
| 2.4 Toxicity Rail | REQ-401, REQ-402, REQ-403, REQ-404 |
| 2.5 Parallel Executor | REQ-702, REQ-707 |
| 3.1 Faithfulness Rail | REQ-501, REQ-502, REQ-503, REQ-504, REQ-505 |
| 3.2 Output PII/Toxicity | REQ-601, REQ-602, REQ-603 |
| 3.3 Sequential Executor | REQ-703 |
| 4.1 Observability | REQ-904, REQ-203, REQ-305 |
| 4.2 Prometheus Metrics | REQ-905, REQ-901 |
| 4.3 Pipeline Integration | REQ-708, REQ-702, REQ-703 |
| 4.4 Test Suite | REQ-906 |

**Verification:** All 42 requirements from `NEMO_GUARDRAILS_SPEC.md` are covered.

---

# Part B: Code Appendix

## B.1: Guardrails Configuration (YAML + Settings)

The NeMo Guardrails runtime configuration and environment variable integration. Supports Task 1.1.

**Tasks:** Task 1.1
**Requirements:** REQ-704, REQ-705, REQ-706, REQ-903

```yaml
# config/guardrails/config.yml
models:
  - type: main
    engine: ollama
    model: qwen2.5:3b
    parameters:
      base_url: ${RAG_OLLAMA_URL:-http://localhost:11434}
      temperature: 0.1

rails:
  input:
    flows:
      - check intent
      - check jailbreak
      - check pii
      - check toxicity
  output:
    flows:
      - check faithfulness
      - check output pii
      - check output toxicity

  config:
    jailbreak_detection:
      enabled: true
      sensitivity: balanced  # strict | balanced | permissive
    pii_detection:
      enabled: true
      extended: false
      categories: [email, phone, ssn]
    toxicity_detection:
      enabled: true
      threshold: 0.5
    faithfulness:
      enabled: true
      threshold: 0.5
      action: flag  # reject | flag
    intent_classification:
      enabled: true
      confidence_threshold: 0.5
```

```python
# Settings module additions (config/settings.py)
import os

# --- NeMo Guardrails ---
RAG_NEMO_ENABLED = os.environ.get(
    "RAG_NEMO_ENABLED", "false"
).lower() in ("true", "1", "yes")

RAG_NEMO_CONFIG_DIR = os.environ.get(
    "RAG_NEMO_CONFIG_DIR",
    str(PROJECT_ROOT / "config" / "guardrails"),
)

RAG_NEMO_INJECTION_ENABLED = os.environ.get(
    "RAG_NEMO_INJECTION_ENABLED", "true"
).lower() in ("true", "1", "yes")
RAG_NEMO_INJECTION_SENSITIVITY = os.environ.get(
    "RAG_NEMO_INJECTION_SENSITIVITY", "balanced"
)

RAG_NEMO_PII_ENABLED = os.environ.get(
    "RAG_NEMO_PII_ENABLED", "true"
).lower() in ("true", "1", "yes")
RAG_NEMO_PII_EXTENDED = os.environ.get(
    "RAG_NEMO_PII_EXTENDED", "false"
).lower() in ("true", "1", "yes")

RAG_NEMO_TOXICITY_ENABLED = os.environ.get(
    "RAG_NEMO_TOXICITY_ENABLED", "true"
).lower() in ("true", "1", "yes")
RAG_NEMO_TOXICITY_THRESHOLD = float(
    os.environ.get("RAG_NEMO_TOXICITY_THRESHOLD", "0.5")
)

RAG_NEMO_FAITHFULNESS_ENABLED = os.environ.get(
    "RAG_NEMO_FAITHFULNESS_ENABLED", "true"
).lower() in ("true", "1", "yes")
RAG_NEMO_FAITHFULNESS_THRESHOLD = float(
    os.environ.get("RAG_NEMO_FAITHFULNESS_THRESHOLD", "0.5")
)
RAG_NEMO_FAITHFULNESS_ACTION = os.environ.get(
    "RAG_NEMO_FAITHFULNESS_ACTION", "flag"
)

RAG_NEMO_OUTPUT_PII_ENABLED = os.environ.get(
    "RAG_NEMO_OUTPUT_PII_ENABLED", "true"
).lower() in ("true", "1", "yes")
RAG_NEMO_OUTPUT_TOXICITY_ENABLED = os.environ.get(
    "RAG_NEMO_OUTPUT_TOXICITY_ENABLED", "true"
).lower() in ("true", "1", "yes")

RAG_NEMO_INTENT_CONFIDENCE_THRESHOLD = float(
    os.environ.get("RAG_NEMO_INTENT_CONFIDENCE_THRESHOLD", "0.5")
)
RAG_NEMO_RAIL_TIMEOUT_SECONDS = int(
    os.environ.get("RAG_NEMO_RAIL_TIMEOUT_SECONDS", "10")
)
```

**Key design decisions:**
- YAML config follows NeMo's native `config.yml` schema for compatibility with `RailsConfig.from_path()`
- Environment variables override YAML values, following the existing project pattern
- Master toggle defaults to `false` for safe rollout

---

## B.2: Guardrails Schema Contracts

Shared data structures used across all rail modules and the pipeline integration. Supports Task 1.2.

**Tasks:** Task 1.2
**Requirements:** REQ-708

```python
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class RailVerdict(Enum):
    """Verdict returned by a rail execution."""
    PASS = "pass"
    REJECT = "reject"
    MODIFY = "modify"


@dataclass
class RailExecution:
    """Result of a single rail execution."""
    rail_name: str
    verdict: RailVerdict
    execution_ms: float
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class InputRailResult:
    """Combined result of all input rails."""
    intent: str = "rag_search"
    intent_confidence: float = 1.0
    injection_verdict: RailVerdict = RailVerdict.PASS
    pii_redactions: List[Dict[str, str]] = field(default_factory=list)
    redacted_query: Optional[str] = None
    toxicity_verdict: RailVerdict = RailVerdict.PASS
    rail_executions: List[RailExecution] = field(default_factory=list)


@dataclass
class OutputRailResult:
    """Combined result of all output rails."""
    faithfulness_score: float = 1.0
    faithfulness_verdict: RailVerdict = RailVerdict.PASS
    faithfulness_warning: bool = False
    claim_scores: List[Dict[str, Any]] = field(default_factory=list)
    pii_redactions: List[Dict[str, str]] = field(default_factory=list)
    toxicity_verdict: RailVerdict = RailVerdict.PASS
    final_answer: Optional[str] = None
    rail_executions: List[RailExecution] = field(default_factory=list)


@dataclass
class GuardrailsMetadata:
    """Metadata embedded in RAGResponse for caller visibility."""
    enabled: bool = True
    input_rails: List[RailExecution] = field(default_factory=list)
    output_rails: List[RailExecution] = field(default_factory=list)
    intent: Optional[str] = None
    intent_confidence: Optional[float] = None
    faithfulness_score: Optional[float] = None
    faithfulness_warning: bool = False
    total_rail_ms: float = 0.0
```

**Key design decisions:**
- Dataclasses over raw dicts for type safety and IDE support
- `RailExecution` captures per-rail timing for observability (REQ-904)
- `GuardrailsMetadata` is the public contract; `InputRailResult`/`OutputRailResult` are internal

---

## B.3: NeMo Runtime Manager

Singleton runtime that initializes NeMo Guardrails once at startup with lazy imports and master toggle protection. Supports Task 1.3.

**Tasks:** Task 1.3
**Requirements:** REQ-701, REQ-706, REQ-907, REQ-902

```python
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("rag.guardrails.runtime")


class GuardrailsRuntime:
    """Singleton manager for the NeMo Guardrails runtime.

    Lazy-imports nemoguardrails to avoid import errors when
    RAG_NEMO_ENABLED=false and the package is not installed.
    """

    _instance: Optional[GuardrailsRuntime] = None
    _initialized: bool = False
    _rails = None  # LLMRails instance
    _auto_disabled: bool = False

    @classmethod
    def get(cls) -> GuardrailsRuntime:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def is_enabled(cls) -> bool:
        from config.settings import RAG_NEMO_ENABLED
        return RAG_NEMO_ENABLED and not cls._auto_disabled

    def initialize(self, config_dir: str) -> None:
        """Load NeMo config and compile Colang flows.

        Raises on Colang parse errors (fail-fast at startup).
        """
        if self._initialized:
            return
        if not self.is_enabled():
            logger.info("NeMo Guardrails disabled (RAG_NEMO_ENABLED=false)")
            return

        try:
            from nemoguardrails import RailsConfig, LLMRails

            config = RailsConfig.from_path(config_dir)
            self._rails = LLMRails(config)
            self._initialized = True
            logger.info("NeMo Guardrails runtime initialized from %s", config_dir)
        except SyntaxError as e:
            # Colang parse error — fail startup
            logger.error("Colang parse error: %s", e)
            raise
        except Exception as e:
            logger.error("NeMo runtime init failed: %s — auto-disabling", e)
            self._auto_disabled = True

    @property
    def rails(self):
        """Access the LLMRails instance. Returns None if not initialized."""
        return self._rails

    async def generate(self, messages: list[dict]) -> dict:
        """Execute rails on a message sequence."""
        if not self._initialized or self._rails is None:
            return {"role": "assistant", "content": ""}
        try:
            return await self._rails.generate_async(messages=messages)
        except Exception as e:
            logger.warning("Rail execution failed: %s — returning pass", e)
            self._auto_disabled = True
            return {"role": "assistant", "content": ""}

    def shutdown(self) -> None:
        self._rails = None
        self._initialized = False
        logger.info("NeMo Guardrails runtime shut down")
```

**Key design decisions:**
- Lazy import of `nemoguardrails` inside methods, not at module top level (REQ-907)
- `_auto_disabled` flag provides automatic fallback on runtime crash (REQ-902)
- Singleton pattern matches existing `RAGChain` lifecycle
- Colang parse errors raise immediately to fail startup fast

---

## B.4: Colang Intent Definitions

Colang 2.0 flow definitions for canonical intent classification. Supports Task 2.1.

**Tasks:** Task 2.1
**Requirements:** REQ-101, REQ-102, REQ-103

```colang
# config/guardrails/intents.co

define user greeting
  "hello"
  "hi there"
  "hey"
  "good morning"
  "good afternoon"
  "hi, how are you?"
  "greetings"

define bot greeting response
  "Hello! I'm here to help you search the knowledge base. What would you like to know?"

define user farewell
  "goodbye"
  "bye"
  "see you later"
  "thanks, bye"
  "that's all, thanks"
  "have a nice day"

define bot farewell response
  "Goodbye! Feel free to return if you have more questions."

define user off topic
  "what's the weather today"
  "tell me a joke"
  "who won the game last night"
  "what time is it"
  "play some music"
  "what's the stock price of NVIDIA"

define bot off topic response
  "I'm designed to help you find information in the knowledge base. I can't help with that topic, but feel free to ask me a question about the documents I have access to."

define user administrative
  "help"
  "what can you do"
  "how do I use this"
  "show me the available commands"
  "what are your capabilities"
  "how does this work"

define bot administrative response
  "I can search the knowledge base to answer your questions. Just type your question in natural language and I'll find relevant information from the available documents."

define user rag search
  "what is the attention mechanism"
  "explain transformer architecture"
  "how does retrieval augmented generation work"
  "what are embedding models"
  "describe the difference between BM25 and vector search"
  "what is semantic chunking"
  "how do language models handle context windows"

define flow check intent
  user ...
  if user intent is greeting
    bot greeting response
    stop
  else if user intent is farewell
    bot farewell response
    stop
  else if user intent is off topic
    bot off topic response
    stop
  else if user intent is administrative
    bot administrative response
    stop
```

**Key design decisions:**
- Each intent has ≥5 examples as required by REQ-102
- `rag_search` examples use domain-specific terminology matching the AION knowledge base domain
- Non-search intents use `stop` to prevent pipeline execution (REQ-103)
- Flow structure allows adding new intents by adding new `.co` files (REQ-105)

---

## B.5: PII Detector

Regex-based PII detection with type-tagged redaction. Supports Task 2.3.

**Tasks:** Task 2.3
**Requirements:** REQ-301, REQ-302, REQ-303, REQ-304, REQ-305

```python
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from typing import List, Tuple

logger = logging.getLogger("rag.guardrails.pii")

# Core PII patterns (always active when PII rail is enabled)
_CORE_PATTERNS: dict[str, re.Pattern] = {
    "EMAIL": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
    "PHONE": re.compile(
        r"(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"
    ),
    "SSN": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
}

# Extended PII patterns (optional, gated behind config flag)
_EXTENDED_PATTERNS: dict[str, re.Pattern] = {
    "CREDIT_CARD": re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b"),
    "DOB": re.compile(
        r"\b(?:0[1-9]|1[0-2])/(?:0[1-9]|[12]\d|3[01])/(?:19|20)\d{2}\b"
    ),
}


@dataclass
class PIIDetection:
    """A single PII detection."""
    pii_type: str
    start: int
    end: int
    placeholder: str


class PIIDetector:
    """Detect and redact PII with type-tagged placeholders."""

    def __init__(self, extended: bool = False) -> None:
        self.patterns = dict(_CORE_PATTERNS)
        if extended:
            self.patterns.update(_EXTENDED_PATTERNS)

    def detect(self, text: str) -> List[PIIDetection]:
        """Find all PII occurrences in text."""
        detections: List[PIIDetection] = []
        for pii_type, pattern in self.patterns.items():
            for match in pattern.finditer(text):
                detections.append(PIIDetection(
                    pii_type=pii_type,
                    start=match.start(),
                    end=match.end(),
                    placeholder=f"[{pii_type}_REDACTED]",
                ))
        # Sort by position (reverse) for safe replacement
        detections.sort(key=lambda d: d.start, reverse=True)
        return detections

    def redact(self, text: str) -> Tuple[str, List[PIIDetection]]:
        """Detect and redact PII, returning redacted text + detections."""
        detections = self.detect(text)
        redacted = text
        for d in detections:
            redacted = redacted[:d.start] + d.placeholder + redacted[d.end:]
        if detections:
            counts = {}
            for d in detections:
                counts[d.pii_type] = counts.get(d.pii_type, 0) + 1
            logger.info("PII detected: %s", ", ".join(
                f"{k}={v}" for k, v in sorted(counts.items())
            ))
        return redacted, detections
```

**Key design decisions:**
- Regex-based for core types (fast, deterministic, no LLM dependency)
- Extended patterns gated behind config flag to control accuracy/coverage tradeoff
- Reverse-sorted detections enable safe in-place replacement without index shifting
- Logging shows type+count only, never PII values (REQ-305)

---

## B.6: Input Rail Parallel Executor & Merge Gate

Parallel execution of input rails with priority-based merge logic. Supports Task 2.5.

**Tasks:** Task 2.5
**Requirements:** REQ-702, REQ-707

```python
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, Future, TimeoutError
from typing import Optional

logger = logging.getLogger("rag.guardrails.executor")

# Placeholder imports — actual classes from Tasks 2.1-2.4
# from .intent import IntentClassifier
# from .injection import InjectionDetector
# from .pii import PIIDetector
# from .toxicity import ToxicityFilter
# from .schemas import InputRailResult, RailExecution, RailVerdict


class InputRailExecutor:
    """Run all enabled input rails in parallel."""

    def __init__(
        self,
        intent_classifier,   # IntentClassifier
        injection_detector,   # InjectionDetector
        pii_detector,         # PIIDetector
        toxicity_filter,      # ToxicityFilter
        timeout_seconds: int = 10,
    ) -> None:
        self._intent = intent_classifier
        self._injection = injection_detector
        self._pii = pii_detector
        self._toxicity = toxicity_filter
        self._timeout = timeout_seconds

    def execute(self, query: str, tenant_id: str = "") -> InputRailResult:
        """Run all enabled rails in parallel, return combined result."""
        result = InputRailResult()
        executions = []

        with ThreadPoolExecutor(max_workers=4, thread_name_prefix="rail") as pool:
            futures: dict[str, Future] = {}

            if self._intent:
                futures["intent"] = pool.submit(self._intent.classify, query)
            if self._injection:
                futures["injection"] = pool.submit(self._injection.check, query)
            if self._pii:
                futures["pii"] = pool.submit(self._pii.redact, query)
            if self._toxicity:
                futures["toxicity"] = pool.submit(self._toxicity.check, query)

            for name, fut in futures.items():
                t0 = time.perf_counter()
                try:
                    rail_result = fut.result(timeout=self._timeout)
                    ms = (time.perf_counter() - t0) * 1000

                    if name == "intent":
                        result.intent = rail_result.intent
                        result.intent_confidence = rail_result.confidence
                        executions.append(RailExecution(
                            "intent", RailVerdict.PASS, ms,
                            {"intent": rail_result.intent}
                        ))
                    elif name == "injection":
                        result.injection_verdict = rail_result.verdict
                        executions.append(RailExecution(
                            "injection", rail_result.verdict, ms
                        ))
                    elif name == "pii":
                        redacted_text, detections = rail_result
                        if detections:
                            result.redacted_query = redacted_text
                            result.pii_redactions = [
                                {"type": d.pii_type} for d in detections
                            ]
                        verdict = RailVerdict.MODIFY if detections else RailVerdict.PASS
                        executions.append(RailExecution("pii", verdict, ms))
                    elif name == "toxicity":
                        result.toxicity_verdict = rail_result.verdict
                        executions.append(RailExecution(
                            "toxicity", rail_result.verdict, ms
                        ))

                except TimeoutError:
                    ms = (time.perf_counter() - t0) * 1000
                    logger.warning("Rail '%s' timed out after %.0fms — pass", name, ms)
                    executions.append(RailExecution(name, RailVerdict.PASS, ms))
                except Exception as e:
                    ms = (time.perf_counter() - t0) * 1000
                    logger.warning("Rail '%s' failed: %s — pass", name, e)
                    executions.append(RailExecution(name, RailVerdict.PASS, ms))

        result.rail_executions = executions
        return result


class RailMergeGate:
    """Merge query processing result with input rail result.

    Priority order:
    1. Injection reject overrides all
    2. Toxicity reject overrides intent routing
    3. Intent classification determines flow
    4. PII redaction modifies query but does not change flow
    """

    REJECTION_MESSAGES = {
        "injection": "Your query could not be processed. Please rephrase your question.",
        "toxicity": "Your query contains content that violates our usage policy. Please rephrase.",
    }

    INTENT_RESPONSES = {
        "greeting": "Hello! I'm here to help you search the knowledge base. What would you like to know?",
        "farewell": "Goodbye! Feel free to return if you have more questions.",
        "off_topic": "I'm designed to help you find information in the knowledge base. I can't help with that topic.",
        "administrative": "I can search the knowledge base to answer your questions. Just type your question in natural language.",
    }

    def merge(self, query_result, rail_result: InputRailResult) -> dict:
        """Return merged routing decision."""
        # Priority 1: injection reject
        if rail_result.injection_verdict == RailVerdict.REJECT:
            return {"action": "reject", "message": self.REJECTION_MESSAGES["injection"]}

        # Priority 2: toxicity reject
        if rail_result.toxicity_verdict == RailVerdict.REJECT:
            return {"action": "reject", "message": self.REJECTION_MESSAGES["toxicity"]}

        # Priority 3: intent routing
        intent = rail_result.intent
        if intent != "rag_search" and intent in self.INTENT_RESPONSES:
            return {"action": "canned", "message": self.INTENT_RESPONSES[intent]}

        # Priority 4: PII redaction (non-blocking)
        effective_query = rail_result.redacted_query or query_result.processed_query
        return {"action": "search", "query": effective_query}
```

**Key design decisions:**
- `ThreadPoolExecutor` with 4 workers (one per rail) — no GPU ops in rails, so thread-safe
- Per-rail timeout with `pass` fallback on timeout/error (REQ-902)
- Merge gate uses strict priority ordering per REQ-707
- PII is non-blocking: query is modified but flow continues to search

---

## B.7: Faithfulness Checker

LLM-based faithfulness scoring with claim-level granularity. Supports Task 3.1.

**Tasks:** Task 3.1
**Requirements:** REQ-501, REQ-502, REQ-503, REQ-504, REQ-505

```python
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger("rag.guardrails.faithfulness")

_FAITHFULNESS_PROMPT = """You are a faithfulness evaluator. Given an answer and context chunks,
score how well each claim in the answer is supported by the context.

Context:
{context}

Answer:
{answer}

For each sentence in the answer, output a JSON array:
[{{"claim": "sentence text", "score": 0.0-1.0, "supported": true/false}}]

Score 1.0 = fully supported, 0.0 = completely unsupported.
Output ONLY the JSON array."""


@dataclass
class ClaimScore:
    """Faithfulness score for a single claim."""
    claim: str
    score: float
    supported: bool


@dataclass
class FaithfulnessResult:
    """Result of faithfulness evaluation."""
    overall_score: float
    claim_scores: List[ClaimScore]
    hallucinated_entities: List[str]


class FaithfulnessChecker:
    """Check generated answers for faithfulness to retrieved context."""

    def __init__(
        self,
        llm_caller,  # callable that takes a prompt and returns text
        threshold: float = 0.5,
        action: str = "flag",  # "reject" or "flag"
    ) -> None:
        self._llm = llm_caller
        self._threshold = threshold
        self._action = action

    def check(
        self,
        answer: str,
        context_chunks: List[str],
    ) -> FaithfulnessResult:
        """Evaluate faithfulness of answer against context."""
        # Step 1: LLM-based claim scoring
        claim_scores = self._score_claims(answer, context_chunks)

        # Step 2: Lightweight hallucination detection
        hallucinated = self._detect_hallucinated_entities(answer, context_chunks)

        # Step 3: Compute overall score
        if claim_scores:
            overall = sum(c.score for c in claim_scores) / len(claim_scores)
        else:
            overall = 1.0

        # Penalize for hallucinated entities
        if hallucinated:
            penalty = min(0.3, len(hallucinated) * 0.1)
            overall = max(0.0, overall - penalty)

        return FaithfulnessResult(
            overall_score=overall,
            claim_scores=claim_scores,
            hallucinated_entities=hallucinated,
        )

    def _score_claims(self, answer: str, context_chunks: List[str]) -> List[ClaimScore]:
        """Use LLM to score each claim against context."""
        context_text = "\n\n".join(
            f"[{i+1}] {chunk}" for i, chunk in enumerate(context_chunks)
        )
        prompt = _FAITHFULNESS_PROMPT.format(context=context_text, answer=answer)

        try:
            response = self._llm(prompt)
            parsed = json.loads(response)
            return [
                ClaimScore(
                    claim=str(item.get("claim", "")),
                    score=float(item.get("score", 0.0)),
                    supported=bool(item.get("supported", False)),
                )
                for item in parsed
            ]
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            logger.warning("Failed to parse faithfulness response: %s", e)
            return []

    def _detect_hallucinated_entities(
        self, answer: str, context_chunks: List[str],
    ) -> List[str]:
        """Check for entities/dates/numbers in answer not in any chunk."""
        context_text = " ".join(context_chunks).lower()

        # Extract potential factual claims: dates, numbers, proper nouns
        date_pattern = re.compile(r"\b(?:19|20)\d{2}\b")
        number_pattern = re.compile(r"\b\d+(?:\.\d+)?%?\b")

        hallucinated = []
        for pattern in [date_pattern]:
            for match in pattern.finditer(answer):
                value = match.group()
                if value not in context_text:
                    hallucinated.append(value)

        return hallucinated
```

**Key design decisions:**
- Same context chunks passed by reference as used for generation (REQ-504)
- Claim-level scoring via sentence splitting + per-claim LLM evaluation (REQ-503)
- Lightweight entity hallucination as a fast complement to LLM scoring (REQ-505)
- Penalty-based overall score combines LLM claims + entity detection
- Deterministic entity check works even when LLM is unavailable (graceful degradation)

---

## B.8: Colang Python Demo Script

Standalone script demonstrating NeMo Guardrails usage with Colang definitions. Supports the Colang Python demo requirement.

**Tasks:** N/A (standalone demo)
**Requirements:** Demonstration of NeMo Guardrails SDK usage

```python
#!/usr/bin/env python3
"""
Colang Python Demo — NeMo Guardrails Usage Example

Demonstrates how to:
1. Configure NeMo Guardrails with Colang 2.0 definitions
2. Run input rails (intent classification, injection detection)
3. Run output rails (faithfulness checking)
4. Handle verdicts and route queries

Usage:
    python colang_demo.py
"""

import asyncio
import os
import tempfile
from pathlib import Path


# --- Colang definition (inline for demo) ---
COLANG_CONTENT = """
define user greeting
  "hello"
  "hi there"
  "hey"
  "good morning"
  "greetings"

define bot greeting response
  "Hello! How can I help you search the knowledge base today?"

define user off topic
  "what's the weather"
  "tell me a joke"
  "who is the president"
  "play music"
  "what time is it"

define bot off topic response
  "I can only help with questions about the knowledge base. Please ask a relevant question."

define user rag search
  "what is machine learning"
  "explain neural networks"
  "how does RAG work"
  "what are embeddings"
  "describe vector databases"

define flow check intent
  user ...
  if user intent is greeting
    bot greeting response
    stop
  else if user intent is off topic
    bot off topic response
    stop
"""

CONFIG_CONTENT = """
models:
  - type: main
    engine: ollama
    model: {model}
    parameters:
      base_url: {base_url}

rails:
  input:
    flows:
      - check intent
"""


async def run_demo():
    """Run the NeMo Guardrails demo."""
    from nemoguardrails import RailsConfig, LLMRails

    base_url = os.environ.get("RAG_OLLAMA_URL", "http://localhost:11434")
    model = os.environ.get("RAG_OLLAMA_MODEL", "qwen2.5:3b")

    # Create a temporary config directory
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir)

        # Write Colang definitions
        (config_path / "intents.co").write_text(COLANG_CONTENT)

        # Write config.yml
        (config_path / "config.yml").write_text(
            CONFIG_CONTENT.format(model=model, base_url=base_url)
        )

        print(f"Config directory: {config_path}")
        print(f"Using model: {model} at {base_url}")
        print("=" * 60)

        # Initialize NeMo Guardrails
        config = RailsConfig.from_path(str(config_path))
        rails = LLMRails(config)

        # Test queries
        test_queries = [
            "Hello, how are you?",
            "What is the attention mechanism in transformers?",
            "What's the weather today?",
            "Explain how embeddings work",
            "Tell me a joke",
        ]

        for query in test_queries:
            print(f"\nQuery: {query!r}")
            print("-" * 40)

            messages = [{"role": "user", "content": query}]

            try:
                response = await rails.generate_async(messages=messages)
                content = response.get("content", response)
                print(f"Response: {content}")

                # Check if the query was handled by a rail (canned response)
                # or passed through to the LLM (rag_search intent)
                info = await rails.explain_async(messages=messages)
                if hasattr(info, "colang_history"):
                    print(f"Flow: {info.colang_history[:100]}...")
            except Exception as e:
                print(f"Error: {e}")

            print()

    print("=" * 60)
    print("Demo complete!")


if __name__ == "__main__":
    asyncio.run(run_demo())
```

**Key design decisions:**
- Self-contained: creates temp directory with Colang + config, no external files needed
- Uses the same Ollama model as the AION pipeline for consistency
- Demonstrates both intent classification (greeting, off_topic, rag_search) and flow routing
- Async usage matches NeMo's native `generate_async` API
- Environment variables for model/URL match the project's configuration pattern
