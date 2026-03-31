# Retrieval Generation Pipeline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.
> This plan has six phases: Phase 0 (contracts), Phase A (spec tests), Phase B (implementation),
> Phase C (engineering guide), Phase D (white-box tests), Phase E (full suite).
> Invoke `write-engineering-guide` skill for Phase C. Invoke `write-module-tests` skill for Phase D.

**Goal:** Implement the retrieval generation pipeline's post-generation guardrails, confidence scoring, routing, formatting, and observability features specified in `RETRIEVAL_GENERATION_SPEC.md` (REQ-501–REQ-903).

**Architecture:** 8-stage retrieval pipeline (query processing → pre-retrieval guardrail → retrieval → reranking → document formatting → generation → post-generation guardrail → answer delivery) with LangGraph orchestration, 3-signal confidence routing, persistent conversation memory, and comprehensive observability.

**Tech Stack:** Python, LangGraph (orchestration), Weaviate (vector DB), BGE-M3 (embeddings), BGE-Reranker-v2-m3 (reranking), LiteLLM (LLM abstraction), Temporal (durable execution), FastAPI (server)

| Field | Value |
|-------|-------|
| **Spec Reference** | `RETRIEVAL_GENERATION_SPEC.md` v1.2 (REQ-501–REQ-903) |
| **Design Reference** | `RETRIEVAL_GENERATION_DESIGN.md` v1.2 |
| **Created** | 2026-03-23 |
| **Split From** | `RETRIEVAL_IMPLEMENTATION.md` — generation-side tasks only |

---

## File Structure

### Contracts (Phase 0)

- `src/retrieval/guardrails/__init__.py` — CREATE
- `src/retrieval/guardrails/types.py` — CREATE (PostGuardrailAction, PostGuardrailResult) — GENERATION types only
- `src/retrieval/confidence/__init__.py` — CREATE
- `src/retrieval/confidence/types.py` — CREATE (ConfidenceBreakdown)
- `src/retrieval/confidence/scoring.py` — CREATE (pure utility functions — fully implemented)
- `src/retrieval/formatting/__init__.py` — CREATE
- `src/retrieval/formatting/types.py` — CREATE (VersionConflict, detect/format functions — fully implemented)
- `src/retrieval/observability/__init__.py` — CREATE
- `src/retrieval/observability/types.py` — CREATE (StageMetrics, QueryTrace, traced decorator)
- `src/retrieval/pipeline_state.py` — CREATE (RAGPipelineState TypedDict)
- `src/retrieval/retry.py` — CREATE (with_retry decorator — fully implemented)
- `config/guardrails.yaml` — CREATE (risk taxonomy, injection patterns, parameter ranges) — GENERATION portion

### Source (Phase B — stubs become implementations)

- `src/retrieval/guardrails/post_generation.py` — CREATE (PostGenerationGuardrail class)
- `src/retrieval/confidence/engine.py` — CREATE (confidence routing logic)
- `src/retrieval/formatting/formatter.py` — CREATE (format_retrieved_docs)
- `src/retrieval/formatting/conflicts.py` — CREATE (version conflict detection integration)
- `src/retrieval/prompt_loader.py` — CREATE (PromptTemplate integration)
- `src/retrieval/observability/tracing.py` — CREATE (instrumentation wiring)
- `src/retrieval/pipeline.py` — MODIFY (full LangGraph pipeline wiring)

### Tests (Phase A)

- `tests/retrieval/test_post_generation_guardrail.py` — CREATE
- `tests/retrieval/test_retry_logic.py` — CREATE
- `tests/retrieval/test_confidence_scoring.py` — CREATE
- `tests/retrieval/test_pipeline_routing.py` — CREATE
- `tests/retrieval/test_document_formatter.py` — CREATE
- `tests/retrieval/test_version_conflicts.py` — CREATE
- `tests/retrieval/test_prompt_template.py` — CREATE
- `tests/retrieval/test_observability.py` — CREATE

---

## Dependency Graph

```
Phase 0 (Contracts)
├── Task 0.1: Guardrail Types + Config (GENERATION types) ──────────────┐
├── Task 0.2: Confidence Types + Scoring (pure utils) ──────────────────┤
├── Task 0.3: Pipeline State + Retry (pure utils) ──────────────────────┤
└── Task 0.4: Formatting Types + Observability Types ───────────────────┤
                                                                        │
═══════════════════════ [REVIEW GATE] ══════════════════════════════════╡
                                                                        │
Phase A (Tests — ALL PARALLEL)                                          │
├── A-1.2: Post-Generation Guardrail ◄── Phase 0 ──────────────────────┤
├── A-1.3: Retry Logic ◄── Phase 0 ────────────────────────────────────┤
├── A-2.1: Confidence Scoring ◄── Phase 0 ──────────────────────────────┤
├── A-2.2: Pipeline Routing ◄── Phase 0 ───────────────────────────────┤
├── A-3.1: Document Formatter ◄── Phase 0 ──────────────────────────────┤
├── A-3.2: Version Conflicts ◄── Phase 0 ──────────────────────────────┤
├── A-3.3: Prompt Template ◄── Phase 0 ────────────────────────────────┤
└── A-4.4: Observability ◄── Phase 0 ──────────────────────────────────┘

Phase B (Implementation — dependency-ordered)

Independent start (no Phase B dependencies):
├── B-1.3: Retry Logic
├── B-3.1: Document Formatter
├── B-3.3: Prompt Template

After B-1.3:
├── B-2.1: Confidence Scoring ◄── B-1.3

After B-2.1:
├── B-1.2: Post-Generation Guardrail ◄── B-2.1, B-2.3 [QUERY — see RETRIEVAL_QUERY_IMPLEMENTATION.md]         [CRITICAL]

After B-3.1:
├── B-3.2: Version Conflicts ◄── B-3.1

After all pipeline stages:
├── B-4.4: Observability ◄── all pipeline stages

After B-1.1 [QUERY — see RETRIEVAL_QUERY_IMPLEMENTATION.md], B-1.2, B-2.1:
└── B-2.2: Pipeline Routing ◄── B-1.1 [QUERY — see RETRIEVAL_QUERY_IMPLEMENTATION.md], B-1.2, B-2.1          [CRITICAL]

Critical path: B-1.3 → B-2.1 → B-1.2 → B-2.2

Phase 6 (Memory-Aware Generation Routing — REQ-1201/1203/1204/1205/1207/1209)

Phase 0 prerequisite:
└── Task 0.5: RAGResponse extension (generation_source field)

Phase A (Tests — ALL PARALLEL):
├── A-6.1: Fallback Retrieval Routing ◄── Phase 0 (Task 0.5)
├── A-6.2: Memory-Generation Path ◄── Phase 0 (Task 0.5)
├── A-6.3: Suppress-Memory Routing ◄── Phase 0 (Task 0.5)
├── A-6.4: BLOCK/FLAG Memory Filtering ◄── Phase 0 (Task 0.5)
└── A-6.5: Generation Source Tracking ◄── Phase 0 (Task 0.5)

Phase B (Implementation — dependency-ordered):
├── B-6.1: Fallback Retrieval Routing ◄── Query Task 7.1 (standalone_query schema)
├── B-6.3: Suppress-Memory Routing ◄── Query Task 7.3 (suppress_memory detection)
├── B-6.2: Memory-Generation Path ◄── B-6.1
├── B-6.5: Generation Source Tracking ◄── B-6.1, B-6.2, B-6.3
└── B-6.4: BLOCK/FLAG Caller Contract ◄── (no pipeline deps — documentation only)
```

---

## Task-to-Requirement Mapping

| Task | Phase 0 Contracts | Phase A Test File | Phase B Source File | Phase C Module Doc | Phase D Test File | Requirements |
|------|-------------------|-------------------|---------------------|--------------------|-------------------|-------------|
| 1.2 Post-Generation Guardrail | `guardrails/types.py`, `confidence/types.py` | `test_post_generation_guardrail.py` | `guardrails/post_generation.py` | `docs/tmp/module-post-generation-guardrail.md` | `tests/retrieval/test_post_generation_guardrail_coverage.py` | REQ-701–REQ-706 |
| 1.3 Retry Logic | `retry.py` | `test_retry_logic.py` | `retry.py` (already implemented in Phase 0) | `docs/tmp/module-retry.md` | `tests/retrieval/test_retry_logic_coverage.py` | REQ-605, REQ-902 |
| 2.1 Confidence Scoring | `confidence/types.py`, `confidence/scoring.py` | `test_confidence_scoring.py` | `confidence/engine.py` | `docs/tmp/module-confidence-engine.md` | `tests/retrieval/test_confidence_scoring_coverage.py` | REQ-701, REQ-604 |
| 2.2 Pipeline Routing | `pipeline_state.py` | `test_pipeline_routing.py` | `pipeline.py` | `docs/tmp/module-pipeline.md` | `tests/retrieval/test_pipeline_routing_coverage.py` | REQ-706, REQ-902 |
| 3.1 Document Formatter | `formatting/types.py` | `test_document_formatter.py` | `formatting/formatter.py` | `docs/tmp/module-document-formatter.md` | `tests/retrieval/test_document_formatter_coverage.py` | REQ-501, REQ-503 |
| 3.2 Version Conflicts | `formatting/types.py` | `test_version_conflicts.py` | `formatting/conflicts.py` | `docs/tmp/module-version-conflicts.md` | `tests/retrieval/test_version_conflicts_coverage.py` | REQ-502 |
| 3.3 Prompt Template | — | `test_prompt_template.py` | `prompt_loader.py` | `docs/tmp/module-prompt-loader.md` | `tests/retrieval/test_prompt_template_coverage.py` | REQ-601, REQ-602 |
| 4.4 Observability | `observability/types.py` | `test_observability.py` | `observability/tracing.py` | `docs/tmp/module-observability.md` | `tests/retrieval/test_observability_coverage.py` | REQ-801, REQ-802, REQ-803 |
| 6.1 Fallback Retrieval Routing | Task 0.5 (`RAGResponse`) | `test_fallback_retrieval_routing.py` | `pipeline/rag_chain.py` | — | — | REQ-1201 |
| 6.2 Memory-Generation Path | Task 0.5 (`RAGResponse`) | `test_memory_generation_path.py` | `pipeline/rag_chain.py` | — | — | REQ-1203, REQ-1204 |
| 6.3 Suppress-Memory Routing | Task 0.5 (`RAGResponse`) | `test_suppress_memory_routing.py` | `pipeline/rag_chain.py` | — | — | REQ-1205 |
| 6.4 BLOCK/FLAG Memory Filtering | Task 0.5 (caller contract) | `test_block_flag_memory_filtering.py` | Caller code (CLI/API) | — | — | REQ-1207 |
| 6.5 Generation Source Tracking | Task 0.5 (`RAGResponse.generation_source`) | `test_generation_source_tracking.py` | `common/schemas.py`, `pipeline/rag_chain.py` | — | — | REQ-1209 |

---

# Phase 0 — Contract Definitions

Phase 0 creates the shared type surface that both test agents (Phase A) and implementation agents (Phase B) work against. All code below is complete and copy-pasteable.

**REVIEW GATE:** Phase 0 must be human-reviewed before Phase A begins.

---

## Task 0.1: Guardrail Types and Config (GENERATION contracts only)

- [ ] Create `src/retrieval/guardrails/__init__.py`
- [ ] Create `src/retrieval/guardrails/types.py` with the following content (GENERATION types only):

```python
"""Guardrail type contracts for pre-retrieval and post-generation stages.

Design doc: RETRIEVAL_GENERATION_DESIGN.md B.4
Spec: REQ-201–REQ-205 (pre-retrieval), REQ-701–REQ-706 (post-generation)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
```

> **Cross-module dependency:** `RiskLevel`, `GuardrailAction`, `GuardrailResult`, and `validate_query()` are defined in
> `RETRIEVAL_QUERY_IMPLEMENTATION.md` Phase 0, Task 0.1. These types are in the **same** `src/retrieval/guardrails/types.py`
> file. Implement QUERY Task 0.1 before this task. The `PostGuardrailResult.risk_level` field and `evaluate_answer()` parameter
> reference `RiskLevel` from the QUERY-side contract of this same file.

```python
class PostGuardrailAction(Enum):
    """Post-generation guardrail routing action (REQ-706)."""
    RETURN = "return"            # Confidence OK — deliver answer to user
    RE_RETRIEVE = "re_retrieve"  # Low confidence — retry with broader params (max 1 retry)
    FLAG = "flag"                # Escalate to human review
    BLOCK = "block"              # Do not return answer — "Insufficient documentation"


@dataclass
class PostGuardrailResult:
    """Result from post-generation guardrail evaluation (REQ-701–REQ-706).

    Fields:
        action: routing decision based on confidence + risk.
        answer: the (possibly redacted/sanitized) answer text.
        confidence: full confidence breakdown from 3-signal scoring.
        risk_level: query risk level from pre-retrieval stage.
        pii_redactions: PII entries redacted from the answer (REQ-703).
        hallucination_flags: sentences not grounded in sources (REQ-702).
        verification_warning: warning text for HIGH risk answers (REQ-705).
    """
    action: PostGuardrailAction                      # REQ-706
    answer: str                                      # REQ-704 (sanitized)
    confidence: "ConfidenceBreakdown"                # REQ-701
    risk_level: "RiskLevel"                          # REQ-203
    pii_redactions: list[dict] = field(default_factory=list)      # REQ-703
    hallucination_flags: list[str] = field(default_factory=list)  # REQ-702
    verification_warning: Optional[str] = None       # REQ-705


# Stub for post-generation guardrail (implementation in Phase B-1.2)
def evaluate_answer(
    answer: str,
    confidence: "ConfidenceBreakdown",
    risk_level: "RiskLevel",
    retrieved_docs: list[dict],
    retry_count: int = 0,
) -> PostGuardrailResult:
    """Run post-generation evaluation: PII, sanitize, hallucination, routing.

    Args:
        answer: raw generated answer text.
        confidence: pre-computed 3-signal confidence breakdown.
        risk_level: query risk from pre-retrieval stage.
        retrieved_docs: list of retrieved document dicts with 'text' and 'metadata'.
        retry_count: how many re-retrieval attempts have been made (max 1).

    Returns:
        PostGuardrailResult with routing action, cleaned answer, flags.

    Raises:
        Nothing — returns structured result, never raises.
    """
    raise NotImplementedError("Task B-1.2")
```

- [ ] Create `config/guardrails.yaml` with the following content (GENERATION portion):

```yaml
# Guardrail configuration — loaded at startup (REQ-903)
# Changes take effect on restart without code changes.
# GENERATION keys only. QUERY keys (injection_patterns, risk_taxonomy, parameter_ranges, etc.) are defined in RETRIEVAL_QUERY_IMPLEMENTATION.md Phase 0 Task 0.1.

post_generation:            # REQ-706
  high_confidence_threshold: 0.70
  low_confidence_threshold: 0.50
  system_prompt_path: "prompts/rag_system.md"
```

- [ ] Verify both files are syntactically valid

---

## Task 0.2: Confidence Types and Scoring (Pure Utilities)

- [ ] Create `src/retrieval/confidence/__init__.py`
- [ ] Create `src/retrieval/confidence/types.py`:

```python
"""Confidence scoring type contracts.

Design doc: RETRIEVAL_GENERATION_DESIGN.md B.3
Spec: REQ-701, REQ-604
"""
from dataclasses import dataclass


@dataclass
class ConfidenceBreakdown:
    """3-signal composite confidence score (REQ-701).

    Fields:
        retrieval_score: average of top-N reranker scores (objective signal).
        llm_score: LLM self-reported confidence mapped to 0-1 (subjective signal).
        citation_score: fraction of answer sentences grounded in sources (structural signal).
        composite: weighted combination of all three signals.
        retrieval_weight: weight for retrieval signal (default 0.50).
        llm_weight: weight for LLM signal (default 0.25).
        citation_weight: weight for citation signal (default 0.25).
    """
    retrieval_score: float       # REQ-701 — from reranker (objective)
    llm_score: float             # REQ-604 — from LLM self-report (subjective)
    citation_score: float        # REQ-701 — from citation coverage (structural)
    composite: float             # REQ-701 — weighted combination
    retrieval_weight: float      # Configurable (REQ-903)
    llm_weight: float            # Configurable (REQ-903)
    citation_weight: float       # Configurable (REQ-903)
```

- [ ] Create `src/retrieval/confidence/scoring.py` (fully implemented — pure utility):

```python
"""Pure scoring functions for 3-signal confidence computation.

These are deterministic, side-effect-free utilities. Fully implemented in Phase 0
because they carry no bias risk.

Design doc: RETRIEVAL_GENERATION_DESIGN.md B.3
Spec: REQ-701, REQ-604
"""
from __future__ import annotations

import re
from src.retrieval.confidence.types import ConfidenceBreakdown


# Downward correction map for LLM overconfidence (REQ-604)
# LLMs tend to report "high" even when uncertain. These corrections
# are calibrated to produce useful composite scores.
LLM_CONFIDENCE_MAP: dict[str, float] = {
    "high": 0.85,      # Not 1.0 — LLMs systematically overestimate
    "medium": 0.55,    # Not 0.6 — slight downward correction
    "low": 0.25,       # Not 0.3 — slight downward correction
}
LLM_CONFIDENCE_DEFAULT = 0.5  # When parsing fails


def compute_retrieval_confidence(reranker_scores: list[float], top_n: int = 3) -> float:
    """Average of top-N reranker scores. Objective signal (REQ-701).

    Args:
        reranker_scores: list of reranker scores (0.0-1.0 range after sigmoid).
        top_n: how many top scores to average (default 3).

    Returns:
        Average score, or 0.0 if no scores provided.

    Edge cases:
        - Empty list → returns 0.0 (no retrieval = no confidence).
        - Fewer than top_n scores → averages all available scores.
    """
    if not reranker_scores:
        return 0.0
    scores = sorted(reranker_scores, reverse=True)[:top_n]
    return sum(scores) / len(scores)


def parse_llm_confidence(llm_confidence_text: str) -> float:
    """Map LLM self-reported confidence to numerical score with downward correction (REQ-604).

    Args:
        llm_confidence_text: "high", "medium", or "low" (case-insensitive).

    Returns:
        Corrected numerical score. Defaults to 0.5 on unknown input.

    Edge cases:
        - Empty string → returns 0.5 (neutral default).
        - Unknown value like "UNKNOWN" or "maybe" → returns 0.5.
        - Leading/trailing whitespace → stripped before matching.
    """
    if not llm_confidence_text or not llm_confidence_text.strip():
        return LLM_CONFIDENCE_DEFAULT
    return LLM_CONFIDENCE_MAP.get(llm_confidence_text.strip().lower(), LLM_CONFIDENCE_DEFAULT)


def compute_citation_coverage(answer: str, retrieved_quotes: list[str]) -> float:
    """Fraction of answer sentences grounded in retrieved content (REQ-701).

    A sentence is "grounded" if it shares a substantial n-gram overlap with
    any retrieved document text. Very short sentences (< 10 chars, e.g., "Yes.")
    are auto-counted as covered since they typically don't carry factual claims.

    Args:
        answer: the generated answer text.
        retrieved_quotes: list of retrieved document text strings.

    Returns:
        Coverage ratio (0.0 to 1.0).

    Edge cases:
        - Empty answer → returns 0.0.
        - Answer with only short sentences → returns 1.0 (all auto-covered).
        - Empty retrieved_quotes → returns 0.0 for all non-trivial sentences.
    """
    sentences = _split_sentences(answer)
    if not sentences:
        return 0.0

    covered = 0
    for sentence in sentences:
        sentence_lower = sentence.lower().strip()
        if len(sentence_lower) < 10:
            covered += 1
            continue
        for quote in retrieved_quotes:
            if _has_substantial_overlap(sentence_lower, quote.lower()):
                covered += 1
                break

    return covered / len(sentences)


def compute_composite_confidence(
    reranker_scores: list[float],
    llm_confidence_text: str,
    answer: str,
    retrieved_quotes: list[str],
    retrieval_weight: float = 0.50,
    llm_weight: float = 0.25,
    citation_weight: float = 0.25,
) -> ConfidenceBreakdown:
    """Compute composite confidence from 3 independent signals (REQ-701).

    Args:
        reranker_scores: reranker scores for retrieved docs.
        llm_confidence_text: LLM self-reported confidence string.
        answer: the generated answer text.
        retrieved_quotes: text content of retrieved documents.
        retrieval_weight: weight for retrieval signal.
        llm_weight: weight for LLM signal.
        citation_weight: weight for citation signal.

    Returns:
        ConfidenceBreakdown with all three signals and composite score.

    Edge cases:
        - All weights = 0 → composite = 0.0.
        - Weights don't sum to 1.0 → still works (no normalization enforced).
    """
    retrieval = compute_retrieval_confidence(reranker_scores)
    llm = parse_llm_confidence(llm_confidence_text)
    citation = compute_citation_coverage(answer, retrieved_quotes)

    composite = (
        retrieval * retrieval_weight
        + llm * llm_weight
        + citation * citation_weight
    )

    return ConfidenceBreakdown(
        retrieval_score=round(retrieval, 3),
        llm_score=round(llm, 3),
        citation_score=round(citation, 3),
        composite=round(composite, 3),
        retrieval_weight=retrieval_weight,
        llm_weight=llm_weight,
        citation_weight=citation_weight,
    )


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences. Basic regex splitter.

    For production, consider spaCy or nltk for better accuracy with
    abbreviations (e.g., "Dr. Smith" should not split at the period).
    """
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    return [s for s in sentences if s.strip()]


def _has_substantial_overlap(sentence: str, quote: str, threshold: int = 5) -> bool:
    """Check if sentence shares at least `threshold` consecutive words with a quote.

    This is a simple n-gram overlap check. For production, consider
    semantic similarity (embedding cosine) for better recall.
    """
    sentence_words = sentence.split()
    if len(sentence_words) < threshold:
        return False
    quote_joined = " ".join(quote.split())
    for i in range(len(sentence_words) - threshold + 1):
        ngram = " ".join(sentence_words[i : i + threshold])
        if ngram in quote_joined:
            return True
    return False
```

- [ ] Verify imports resolve and no circular dependencies

---

## Task 0.3: Pipeline State and Retry

- [ ] Create `src/retrieval/pipeline_state.py`:

```python
"""Full-pipeline LangGraph state schema.

Design doc: RETRIEVAL_GENERATION_DESIGN.md B.12
Spec: REQ-706, REQ-902
"""
from typing import Optional, TypedDict


class RAGPipelineState(TypedDict, total=False):
    """Shared state flowing through the full retrieval pipeline.

    Each pipeline stage reads from and writes to this state dict.
    Fields are populated incrementally as stages execute.
    TypedDict with total=False allows stages to populate only their fields.
    """
    # --- Input ---
    question: str                              # Raw user query
    conversation_history: list[dict]           # Recent turns for context
    conversation_id: str                       # Memory conversation ID (REQ-1006)
    memory_enabled: bool                       # Per-request memory toggle (REQ-1005)
    memory_turn_window: int                    # Per-request window override (REQ-1005)

    # --- Query Processing (REQ-101, REQ-102, REQ-104) ---
    processed_query: str                       # Reformulated query
    query_confidence: float                    # 0.0-1.0 confidence score
    query_action: str                          # "search" or "ask_user"
    clarification_message: Optional[str]       # Message when action=ask_user

    # --- Pre-Retrieval Guardrail (REQ-201–REQ-205) ---
    risk_level: str                            # "HIGH", "MEDIUM", "LOW" (REQ-203)
    sanitized_query: str                       # After optional PII redaction (REQ-204)
    guardrail_passed: bool                     # True if validation passed (REQ-205)

    # --- Retrieval (REQ-301–REQ-308) ---
    retrieved_docs: list[dict]                 # Raw search results
    kg_expanded_terms: list[str]               # KG expansion terms (REQ-304)
    search_alpha: float                        # Current alpha (may change on retry)
    search_limit: int                          # Current limit (may increase on retry)

    # --- Reranking (REQ-401–REQ-403) ---
    ranked_docs: list[dict]                    # After cross-encoder reranking
    reranker_scores: list[float]               # Sigmoid-normalized scores

    # --- Document Formatting (REQ-501–REQ-503) ---
    formatted_context: str                     # Context string for LLM injection
    version_conflicts: list[dict]              # Detected version conflicts (REQ-502)

    # --- Generation (REQ-601–REQ-605) ---
    answer: str                                # Raw LLM answer
    llm_confidence: str                        # "high", "medium", "low" (REQ-604)

    # --- Post-Generation Guardrail (REQ-701–REQ-706) ---
    composite_confidence: float                # 3-signal composite (REQ-701)
    confidence_breakdown: dict                 # Full breakdown for logging
    post_guardrail_action: str                 # "return"/"re_retrieve"/"flag"/"block"
    final_answer: str                          # After PII redaction + sanitization
    verification_warning: Optional[str]        # For HIGH risk answers (REQ-705)

    # --- Control ---
    retry_count: int                           # Re-retrieval count (max 1, REQ-706)
    trace_id: str                              # Unique trace ID (REQ-801)
```

- [ ] Create `src/retrieval/retry.py` (fully implemented — pure utility):

```python
"""Retry decorator with exponential backoff and optional fallback.

Design doc: RETRIEVAL_GENERATION_DESIGN.md B.7
Spec: REQ-605 (retry for LLM calls), REQ-902 (graceful degradation)
"""
import logging
import time
from functools import wraps
from typing import Callable, Optional, TypeVar

logger = logging.getLogger(__name__)
T = TypeVar("T")


def with_retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    backoff_factor: float = 2.0,
    fallback: Optional[Callable[..., T]] = None,
    exceptions: tuple = (Exception,),
) -> Callable:
    """Decorator: retry with exponential backoff. Falls back if all retries fail.

    Args:
        max_retries: maximum number of retry attempts (not counting the first call).
        base_delay: initial delay in seconds between retries.
        max_delay: maximum delay cap in seconds.
        backoff_factor: multiplier for delay between retries.
        fallback: optional function to call when all retries are exhausted.
            Receives the same args/kwargs as the original function.
        exceptions: tuple of exception types to catch and retry on.

    Usage:
        @with_retry(max_retries=3, fallback=heuristic_confidence)
        def evaluate_confidence(query: str) -> float:
            return call_llm(query)

    Edge cases:
        - max_retries=0 → function is called once, no retries.
        - fallback=None and all retries fail → re-raises the last exception.
        - backoff_factor=1.0 → constant delay (no exponential growth).
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_exception = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        delay = min(
                            base_delay * (backoff_factor ** attempt),
                            max_delay,
                        )
                        logger.warning(
                            "%s attempt %d/%d failed: %s. Retrying in %.1fs...",
                            func.__name__,
                            attempt + 1,
                            max_retries + 1,
                            e,
                            delay,
                        )
                        time.sleep(delay)
                    else:
                        logger.error(
                            "%s exhausted all %d attempts. Last error: %s",
                            func.__name__,
                            max_retries + 1,
                            e,
                        )

            if fallback is not None:
                logger.info("%s using fallback.", func.__name__)
                return fallback(*args, **kwargs)
            raise last_exception  # type: ignore[misc]

        return wrapper
    return decorator
```

- [ ] Verify both files parse without errors

---

## Task 0.4: Formatting Types and Observability Types

- [ ] Create `src/retrieval/formatting/__init__.py`
- [ ] Create `src/retrieval/formatting/types.py` (fully implemented — pure utility):

```python
"""Version conflict detection and formatting utilities.

Design doc: RETRIEVAL_GENERATION_DESIGN.md B.5
Spec: REQ-502 (version conflict detection)
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class VersionConflict:
    """A detected version conflict between two retrieved documents (REQ-502)."""
    spec_identifier: str    # Spec ID or filename stem
    version_a: str
    date_a: str
    version_b: str
    date_b: str


def detect_version_conflicts(documents: list[dict]) -> list[VersionConflict]:
    """Detect when retrieved docs share a spec ID / filename stem but differ in version.

    Args:
        documents: list of dicts with 'metadata' containing 'spec_id', 'filename',
                   'version', and 'date' fields.

    Returns:
        List of VersionConflict objects. Empty list if no conflicts.

    Edge cases:
        - Document with no spec_id AND no filename → skipped (no key to group by).
        - Two documents same spec_id same version → no conflict reported.
        - Three documents, two different versions of same spec → one conflict reported.
        - Missing 'version' field → treated as "unknown".
    """
    version_map: dict[str, dict] = {}
    conflicts: list[VersionConflict] = []

    for doc in documents:
        metadata = doc.get("metadata", {})
        key = metadata.get("spec_id") or _extract_filename_stem(
            metadata.get("filename", "")
        )
        if not key:
            continue

        version = metadata.get("version", "unknown")
        date = metadata.get("date", "unknown")

        if key in version_map:
            existing = version_map[key]
            if existing["version"] != version:
                conflicts.append(VersionConflict(
                    spec_identifier=key,
                    version_a=existing["version"],
                    date_a=existing["date"],
                    version_b=version,
                    date_b=date,
                ))
        else:
            version_map[key] = {"version": version, "date": date}

    return conflicts


def format_conflict_warning(conflicts: list[VersionConflict]) -> str:
    """Format conflicts for injection into LLM context (REQ-502).

    Returns empty string if no conflicts. Otherwise returns a multi-line
    warning block that instructs the LLM to acknowledge the conflict.
    """
    if not conflicts:
        return ""

    lines = ["WARNING — Version conflicts detected in retrieved documents:"]
    for c in conflicts:
        lines.append(
            f"  - {c.spec_identifier}: {c.version_a} ({c.date_a}) vs "
            f"{c.version_b} ({c.date_b})"
        )
    lines.append(
        "You MUST note this conflict in your answer. "
        "Do NOT silently choose one version over another."
    )
    return "\n".join(lines)


def _extract_filename_stem(filename: str) -> Optional[str]:
    """Extract base name without version suffix.

    Examples:
        'Power_Spec_v3.pdf' → 'Power_Spec'
        'Timing_rev2.1.pdf' → 'Timing'
        '' → None
    """
    if not filename:
        return None
    name = re.sub(r'\.[^.]+$', '', filename)
    name = re.sub(r'[_-]?v\d+(\.\d+)?$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'[_-]?rev\d+(\.\d+)?$', '', name, flags=re.IGNORECASE)
    return name if name else None
```

- [ ] Create `src/retrieval/observability/__init__.py`
- [ ] Create `src/retrieval/observability/types.py`:

```python
"""Observability type contracts and trace decorators.

Design doc: RETRIEVAL_GENERATION_DESIGN.md B.13
Spec: REQ-801 (tracing), REQ-802 (per-stage metrics)
"""
from __future__ import annotations

import logging
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Context variable for async-safe trace propagation
_current_trace: ContextVar["QueryTrace | None"] = ContextVar(
    "_current_trace", default=None
)


@dataclass
class StageMetrics:
    """Metrics captured for a single pipeline stage (REQ-802)."""
    stage_name: str
    latency_ms: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class QueryTrace:
    """End-to-end trace for a single query (REQ-801).

    Contains a unique trace_id, risk_level, and ordered list of stage metrics.
    """
    trace_id: str
    risk_level: str
    stages: list[StageMetrics] = field(default_factory=list)
    total_latency_ms: float = 0.0

    def add_stage(self, stage: StageMetrics) -> None:
        self.stages.append(stage)
        self.total_latency_ms = sum(s.latency_ms for s in self.stages)


def start_trace(risk_level: str = "LOW") -> QueryTrace:
    """Start a new query trace. Sets the trace in context for downstream stages."""
    trace = QueryTrace(
        trace_id=str(uuid.uuid4()),
        risk_level=risk_level,
    )
    _current_trace.set(trace)
    return trace


def get_current_trace() -> QueryTrace | None:
    """Get the current trace from context. Returns None if no trace is active."""
    return _current_trace.get()


def traced(stage_name: str) -> Callable:
    """Decorator to capture timing and metadata for a pipeline stage (REQ-802).

    Automatically records latency and extracts scalar metadata from the
    return value (if it's a dict). Logs with trace_id for correlation.

    Usage:
        @traced("retrieval")
        def retrieve_node(state):
            results = hybrid_search(...)
            return {"retrieved_docs": results, "result_count": len(results)}
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            start = time.perf_counter()
            result = func(*args, **kwargs)
            elapsed_ms = (time.perf_counter() - start) * 1000

            trace = get_current_trace()
            if trace:
                metadata: dict[str, Any] = {}
                if isinstance(result, dict):
                    metadata = {
                        k: v for k, v in result.items()
                        if isinstance(v, (int, float, str, bool))
                    }
                trace.add_stage(StageMetrics(
                    stage_name=stage_name,
                    latency_ms=round(elapsed_ms, 2),
                    metadata=metadata,
                ))
                logger.info(
                    "[%s] %s: %.1fms",
                    trace.trace_id,
                    stage_name,
                    elapsed_ms,
                    extra={"trace_id": trace.trace_id, "stage": stage_name},
                )

            return result
        return wrapper
    return decorator
```

- [ ] Verify imports resolve

---

## Task 0.5: Memory-Aware Generation Routing Types

### Phase 0 Contract: RAGResponse Extension (REQ-1209)

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.platform.token_budget.schemas import TokenBudgetSnapshot


@dataclass
class RAGResponse:
    """Complete response from the retrieval pipeline.

    Extended with generation_source for conversational routing (REQ-1209).
    """
    query: str
    processed_query: str
    query_confidence: float
    action: str
    results: List["RankedResult"] = field(default_factory=list)
    clarification_message: Optional[str] = None
    kg_expanded_terms: Optional[List[str]] = None
    generated_answer: Optional[str] = None
    stage_timings: List[Dict[str, Any]] = field(default_factory=list)
    timing_totals: Dict[str, float] = field(default_factory=dict)
    budget_exhausted: bool = False
    budget_exhausted_stage: Optional[str] = None
    conversation_id: Optional[str] = None
    guardrails: Optional[Dict[str, Any]] = None
    token_budget: Optional["TokenBudgetSnapshot"] = None
    composite_confidence: Optional[float] = None
    confidence_breakdown: Optional[Dict[str, Any]] = None
    post_guardrail_action: Optional[str] = None
    version_conflicts: Optional[List[Dict[str, Any]]] = None
    retry_count: int = 0
    verification_warning: Optional[str] = None
    retrieval_quality: Optional[str] = None
    retrieval_quality_note: Optional[str] = None
    re_retrieval_suggested: bool = False
    re_retrieval_params: Optional[Dict[str, Any]] = None
    generation_source: Optional[str] = None       # "retrieval" | "memory" | "retrieval+memory" | None (REQ-1209)
```

### Integration Contracts (additions)

```
rag_chain.run()
    → QueryResult.suppress_memory → determines retrieval path
    → QueryResult.standalone_query → fallback retrieval query
    → QueryResult.has_backward_reference → memory-generation path trigger

    Routing decision:
        suppress_memory=True → standalone retrieval only, no memory in generation
        retrieval strong/moderate → standard generation (docs ± memory)
        retrieval weak + backward_ref + non-empty memory → memory-generation
        retrieval weak + no backward_ref → BLOCK/FLAG (existing behavior)

    → RAGResponse.generation_source set based on which path
    → Caller checks post_guardrail_action before append_turn() (REQ-1207)
```

- [ ] Verify all Phase 0 files import correctly:
```bash
cd /home/juansync7/RAG && python -c "
from src.retrieval.guardrails.types import PostGuardrailAction, PostGuardrailResult
from src.retrieval.confidence.types import ConfidenceBreakdown
from src.retrieval.confidence.scoring import compute_composite_confidence
from src.retrieval.formatting.types import VersionConflict, detect_version_conflicts
from src.retrieval.observability.types import QueryTrace, StageMetrics, traced
from src.retrieval.pipeline_state import RAGPipelineState
from src.retrieval.retry import with_retry
print('All Phase 0 GENERATION contracts import successfully')
"
```

---

**REVIEW GATE: Human must review all Phase 0 contracts before proceeding to Phase A.**

---

# Phase A — Tests (Isolated from Implementation)

**Agent isolation contract:** The test agent receives ONLY:
1. The spec requirements (REQ numbers + acceptance criteria)
2. The contract files from Phase 0 (TypedDicts, signatures, exceptions)
3. The task description from the design document

**Must NOT receive:** Any implementation code, any pattern entries from the
design doc's code appendix, any source files beyond Phase 0 stubs.

**All Phase A tasks can run in parallel.**

---

## Task A-1.2: Post-Generation Guardrail Tests

**Agent input (ONLY these):**
- REQ-701 (3-signal composite confidence)
- REQ-702 (hallucination detection — grounding check)
- REQ-703 (PII redaction from answer)
- REQ-704 (output sanitization — system prompt leaks, artifacts)
- REQ-705 (HIGH risk numerical claim verification)
- REQ-706 (confidence routing: return/re-retrieve/flag/block)
- Phase 0 contracts: `src/retrieval/guardrails/types.py`, `src/retrieval/confidence/types.py`

**Must NOT receive:** `src/retrieval/guardrails/post_generation.py`, any Design Doc B.4 code

**Files → Create:** `tests/retrieval/test_post_generation_guardrail.py`

**Test cases:**

PII redaction (REQ-703):
- [ ] Answer with email "Contact john@corp.com" → "Contact [EMAIL]"
- [ ] Answer with phone "Call 555-123-4567" → "Call [PHONE]"
- [ ] Answer with multiple PII types → all replaced
- [ ] Answer with no PII → unchanged
- [ ] Redaction always runs (not conditional like pre-retrieval)

Output sanitization (REQ-704):
- [ ] Answer containing system prompt fragment → fragment removed
- [ ] Answer containing "--- Document 3 ---" marker → marker stripped
- [ ] Answer containing template artifact "{documents}" → removed
- [ ] Clean answer → unchanged

Hallucination detection (REQ-702):
- [ ] Answer where all sentences match source docs → no flags
- [ ] Answer where one sentence has no match → that sentence flagged
- [ ] Answer with all ungrounded sentences → all flagged
- [ ] Short sentence "Yes." (< 10 chars) → skipped, not flagged
- [ ] Empty answer → no flags (no sentences to check)

HIGH risk filtering (REQ-705):
- [ ] HIGH risk answer "The voltage is 3.3V" where docs don't contain "3.3V" → value flagged
- [ ] HIGH risk answer with value that IS in source docs → no flag
- [ ] LOW risk answer with unverified value → no extra flag (LOW risk = no numerical check)
- [ ] Verification warning text includes "VERIFY BEFORE IMPLEMENTATION"

Confidence routing (REQ-706):
- [ ] composite=0.80, risk=LOW → RETURN
- [ ] composite=0.80, risk=HIGH → RETURN (with verification_warning attached)
- [ ] composite=0.60, retry_count=0 → RE_RETRIEVE
- [ ] composite=0.60, retry_count=1 → FLAG (already retried once)
- [ ] composite=0.40, retry_count=0 → RE_RETRIEVE
- [ ] composite=0.40, retry_count=1 → BLOCK
- [ ] composite exactly at 0.70 → RETURN (threshold is > 0.70, test boundary)
- [ ] composite exactly at 0.50 → RE_RETRIEVE (threshold is 0.50-0.70 range)
- [ ] FLAG action → verification_warning text is appended to generated_answer as "\n\n---\n⚠️ <warning>" (Stage 7.5 behavior — warning visible in answer text, not only in structured field)

Memory echo suppression (rag_chain.py Stage 6):
- [ ] retrieval_quality="strong" → recent_turns passed to generator unchanged
- [ ] retrieval_quality="moderate" → recent_turns passed to generator unchanged
- [ ] retrieval_quality="weak" → recent_turns suppressed (None) before generate() call
- [ ] retrieval_quality="insufficient" → recent_turns suppressed (None) before generate() call
- [ ] memory_context (rolling summary) always passed regardless of retrieval_quality

```bash
cd /home/juansync7/RAG && python -m pytest tests/retrieval/test_post_generation_guardrail.py -v
# Expected: ALL FAIL (no implementation yet)
```

---

## Task A-1.3: Retry Logic Tests

**Agent input (ONLY these):**
- REQ-605 (retry with exponential backoff for LLM calls)
- REQ-902 (graceful fallback when retries exhausted)
- Phase 0 contracts: `src/retrieval/retry.py`

**Must NOT receive:** any implementation code beyond `retry.py`

**Files → Create:** `tests/retrieval/test_retry_logic.py`

**Test cases:**

Happy path:
- [ ] Function succeeds on first try → returns immediately, no retries (REQ-605)
- [ ] Function fails once then succeeds → retries once and returns (REQ-605)

Retry behavior:
- [ ] Function fails all attempts (max_retries=2) → fallback called (REQ-902)
- [ ] Function fails all attempts, no fallback → last exception re-raised
- [ ] Backoff delay grows: attempt 0 → base_delay, attempt 1 → base_delay * factor (REQ-605)
- [ ] Backoff caps at max_delay when base_delay * factor^n > max_delay
- [ ] max_retries=0 → function called once, no retry on failure

Edge cases:
- [ ] Only specified exception types are caught (e.g., TimeoutError but not ValueError)
- [ ] Fallback receives same args/kwargs as original function
- [ ] Decorated function preserves __name__ and __doc__ (functools.wraps)

```bash
cd /home/juansync7/RAG && python -m pytest tests/retrieval/test_retry_logic.py -v
# Expected: ALL PASS (retry.py is fully implemented in Phase 0)
```

---

## Task A-2.1: Confidence Scoring Tests

**Agent input (ONLY these):**
- REQ-701 (3-signal composite: retrieval 0.50, LLM 0.25, citation 0.25)
- REQ-604 (LLM confidence extraction with downward correction)
- Phase 0 contracts: `src/retrieval/confidence/types.py`, `src/retrieval/confidence/scoring.py`

**Must NOT receive:** `src/retrieval/confidence/engine.py`, any Design Doc B.3 code beyond Phase 0

**Files → Create:** `tests/retrieval/test_confidence_scoring.py`

**Test cases:**

Retrieval confidence (REQ-701):
- [ ] Empty reranker_scores list → 0.0
- [ ] Single score [0.8] → 0.8 (average of 1 item)
- [ ] Three scores [0.9, 0.7, 0.5] → average of top-3 = 0.7
- [ ] Five scores, top_n=3 → only top 3 averaged
- [ ] All scores 0.0 → 0.0

LLM confidence parsing (REQ-604):
- [ ] "high" → 0.85 (not 1.0 — downward correction)
- [ ] "medium" → 0.55
- [ ] "low" → 0.25
- [ ] "HIGH" (uppercase) → 0.85 (case insensitive)
- [ ] "  high  " (whitespace) → 0.85 (trimmed)
- [ ] "" (empty) → 0.5 (neutral default)
- [ ] "UNKNOWN" → 0.5 (default for unrecognized)
- [ ] None-like empty string → 0.5

Citation coverage (REQ-701):
- [ ] Empty answer → 0.0
- [ ] All sentences grounded in retrieved docs → 1.0
- [ ] No sentences grounded → 0.0 (only non-trivial sentences counted)
- [ ] Short sentence "Yes." (< 10 chars) → auto-covered
- [ ] Mixed grounded/ungrounded → correct fraction
- [ ] Empty retrieved_quotes with non-trivial answer → 0.0

Composite (REQ-701):
- [ ] Default weights (0.50, 0.25, 0.25) produce expected composite
- [ ] Custom weights produce different composite
- [ ] All signals 0.0 → composite 0.0
- [ ] All signals 1.0 → composite = sum of weights
- [ ] Returned ConfidenceBreakdown has all fields populated and rounded to 3 decimals

```bash
cd /home/juansync7/RAG && python -m pytest tests/retrieval/test_confidence_scoring.py -v
# Expected: ALL PASS (scoring.py is fully implemented in Phase 0)
```

---

## Task A-2.2: Pipeline Routing Tests

**Agent input (ONLY these):**
- REQ-706 (confidence routing: return/re-retrieve/flag/block)
- REQ-902 (graceful degradation)
- Phase 0 contracts: `src/retrieval/pipeline_state.py`

**Must NOT receive:** `src/retrieval/pipeline.py`, any Design Doc B.12 code

**Files → Create:** `tests/retrieval/test_pipeline_routing.py`

**Test cases:**

Query action routing:
- [ ] query_action="ask_user" → pipeline skips to ask_user, returns clarification (REQ-102)
- [ ] query_action="search" → pipeline proceeds to pre-retrieval guardrail

Guardrail routing:
- [ ] guardrail_passed=False → pipeline skips to block_answer (REQ-205)
- [ ] guardrail_passed=True → pipeline proceeds to retrieval

Post-guardrail routing (REQ-706):
- [ ] post_guardrail_action="return" → deliver answer to user
- [ ] post_guardrail_action="re_retrieve" with retry_count=0 → loop back to retrieve with broader params
- [ ] Re-retrieval increases search_limit and shifts alpha toward BM25 (REQ-706)
- [ ] post_guardrail_action="re_retrieve" with retry_count=1 → escalate (no infinite loop)
- [ ] post_guardrail_action="block" → "Insufficient documentation found" message
- [ ] post_guardrail_action="flag" → escalation to review queue; verification_warning text appended to generated_answer as visible block

Graceful degradation (REQ-902):
- [ ] Generation unavailable → return retrieved docs without synthesis
- [ ] Query processing LLM unavailable → use heuristic confidence
- [ ] KG unavailable → skip expansion, proceed normally

```bash
cd /home/juansync7/RAG && python -m pytest tests/retrieval/test_pipeline_routing.py -v
# Expected: ALL FAIL (no implementation yet)
```

---

## Task A-3.1: Document Formatter Tests

**Agent input (ONLY these):**
- REQ-501 (structured metadata: filename, version, date, domain, section, spec_id)
- REQ-503 (deterministic formatting, sequential numbering)
- Phase 0 contracts: `src/retrieval/formatting/types.py`

**Must NOT receive:** `src/retrieval/formatting/formatter.py`, Design Doc B.6 code

**Files → Create:** `tests/retrieval/test_document_formatter.py`

**Test cases:**
- [ ] Single doc with all metadata fields → formatted with all fields visible (REQ-501)
- [ ] Doc with missing metadata fields → "unknown" defaults (REQ-501)
- [ ] Two docs → numbered sequentially "Document 1", "Document 2" (REQ-503)
- [ ] Same input twice → identical output (deterministic) (REQ-503)
- [ ] Doc with no metadata at all → all fields show "unknown"
- [ ] Empty document list → empty formatted string
- [ ] Version conflicts present → conflict warning prepended to output

```bash
cd /home/juansync7/RAG && python -m pytest tests/retrieval/test_document_formatter.py -v
# Expected: ALL FAIL (no implementation yet)
```

---

## Task A-3.2: Version Conflict Tests

**Agent input (ONLY these):**
- REQ-502 (detect and surface version conflicts)
- Phase 0 contracts: `src/retrieval/formatting/types.py` (detect_version_conflicts, format_conflict_warning)

**Must NOT receive:** `src/retrieval/formatting/conflicts.py`

**Files → Create:** `tests/retrieval/test_version_conflicts.py`

**Test cases:**
- [ ] Two docs same spec_id different versions → one VersionConflict returned (REQ-502)
- [ ] Two docs same spec_id same version → no conflict
- [ ] Doc with no spec_id and no filename → gracefully skipped
- [ ] Three docs: two versions of "Power_Spec" → one conflict between them
- [ ] Filename stem extraction: "Power_Spec_v3.pdf" → "Power_Spec"
- [ ] Filename with revision suffix: "Timing_rev2.pdf" → "Timing"
- [ ] Filename with no version: "README.pdf" → "README" (no conflict with itself)
- [ ] format_conflict_warning with no conflicts → empty string
- [ ] format_conflict_warning with conflicts → includes "WARNING" and spec identifiers
- [ ] Warning instructs LLM not to silently choose one version

```bash
cd /home/juansync7/RAG && python -m pytest tests/retrieval/test_version_conflicts.py -v
# Expected: ALL PASS (types.py pure utilities are fully implemented in Phase 0)
```

---

## Task A-3.3: Prompt Template Tests

**Agent input (ONLY these):**
- REQ-601 (anti-hallucination system prompt stored in separate file)
- REQ-602 (template engine that safely handles curly braces in documents)
- Phase 0 contracts: none — template integration has no Phase 0 types

**Must NOT receive:** `src/retrieval/prompt_loader.py`, Design Doc B.11 code

**Files → Create:** `tests/retrieval/test_prompt_template.py`

**Test cases:**
- [ ] System prompt loads from markdown file (REQ-601)
- [ ] Human template substitutes {documents} and {question} placeholders (REQ-602)
- [ ] Document content with curly braces `{"voltage": "1.8V"}` passes through safely (REQ-602)
- [ ] System prompt is static (no variable substitution inside it) (REQ-601)
- [ ] Missing prompt file → clear error, not a crash
- [ ] Prompt contains all 5 anti-hallucination instruction categories (REQ-601)

```bash
cd /home/juansync7/RAG && python -m pytest tests/retrieval/test_prompt_template.py -v
# Expected: ALL FAIL (no implementation yet)
```

---

## Task A-4.4: Observability Tests (REQ-801–803)

**Agent input (ONLY these):**
- REQ-801 (end-to-end trace with unique ID)
- REQ-802 (per-stage metrics: latency, scores, counts)
- REQ-803 (alerting thresholds)
- Phase 0 contracts: `src/retrieval/observability/types.py`

**Must NOT receive:** `src/retrieval/observability/tracing.py`

**Files → Create:** `tests/retrieval/test_observability.py`

**Test cases:**
- [ ] start_trace() creates trace with unique UUID (REQ-801)
- [ ] @traced decorator captures latency_ms for a function (REQ-802)
- [ ] @traced extracts scalar metadata from dict return values (REQ-802)
- [ ] Multiple stages accumulate in QueryTrace.stages list (REQ-801)
- [ ] total_latency_ms = sum of all stage latencies
- [ ] get_current_trace() returns None when no trace active
- [ ] Risk level propagated through trace (REQ-801)

```bash
cd /home/juansync7/RAG && python -m pytest tests/retrieval/test_observability.py -v
# Expected: ALL PASS (types.py decorators are fully implemented in Phase 0)
```

---

## Task A-6.1: Fallback Retrieval Routing Tests

### Agent Isolation Contract

You have access to:
- `src/retrieval/pipeline/rag_chain.py` — the pipeline to test
- Only the requirements REQ-1201

### Test Cases

1. **Test fallback triggered on weak retrieval**: Mock primary retrieval returning weak results, verify standalone_query retrieval is attempted.
2. **Test fallback NOT triggered on strong retrieval**: Mock strong primary retrieval, verify no fallback.
3. **Test fallback NOT triggered when suppress_memory=True**: Verify fallback skipped because standalone was already primary.
4. **Test better results selected**: Mock primary weak + fallback moderate, verify fallback results used.
5. **Test both weak**: Mock both retrievals weak, verify best-of comparison still runs.

---

## Task A-6.2: Memory-Generation Path Tests

### Agent Isolation Contract

You have access to:
- `src/retrieval/pipeline/rag_chain.py` — the pipeline to test
- Only the requirements REQ-1203, REQ-1204

### Test Cases

1. **Test memory-gen triggered**: Both retrievals weak + has_backward_reference=True + non-empty memory → generates from memory.
2. **Test fresh conversation guard**: has_backward_reference=True + empty memory → BLOCK (not memory-gen).
3. **Test hybrid case (REQ-1204)**: has_backward_reference=True + strong retrieval → standard retrieval+memory path, NOT memory-gen.
4. **Test confidence routing on memory-gen**: Memory-generated answer with low confidence → BLOCK.
5. **Test re-retrieval skip**: Memory-generated answer → confidence routing skips re-retrieval step.
6. **Test generation_source="memory"**: Memory-gen path sets generation_source correctly.

---

## Task A-6.3: Suppress-Memory Routing Tests

### Agent Isolation Contract

You have access to:
- `src/retrieval/pipeline/rag_chain.py` — the pipeline to test
- Only the requirements REQ-1205

### Test Cases

1. **Test suppress_memory=True routing**: Verify standalone_query used as primary, no memory in generation.
2. **Test no fallback when suppress_memory**: Verify fallback retrieval is skipped.
3. **Test generation has no memory**: Verify generation prompt does not contain memory_context or recent_turns.
4. **Test generation_source="retrieval"**: Verify source is "retrieval" not "retrieval+memory".

---

## Task A-6.4: BLOCK/FLAG Memory Filtering Tests

### Agent Isolation Contract

You have access to:
- Caller-side contract documentation
- Only the requirements REQ-1207

### Test Cases

1. **Test BLOCK response not stored**: After BLOCK, verify append_turn() not called for assistant turn.
2. **Test FLAG response not stored**: After FLAG, verify append_turn() not called for assistant turn.
3. **Test user turn always stored**: User's query IS stored regardless of response action.
4. **Test RETURN response stored**: Normal response IS stored in memory.
5. **Test no echo**: After BLOCK on query A, query B's memory context does not contain BLOCK message.

---

## Task A-6.5: Generation Source Tracking Tests

### Agent Isolation Contract

You have access to:
- `src/retrieval/pipeline/rag_chain.py` and `src/retrieval/common/schemas.py`
- Only the requirements REQ-1209

### Test Cases

1. **Test source="retrieval"**: Standard retrieval generation → "retrieval".
2. **Test source="memory"**: Memory-generation path → "memory".
3. **Test source="retrieval+memory"**: Hybrid backward-ref + strong retrieval → "retrieval+memory".
4. **Test source=None**: BLOCK with no generation → None.
5. **Test suppress_memory source**: suppress_memory=True + successful retrieval → "retrieval" (not "retrieval+memory").

---

# Phase B — Implementation (Against Tests)

Each Phase B task implements the code that makes its corresponding Phase A tests pass.
The agent receives ONLY its own test file + Phase 0 contracts — never other tasks' tests.

---

## Task B-1.2: Post-Generation Guardrail

**Agent input:** Design Task 1.2 + 5.3 description, `tests/retrieval/test_post_generation_guardrail.py`, Phase 0 contracts

**Must NOT receive:** `tests/retrieval/test_pre_retrieval_guardrail.py` or other test files

**Files → Modify:** `src/retrieval/guardrails/post_generation.py`

**Dependencies:** B-2.1 (confidence scoring), B-2.3 [QUERY — see RETRIEVAL_QUERY_IMPLEMENTATION.md] (risk classification)

**Implementation steps:**
- [ ] Create PostGenerationGuardrail class with config loading (REQ-903)
- [ ] Implement `_filter_pii()` — reuse regex patterns from pre-retrieval (shared module) (REQ-703)
- [ ] Implement `_sanitize_output()` — detect system prompt fragments, remove markers/artifacts (REQ-704)
- [ ] Implement `_detect_hallucination()` — check each answer sentence against retrieved doc texts (REQ-702)
- [ ] Implement `_apply_risk_filtering()` — for HIGH risk: regex for numerical values, verify against source docs (REQ-705)
- [ ] Implement `_route()` — threshold-based routing with single re-retrieval limit (REQ-706)
- [ ] Implement `evaluate()` method that chains PII → sanitize → hallucination → risk filter → route (REQ-706)
- [ ] Wire evaluate_answer stub in types.py to call PostGenerationGuardrail.evaluate

```bash
cd /home/juansync7/RAG && python -m pytest tests/retrieval/test_post_generation_guardrail.py -v
# Expected: ALL PASS
```

- [ ] Commit: "feat(retrieval): implement post-generation guardrail with confidence routing"

---

## Task B-1.3: Retry Logic

**Agent input:** Design Task 1.3 description, `tests/retrieval/test_retry_logic.py`, Phase 0 contracts

**Must NOT receive:** other test files

**Files → Modify:** `src/retrieval/retry.py` (already fully implemented in Phase 0)

**Cross-reference:** LiteLLM already has built-in retry (`LLM_NUM_RETRIES=3` in `config/settings.py`). The `with_retry` decorator adds: configurable backoff, fallback functions, and exception-type filtering. Apply it to query processing LLM calls and any direct generation calls not covered by LiteLLM retries.

**Implementation steps:**
- [ ] Verify Phase 0 `retry.py` passes all tests (REQ-605)
- [ ] If any test fails, fix the implementation (REQ-902)

```bash
cd /home/juansync7/RAG && python -m pytest tests/retrieval/test_retry_logic.py -v
# Expected: ALL PASS (already implemented)
```

- [ ] Commit: "feat(retrieval): verify retry logic with exponential backoff"

---

## Task B-2.1: Confidence Scoring Engine

**Agent input:** Design Task 2.1 description, `tests/retrieval/test_confidence_scoring.py`, Phase 0 contracts

**Must NOT receive:** other test files

**Files → Modify:** `src/retrieval/confidence/engine.py`

**Cross-reference:** `src/retrieval/rag_chain.py` currently has no composite confidence scoring — it passes through raw reranker scores. This task adds the 3-signal composite.

**Implementation steps:**
- [ ] Verify Phase 0 `scoring.py` pure functions pass all tests (REQ-701, REQ-604)
- [ ] Create engine.py that wraps scoring.py functions with config loading (REQ-903)
- [ ] Load confidence weights from config (default 0.50/0.25/0.25) (REQ-903)
- [ ] Implement `score()` method that calls compute_composite_confidence with loaded weights

```bash
cd /home/juansync7/RAG && python -m pytest tests/retrieval/test_confidence_scoring.py -v
# Expected: ALL PASS
```

- [ ] Commit: "feat(retrieval): implement 3-signal confidence scoring engine"

---

## Task B-2.2: Full-Pipeline LangGraph Routing

**Agent input:** Design Task 2.2 description, `tests/retrieval/test_pipeline_routing.py`, Phase 0 contracts

**Must NOT receive:** other test files

**Files → Modify:** `src/retrieval/pipeline.py`

**Dependencies:** B-1.1 [QUERY — see RETRIEVAL_QUERY_IMPLEMENTATION.md], B-1.2, B-2.1

**Cross-reference:** `src/retrieval/rag_chain.py` currently orchestrates the pipeline imperatively with `run()`. This task creates a LangGraph-based pipeline using `RAGPipelineState` from Phase 0.

**Implementation steps:**
- [ ] Define graph nodes for each pipeline stage (REQ-706)
- [ ] Implement `route_after_query_processing()` — branch on query_action (REQ-102)
- [ ] Implement `route_after_guardrail()` — branch on guardrail_passed (REQ-205)
- [ ] Implement `route_after_post_guardrail()` — branch on post_guardrail_action (REQ-706)
- [ ] Implement re-retrieval with broader params: increase search_limit, shift alpha toward BM25 (REQ-706)
- [ ] Enforce single retry limit: retry_count < 1 check (REQ-706)
- [ ] Implement graceful degradation nodes for each optional component (REQ-902)
- [ ] Wire all nodes and conditional edges in `build_rag_pipeline()`
- [ ] **Stage 6 — memory echo suppression**: In the generation node, gate `recent_turns` on `retrieval_quality in ("strong", "moderate")`; pass `None` for weak/insufficient quality. `memory_context` (rolling summary) is always passed regardless of retrieval quality.
- [ ] **Stage 7.5 — FLAG display**: In the FLAG branch of confidence routing, append `verification_warning` to `generated_answer` as `"\n\n---\n⚠️ <warning text>"` in addition to setting the structured `verification_warning` field.

```bash
cd /home/juansync7/RAG && python -m pytest tests/retrieval/test_pipeline_routing.py -v
# Expected: ALL PASS
```

- [ ] Commit: "feat(retrieval): implement full-pipeline LangGraph routing with confidence-based decisions"

---

## Task B-3.1: Structured Document Formatter

**Agent input:** Design Task 3.1 description, `tests/retrieval/test_document_formatter.py`, Phase 0 contracts

**Must NOT receive:** other test files

**Files → Modify:** `src/retrieval/formatting/formatter.py`

**Cross-reference:** `src/retrieval/generator.py` currently formats chunks inline with simple numbering. This task replaces that with structured metadata attachment per REQ-501.

**Implementation steps:**
- [ ] Implement `format_retrieved_docs()` — structured metadata header per chunk (REQ-501)
- [ ] Default missing metadata to "unknown" (REQ-501)
- [ ] Number chunks sequentially (REQ-503)
- [ ] Prepend conflict warnings if any (REQ-502 integration)
- [ ] Ensure format is deterministic (same input → same output) (REQ-503)

```bash
cd /home/juansync7/RAG && python -m pytest tests/retrieval/test_document_formatter.py -v
# Expected: ALL PASS
```

- [ ] Commit: "feat(retrieval): implement structured document formatter"

---

## Task B-3.2: Version Conflict Detection Integration

**Agent input:** Design Task 3.2 description, `tests/retrieval/test_version_conflicts.py`, Phase 0 contracts

**Must NOT receive:** other test files

**Files → Modify:** `src/retrieval/formatting/conflicts.py`

**Dependencies:** B-3.1 (formatter)

**Implementation steps:**
- [ ] Verify Phase 0 `detect_version_conflicts` and `format_conflict_warning` pass tests (REQ-502)
- [ ] Create conflicts.py integration that wires detection into the formatting pipeline
- [ ] Include conflict information in generated answer response (REQ-502)

```bash
cd /home/juansync7/RAG && python -m pytest tests/retrieval/test_version_conflicts.py -v
# Expected: ALL PASS
```

- [ ] Commit: "feat(retrieval): integrate version conflict detection"

---

## Task B-3.3: PromptTemplate Integration

**Agent input:** Design Task 3.3 description, `tests/retrieval/test_prompt_template.py`, Phase 0 contracts

**Must NOT receive:** other test files

**Files → Modify:** `src/retrieval/prompt_loader.py`

**Cross-reference:** `src/retrieval/generator.py` currently uses inline f-string formatting. This task replaces it with ChatPromptTemplate that safely handles curly braces in documents.

**Implementation steps:**
- [ ] Store system prompt in `prompts/rag_system.md` (REQ-601)
- [ ] Store human template in `prompts/rag_human.md` with {documents} and {question} (REQ-602)
- [ ] Use ChatPromptTemplate from LangChain (only declared variables substituted) (REQ-602)
- [ ] Verify document content with `{curly_braces}` passes through safely (REQ-602)
- [ ] System prompt includes all 5 anti-hallucination instruction categories (REQ-601)

```bash
cd /home/juansync7/RAG && python -m pytest tests/retrieval/test_prompt_template.py -v
# Expected: ALL PASS
```

- [ ] Commit: "feat(retrieval): implement safe prompt template with anti-hallucination instructions"

---

## Task B-4.4: Observability Instrumentation (REQ-801–803)

**Agent input:** Design Task 4.4 description, `tests/retrieval/test_observability.py`, Phase 0 contracts

**Must NOT receive:** other test files

**Files → Modify:** `src/retrieval/observability/tracing.py`

**Dependencies:** All pipeline stages must exist

**Cross-reference:** `src/retrieval/rag_chain.py` already captures `stage_timings` and `timing_totals`. This task formalizes tracing with the `@traced` decorator and `QueryTrace` from Phase 0.

**Implementation steps:**
- [ ] Verify Phase 0 `traced` decorator and `QueryTrace` pass all tests (REQ-801, REQ-802)
- [ ] Create tracing.py with pipeline-level wiring: start trace at entry, collect metrics per stage
- [ ] Include trace_id in final response (REQ-801)
- [ ] Implement alerting threshold checks (REQ-803)

```bash
cd /home/juansync7/RAG && python -m pytest tests/retrieval/test_observability.py -v
# Expected: ALL PASS
```

- [ ] Commit: "feat(retrieval): implement end-to-end observability with tracing"

---

## Task B-6.1: Fallback Retrieval Routing

### Agent Isolation Contract

You have access to:
- `src/retrieval/pipeline/rag_chain.py` — the pipeline to modify
- `src/retrieval/query/schemas.py` — to read QueryResult fields
- Only the routing changes specified below — do NOT change existing retrieval or reranking logic

### Target Files

| File | Action |
|---|---|
| `src/retrieval/pipeline/rag_chain.py` | MODIFY |

### Requirements Covered

REQ-1201

### Dependencies

Task 7.1 from query implementation (schema with standalone_query)

### Implementation Steps

**Step 1** — Read `rag_chain.py` fully. Find the section after primary retrieval + reranking where `retrieval_quality` is computed.

**Step 2** — After quality classification, add fallback logic:
- If `retrieval_quality in ("weak", "insufficient")` AND `NOT query_result.suppress_memory`:
  - Embed `query_result.standalone_query` (use existing embedding method, check cache first)
  - Execute hybrid search with standalone_query embedding
  - Rerank fallback results
  - Compare best reranker score from primary vs fallback
  - Use the set with higher best score
  - Update `retrieval_quality` and `retrieval_quality_note` based on chosen results

**Step 3** — Skip fallback entirely when `query_result.suppress_memory is True`.

---

## Task B-6.2: Memory-Generation Path and Hybrid Routing

### Agent Isolation Contract

You have access to:
- `src/retrieval/pipeline/rag_chain.py` — the pipeline to modify
- Only the generation routing changes specified below

### Target Files

| File | Action |
|---|---|
| `src/retrieval/pipeline/rag_chain.py` | MODIFY |

### Requirements Covered

REQ-1203, REQ-1204

### Dependencies

Task 6.1 (fallback retrieval)

### Implementation Steps

**Step 1** — After all retrieval passes and quality classification, add routing logic:
- If `retrieval_quality in ("weak", "insufficient")` AND `query_result.has_backward_reference` AND (`memory_context` or `memory_recent_turns` is non-empty):
  - Set `generation_source = "memory"`
  - Generate using `memory_context + recent_turns` as context (no document chunks)
  - When running confidence routing: skip re-retrieval step, go directly to BLOCK/FLAG thresholds
- If `has_backward_reference` AND retrieval is strong/moderate:
  - Set `generation_source = "retrieval+memory"`
  - Use standard generation with docs + memory + turns (existing behavior, just tag the source)
- Guard: if `has_backward_reference` AND empty memory (fresh convo): fall through to standard BLOCK

**Step 2** — For memory-only generation: build a context string from `memory_context` and formatted `recent_turns`, pass as the context chunks to the generator.

---

## Task B-6.3: Suppress-Memory Routing

### Agent Isolation Contract

You have access to:
- `src/retrieval/pipeline/rag_chain.py` — the pipeline to modify
- Only the suppress_memory routing logic

### Target Files

| File | Action |
|---|---|
| `src/retrieval/pipeline/rag_chain.py` | MODIFY |

### Requirements Covered

REQ-1205

### Dependencies

Task 7.3 from query implementation (suppress_memory detection)

### Implementation Steps

**Step 1** — At the start of `rag_chain.run()`, after query processing, check `query_result.suppress_memory`:
- If True: set `search_query = query_result.standalone_query`
- Set `memory_context = None` and `memory_recent_turns = None` for generation
- Skip fallback retrieval (standalone IS the primary)
- Set `generation_source = "retrieval"`

---

## Task B-6.4: BLOCK/FLAG Memory Filtering (Caller Contract)

### Agent Isolation Contract

This is a caller-side contract, not a pipeline change. Document the contract for CLI/API implementors.

### Target Files

| File | Action |
|---|---|
| Caller code (CLI/API/server) | MODIFY (contract) |

### Requirements Covered

REQ-1207

### Dependencies

None

### Implementation Steps

**Step 1** — Document the caller contract: before calling `append_turn()`, check `response.post_guardrail_action`:
- If action is "block" or "flag": display response to user, but skip `append_turn()` for the assistant turn.
- Always store the user's turn.

**Step 2** — This is a documentation + caller-side change. The pipeline itself does not change.

---

## Task B-6.5: Generation Source Tracking

### Agent Isolation Contract

You have access to:
- `src/retrieval/common/schemas.py` — RAGResponse to modify
- `src/retrieval/pipeline/rag_chain.py` — to set the field

### Target Files

| File | Action |
|---|---|
| `src/retrieval/common/schemas.py` | MODIFY |
| `src/retrieval/pipeline/rag_chain.py` | MODIFY |

### Requirements Covered

REQ-1209

### Dependencies

Tasks 6.1, 6.2, 6.3

### Implementation Steps

**Step 1** — Add `generation_source: Optional[str] = None` to `RAGResponse` dataclass.

**Step 2** — In `rag_chain.run()`, set the field based on routing path:
- `"retrieval"`: standard retrieval generation (including suppress_memory path)
- `"memory"`: memory-generation path
- `"retrieval+memory"`: retrieval succeeded + has_backward_reference (hybrid)
- `None`: generation skipped (BLOCK)

**Step 3** — Include `generation_source` in the `RAGResponse` return.

---

# Phase C — Engineering Guide

> **Trigger:** After ALL Phase B tasks complete and all Phase B tests pass.
> **Skill:** Invoke `write-engineering-guide` for both sub-phases.

Phase C runs in two sub-phases: parallel module documentation, then a single cross-cutter assembly pass.

---

## Phase C-parallel — Module Documentation (all parallel)

One agent per module. Each agent writes one module section document and saves to `docs/tmp/module-<name>.md`.

**Agent isolation contract (include verbatim in each task):**
> The module doc agent receives ONLY its assigned source file(s) and the spec FR numbers.
> Must NOT receive: other modules' source files, any test files, the design doc.

---

### Task C-1: Guardrail Layer Module Doc

**Agent input (ONLY these):**
1. `src/retrieval/guardrails/pre_retrieval.py`, `src/retrieval/guardrails/post_generation.py`, `src/retrieval/guardrails/types.py`
2. Spec FR numbers: REQ-201–REQ-205, REQ-701–REQ-706

**Must NOT receive:** Any other source files, test files, or design doc.

**Files → Create:** `docs/tmp/module-pre-retrieval-guardrail.md`, `docs/tmp/module-post-generation-guardrail.md`

Each module doc must contain all 6 sub-sections: Purpose, How it works, Key design decisions, Configuration, Error behavior, Test guide.

---

### Task C-2: Confidence Engine Module Doc

**Agent input (ONLY these):**
1. `src/retrieval/confidence/engine.py`, `src/retrieval/confidence/scoring.py`, `src/retrieval/confidence/types.py`
2. Spec FR numbers: REQ-604, REQ-701

**Must NOT receive:** Any other source files, test files, or design doc.

**Files → Create:** `docs/tmp/module-confidence-engine.md`

---

### Task C-3: Document Formatting Module Doc

**Agent input (ONLY these):**
1. `src/retrieval/formatting/formatter.py`, `src/retrieval/formatting/conflicts.py`, `src/retrieval/formatting/types.py`
2. Spec FR numbers: REQ-501, REQ-502, REQ-503

**Must NOT receive:** Any other source files, test files, or design doc.

**Files → Create:** `docs/tmp/module-document-formatter.md`, `docs/tmp/module-version-conflicts.md`

---

### Task C-4: Prompt Loading Module Doc

**Agent input (ONLY these):**
1. `src/retrieval/prompt_loader.py`
2. Spec FR numbers: REQ-601, REQ-602

**Must NOT receive:** Any other source files, test files, or design doc.

**Files → Create:** `docs/tmp/module-prompt-loader.md`

---

### Task C-5: Observability Module Doc

**Agent input (ONLY these):**
1. `src/retrieval/observability/tracing.py`, `src/retrieval/observability/types.py`
2. Spec FR numbers: REQ-801, REQ-802, REQ-803

**Must NOT receive:** Any other source files, test files, or design doc.

**Files → Create:** `docs/tmp/module-observability.md`

---

### Task C-7: Utilities Module Doc

**Agent input (ONLY these):**
1. `src/retrieval/pipeline_state.py`, `src/retrieval/retry.py`, `src/retrieval/context_resolver.py`, `src/retrieval/pool.py`, `src/retrieval/cached_embeddings.py`, `src/retrieval/result_cache.py`
2. Spec FR numbers: REQ-103, REQ-306, REQ-307, REQ-308, REQ-605, REQ-902

**Must NOT receive:** Any other source files, test files, or design doc.

**Files → Create:** `docs/tmp/module-retry.md`, `docs/tmp/module-context-resolver.md`, `docs/tmp/module-pool.md`, `docs/tmp/module-cached-embeddings.md`, `docs/tmp/module-result-cache.md`

---

## Phase C-cross — Engineering Guide Assembly (single agent, after all C-parallel complete)

### Phase C gate — all must be ✅ before C-cross starts:
- [ ] Task C-1: spec review ✅
- [ ] Task C-2: spec review ✅
- [ ] Task C-3: spec review ✅
- [ ] Task C-4: spec review ✅
- [ ] Task C-5: spec review ✅
- [ ] Task C-7: spec review ✅

### Task C-cross: Assemble Engineering Guide

**Agent input (ONLY these):**
1. All Phase C-parallel module section documents (paths listed above under `docs/tmp/`)
2. Companion spec: `docs/retrieval/RETRIEVAL_GENERATION_SPEC.md` (FR numbers for coverage mapping)

**Must NOT receive:** Any source files directly.

**Files → Create:** `docs/retrieval/RETRIEVAL_GENERATION_ENGINEERING_GUIDE.md`

Invoke: `write-engineering-guide` skill.

Writes: System Overview, Architecture Decisions, Data Flow (2–3 scenarios), Integration Contracts, Configuration Reference, Testing Guide (testability map + critical scenarios), Operational Notes, Known Limitations, Extension Guide, Appendix: Requirement Coverage.

---

# Phase D — White-Box Tests

> **Trigger:** After Phase C-cross completes.
> **Skill:** Invoke `write-module-tests` per task. All Phase D tasks run in parallel.

**Agent isolation contract (include verbatim at top of every Phase D task):**
> The Phase D test agent receives ONLY:
> 1. The module section from `docs/retrieval/RETRIEVAL_GENERATION_ENGINEERING_GUIDE.md` (Purpose, Error behavior, Test guide sub-sections)
> 2. Phase 0 contract files (TypedDicts, signatures, exceptions)
> 3. FR numbers from the spec
>
> Must NOT receive: Any source files (`src/`), any Phase A test files.

Expected outcome: All Phase D tests FAIL initially (new coverage tests against existing implementation). They PASS in Phase E after the full suite runs.

---

### Task D-1.2: Post-Generation Guardrail Coverage Tests

**Agent input (ONLY these):**
1. Module section for `src/retrieval/guardrails/post_generation.py` from `docs/retrieval/RETRIEVAL_GENERATION_ENGINEERING_GUIDE.md`
2. Phase 0 contracts: `src/retrieval/guardrails/types.py`, `src/retrieval/confidence/types.py`
3. FR numbers: REQ-701, REQ-702, REQ-703, REQ-704, REQ-705, REQ-706

**Must NOT receive:** `src/retrieval/guardrails/post_generation.py` or any Phase A test files.

**Files → Create:** `tests/retrieval/test_post_generation_guardrail_coverage.py`

```bash
cd /home/juansync7/RAG && python -m pytest tests/retrieval/test_post_generation_guardrail_coverage.py -v
# Expected: FAIL
```

---

### Task D-2.1: Confidence Engine Coverage Tests

**Agent input (ONLY these):**
1. Module section for `src/retrieval/confidence/engine.py` from `docs/retrieval/RETRIEVAL_GENERATION_ENGINEERING_GUIDE.md`
2. Phase 0 contracts: `src/retrieval/confidence/types.py`, `src/retrieval/confidence/scoring.py`
3. FR numbers: REQ-604, REQ-701

**Must NOT receive:** `src/retrieval/confidence/engine.py` or any Phase A test files.

**Files → Create:** `tests/retrieval/test_confidence_scoring_coverage.py`

```bash
cd /home/juansync7/RAG && python -m pytest tests/retrieval/test_confidence_scoring_coverage.py -v
# Expected: FAIL
```

---

### Task D-3.1: Document Formatter Coverage Tests

**Agent input (ONLY these):**
1. Module section for `src/retrieval/formatting/formatter.py` from `docs/retrieval/RETRIEVAL_GENERATION_ENGINEERING_GUIDE.md`
2. Phase 0 contracts: `src/retrieval/formatting/types.py`
3. FR numbers: REQ-501, REQ-503

**Must NOT receive:** `src/retrieval/formatting/formatter.py` or any Phase A test files.

**Files → Create:** `tests/retrieval/test_document_formatter_coverage.py`

```bash
cd /home/juansync7/RAG && python -m pytest tests/retrieval/test_document_formatter_coverage.py -v
# Expected: FAIL
```

---

### Task D-3.2: Version Conflicts Coverage Tests

**Agent input (ONLY these):**
1. Module section for `src/retrieval/formatting/conflicts.py` from `docs/retrieval/RETRIEVAL_GENERATION_ENGINEERING_GUIDE.md`
2. Phase 0 contracts: `src/retrieval/formatting/types.py`
3. FR numbers: REQ-502

**Must NOT receive:** `src/retrieval/formatting/conflicts.py` or any Phase A test files.

**Files → Create:** `tests/retrieval/test_version_conflicts_coverage.py`

```bash
cd /home/juansync7/RAG && python -m pytest tests/retrieval/test_version_conflicts_coverage.py -v
# Expected: FAIL
```

---

### Task D-3.3: Prompt Template Coverage Tests

**Agent input (ONLY these):**
1. Module section for `src/retrieval/prompt_loader.py` from `docs/retrieval/RETRIEVAL_GENERATION_ENGINEERING_GUIDE.md`
2. Phase 0 contracts: (none — no Phase 0 type file for prompt_loader)
3. FR numbers: REQ-601, REQ-602

**Must NOT receive:** `src/retrieval/prompt_loader.py` or any Phase A test files.

**Files → Create:** `tests/retrieval/test_prompt_template_coverage.py`

```bash
cd /home/juansync7/RAG && python -m pytest tests/retrieval/test_prompt_template_coverage.py -v
# Expected: FAIL
```

---

### Task D-4.4: Observability Coverage Tests

**Agent input (ONLY these):**
1. Module section for `src/retrieval/observability/tracing.py` from `docs/retrieval/RETRIEVAL_GENERATION_ENGINEERING_GUIDE.md`
2. Phase 0 contracts: `src/retrieval/observability/types.py`
3. FR numbers: REQ-801, REQ-802, REQ-803

**Must NOT receive:** `src/retrieval/observability/tracing.py` or any Phase A test files.

**Files → Create:** `tests/retrieval/test_observability_coverage.py`

```bash
cd /home/juansync7/RAG && python -m pytest tests/retrieval/test_observability_coverage.py -v
# Expected: FAIL
```

---

### Phase D gate — all must be ✅ before Phase E starts:
- [ ] Task D-1.2: spec review ✅
- [ ] Task D-2.1: spec review ✅
- [ ] Task D-3.1: spec review ✅
- [ ] Task D-3.2: spec review ✅
- [ ] Task D-3.3: spec review ✅
- [ ] Task D-4.4: spec review ✅

---

# Phase E — Full Suite Verification

> **Trigger:** After ALL Phase D tasks complete.

- [ ] Run full suite:
  ```bash
  cd /home/juansync7/RAG && python -m pytest tests/retrieval/test_post_generation_guardrail.py tests/retrieval/test_retry_logic.py tests/retrieval/test_confidence_scoring.py tests/retrieval/test_pipeline_routing.py tests/retrieval/test_document_formatter.py tests/retrieval/test_version_conflicts.py tests/retrieval/test_prompt_template.py tests/retrieval/test_observability.py tests/retrieval/test_post_generation_guardrail_coverage.py tests/retrieval/test_confidence_scoring_coverage.py tests/retrieval/test_document_formatter_coverage.py tests/retrieval/test_version_conflicts_coverage.py tests/retrieval/test_prompt_template_coverage.py tests/retrieval/test_observability_coverage.py -v
  ```
  Expected: ALL Phase A tests PASS + ALL Phase D tests PASS

- [ ] If any Phase A tests fail: diagnose — likely a Phase B implementation issue, fix in the relevant B task.
- [ ] If any Phase D tests fail: diagnose — either the engineering guide's test guide section was imprecise, or implementation doesn't match documented behavior. Fix implementation or update guide section.

- [ ] Commit:
  ```bash
  git add tests/
  git commit -m "test: add Phase D white-box coverage tests for retrieval generation pipeline"
  ```

---

## Document Chain

```
RETRIEVAL_GENERATION_SPEC.md
        │
        ▼
RETRIEVAL_GENERATION_DESIGN.md
        │
        ▼
RETRIEVAL_GENERATION_IMPLEMENTATION.md
(Phase 0/A/B/C/D/E)
        │
        ├─────────────────────────────┐
        ▼                             ▼
RETRIEVAL_GENERATION_ENGINEERING_GUIDE.md   RETRIEVAL_GENERATION_MODULE_TESTS.md
(Phase C output — write-engineering-guide)  (Phase D catalog — write-module-tests)
```
