# Retrieval Generation Pipeline — Design Document

| Field | Value |
|-------|-------|
| **Document** | Retrieval Generation Pipeline Design Document |
| **Version** | 1.4 |
| **Status** | Draft |
| **Spec Reference** | `RETRIEVAL_GENERATION_SPEC.md` v1.3 (REQ-501–REQ-903, REQ-1201–REQ-1209) |
| **Companion Documents** | `RETRIEVAL_GENERATION_SPEC.md`, `RETRIEVAL_GENERATION_IMPLEMENTATION.md`, `RETRIEVAL_SPEC_SUMMARY.md` |
| **Created** | 2026-03-11 |
| **Last Updated** | 2026-03-27 |

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-03-11 | Initial draft — 5 phases, 17 tasks covering core pipeline through security |
| 1.1 | 2026-03-13 | Added Phase 6 (conversation memory) covering REQ-1001–1008, updated dependency graph and mapping |
| 1.2 | 2026-03-23 | Renamed from Implementation Guide to Design Document; added Contract/Pattern annotations to Part B; added companion document references |
| 1.3 | 2026-03-25 | Split from RETRIEVAL_DESIGN.md; now covers generation-side tasks only (Tasks 1.2, 1.3, 2.1, 2.2, 3.1–3.3, 4.4, 5.3) |
| 1.4 | 2026-03-27 | AI Assistant | Added Phase 6 (Memory-Aware Generation Routing) covering REQ-1201–1209, updated dependency graph and mapping |

> **Document Intent.** This document provides a technical design with task decomposition
> and contract-grade code appendix for the retrieval pipeline specified in
> `RETRIEVAL_QUERY_SPEC.md` / `RETRIEVAL_GENERATION_SPEC.md`. Every task references the
> requirements it satisfies. Part B contract entries are consumed verbatim by the companion
> implementation plan (`RETRIEVAL_GENERATION_IMPLEMENTATION.md`).

---

# Part A: Task-Oriented Overview

## Phase 1 — Core Pipeline Hardening

Foundation work: guardrails, validation, and resilience. These tasks make the pipeline safe before adding new capabilities.

### Task 1.2: Post-Generation Guardrail Layer

**Description:** Build a guardrail module that sits between generation and answer delivery. It computes confidence, detects hallucination, filters PII from the answer, sanitizes output, and routes based on confidence + risk.

**Requirements Covered:** REQ-701, REQ-702, REQ-703, REQ-704, REQ-705, REQ-706

**Dependencies:** Task 2.1 (confidence scoring logic), Task 2.3 (risk classification — shared with Task 1.1)

**Complexity:** L

**Subtasks:**

1. Define a `PostGuardrailResult` data structure (action: return/re-retrieve/flag, redacted answer, confidence breakdown)
2. Implement PII detection on generated answer (regex + optional NER)
3. Implement output sanitization (system prompt leak detection, artifact stripping)
4. Implement risk-based output filtering for HIGH risk queries (numerical claim verification)
5. Implement confidence routing logic (threshold-based, with single re-retrieval retry)
6. Wire into the pipeline between generation and answer delivery

---

### Task 1.3: Retry Logic for External LLM Calls

**Description:** Add exponential backoff retry wrapper for all external LLM calls (query reformulation, confidence evaluation, answer generation). Include graceful fallback when all retries are exhausted.

**Requirements Covered:** REQ-605, REQ-902

**Dependencies:** None.

**Complexity:** S

**Subtasks:**

1. Implement a generic retry decorator/wrapper with configurable max retries, base interval, and max backoff
2. Apply to query processing LLM calls (reformulation, evaluation)
3. Apply to generation LLM call
4. Define fallback behavior for each call site (heuristic confidence, skip generation, etc.)
5. Externalize retry parameters to config (REQ-903)

---

## Phase 2 — Confidence & Routing

The intelligence layer: composite scoring, risk-aware routing, and full-pipeline orchestration.

### Task 2.1: 3-Signal Confidence Scoring

**Description:** Implement the composite confidence score that combines retrieval confidence (reranker scores), LLM self-reported confidence, and citation coverage into a single 0.0–1.0 score.

**Requirements Covered:** REQ-701, REQ-604

**Dependencies:** REQ-403 (reranker score thresholds — already exists), REQ-604 (LLM confidence extraction)

**Complexity:** M

**Subtasks:**

1. Implement retrieval confidence calculation (top-3 reranker score average)
2. Implement LLM confidence extraction and parsing (high/medium/low → numerical with downward correction)
3. Implement citation coverage calculation (sentence-level grounding check)
4. Implement weighted combination with configurable weights
5. Externalize weights and threshold values to config (REQ-903)

---

### Task 2.2: Full-Pipeline LangGraph Routing

**Description:** Extend the existing LangGraph workflow from query-processing-only to wrap the entire pipeline. Add conditional routing based on composite confidence: return answer, re-retrieve with broader parameters, or flag for review.

**Requirements Covered:** REQ-706, REQ-902

**Dependencies:** Task 2.1 (confidence scoring), Task 1.1 (pre-retrieval guardrail), Task 1.2 (post-generation guardrail)

**Complexity:** L

**Subtasks:**

1. Define `RAGPipelineState` TypedDict covering all pipeline stages (query, transformed query, retrieved docs, ranked docs, formatted context, answer, confidence, risk level, retry count)
2. Define graph nodes for each pipeline stage (transform → guardrail → retrieve → rerank → format → generate → evaluate → route)
3. Implement conditional edges from evaluate node (return / re-retrieve / flag)
4. Implement re-retrieval with broader parameters (increased top-k, lower alpha toward BM25, relaxed filters)
5. Enforce single retry limit (retry_count < 1)
6. Wire human review / escalation node for flagged queries

---

## Phase 3 — Retrieval Quality

Improve the quality of what gets retrieved and how it's presented to the LLM.

### Task 3.1: Structured Document Formatter

**Description:** Replace the current simple chunk formatting with structured metadata attachment. Each chunk injected into the LLM context must carry filename, version, date, domain, section, and spec ID.

**Requirements Covered:** REQ-501, REQ-503

**Dependencies:** Metadata schema must be populated at ingestion time (out of scope, but formatter must handle missing fields gracefully).

**Complexity:** S

**Subtasks:**

1. Define the formatted chunk template (metadata header + content body)
2. Implement formatter function that maps document metadata to the template
3. Handle missing metadata fields (default to "unknown")
4. Number chunks sequentially in the context string
5. Ensure format is deterministic

---

### Task 3.2: Version Conflict Detection

**Description:** Detect when retrieved documents share the same specification ID or filename stem but differ in version. Flag conflicts before generation.

**Requirements Covered:** REQ-502

**Dependencies:** Task 3.1 (document formatter — conflicts must be included in formatted context)

**Complexity:** M

**Subtasks:**

1. Group retrieved documents by spec_id or filename stem
2. Within each group, detect version mismatches
3. Build conflict records (spec, version A, version B, dates)
4. Inject conflict warnings into the LLM context string
5. Include conflict information in the final response to the user

---

### Task 3.3: PromptTemplate Integration

**Description:** Replace raw string formatting for prompt construction with a template engine that safely handles variable injection. Documents containing curly braces (JSON, code) must not be interpreted as template variables.

**Requirements Covered:** REQ-601, REQ-602

**Dependencies:** None.

**Complexity:** S

**Subtasks:**

1. Store system prompt in a separate markdown file (no variables — static rules only)
2. Store human turn template in a separate file with named placeholders (`{documents}`, `{question}`)
3. Use a template engine (e.g., LangChain ChatPromptTemplate) that only substitutes declared variables
4. Verify that document content with `{curly_braces}` is passed through safely
5. Ensure prompt changes take effect on restart without code changes

---

## Phase 4 — Performance & Observability

Make the pipeline fast and debuggable.

### Task 4.4: Observability Instrumentation

**Description:** Add end-to-end tracing and per-stage metrics capture for every query processed.

**Requirements Covered:** REQ-801, REQ-802, REQ-803

**Dependencies:** All pipeline stages must exist (Phases 1–3).

**Complexity:** M

**Subtasks:**

1. Choose observability backend (e.g., Langfuse, OpenTelemetry, or structured JSON logging)
2. Generate unique trace ID per query
3. Implement trace decorator/wrapper for each pipeline stage
4. Capture all metrics defined in REQ-802 (latency, scores, counts per stage)
5. Implement alerting thresholds (REQ-803) with configurable values
6. Ensure trace ID is included in the final response for debugging

---

## Phase 5 — Security

Harden the pipeline against data leakage and injection.

### Task 5.3: Post-Generation PII Filtering

**Description:** Detect and redact PII from generated answers before they reach the user. This runs regardless of LLM deployment mode.

**Requirements Covered:** REQ-703

**Dependencies:** Task 1.2 (post-generation guardrail — this is a subtask of 1.2, broken out for clarity).

**Complexity:** M

**Subtasks:**

1. Reuse PII detection logic from Task 5.2 (shared module)
2. Apply to the generated answer text
3. Replace PII with typed placeholders
4. Log redaction events for audit (count and type, not the PII values)
5. This filter runs on every generated answer (not conditional)

---

## Phase 6 — Memory-Aware Generation Routing

Retrieval-first routing with memory-generation fallback: fallback retrieval on standalone_query, memory-generation path for backward-reference queries, suppress-memory routing, BLOCK/FLAG memory filtering, and generation source tracking.

### Task 6.1: Fallback Retrieval Routing

**Description:** When primary retrieval (using `processed_query`) returns weak/insufficient results and `suppress_memory` is False, execute a fallback retrieval using `standalone_query`. Use whichever retrieval produces better results (measured by best reranker score).

**Requirements Covered:** REQ-1201

**Dependencies:** Task 7.1 from RETRIEVAL_QUERY_DESIGN.md (schema with `standalone_query` field)

**Complexity:** M

**Subtasks:**

1. After primary retrieval + reranking, check `retrieval_quality` — if "weak" or "insufficient" and `suppress_memory` is False, proceed to fallback
2. Embed `standalone_query` (check embedding cache first)
3. Execute hybrid search with `standalone_query` embedding
4. Rerank fallback results
5. Compare best reranker score from primary vs fallback — use the set with higher quality
6. Update `retrieval_quality` and `retrieval_quality_note` based on the chosen results
7. Skip fallback when `suppress_memory` is True (standalone_query was already the primary)

---

### Task 6.2: Memory-Generation Path and Hybrid Routing

**Description:** When all retrieval passes return weak/insufficient results AND `has_backward_reference` is True AND memory is non-empty, generate from conversation memory context only. When backward reference is True but retrieval succeeds, use standard retrieval+memory generation. Apply confidence routing to all paths.

**Requirements Covered:** REQ-1203, REQ-1204

**Dependencies:** Task 6.1 (fallback retrieval — must know both retrieval results)

**Complexity:** M

**Subtasks:**

1. After all retrieval passes, check: both weak AND `has_backward_reference == True`
2. Guard: if `memory_context` and `recent_turns` are both empty (fresh conversation), fall through to BLOCK
3. Build memory-only generation context: `memory_context` + formatted `recent_turns` as the "context" for the generator
4. Call generator with memory context instead of document chunks
5. Apply confidence routing to memory-generated answer — skip re-retrieval step (not applicable), go directly to BLOCK/FLAG
6. When `has_backward_reference == True` AND retrieval is strong/moderate (REQ-1204): use standard path with docs + memory + turns, set `generation_source = "retrieval+memory"`
7. Set `generation_source = "memory"` for the memory-only path

---

### Task 6.3: Suppress-Memory Routing

**Description:** When `suppress_memory` is True (context-reset detected), use `standalone_query` as primary and only retrieval query. Exclude `memory_context` and `recent_turns` from generation prompt.

**Requirements Covered:** REQ-1205

**Dependencies:** Task 7.3 from RETRIEVAL_QUERY_DESIGN.md (context-reset detection)

**Complexity:** S

**Subtasks:**

1. At start of `rag_chain.run()`, check `query_result.suppress_memory`
2. If True: set `search_query = standalone_query`, `gen_memory = None`, `gen_turns = None`
3. Skip fallback retrieval (standalone_query IS the primary)
4. Pass `gen_memory=None, gen_turns=None` to generator
5. Set `generation_source = "retrieval"` (no memory involved)

---

### Task 6.4: BLOCK/FLAG Memory Filtering

**Description:** Document the caller-side contract for excluding BLOCK and FLAG responses from conversation memory storage. This is a caller-side change (CLI/API/server), not a pipeline change.

**Requirements Covered:** REQ-1207

**Dependencies:** None — this is a caller-side contract.

**Complexity:** S

**Subtasks:**

1. Define contract: callers MUST check `response.post_guardrail_action` before calling `append_turn()`
2. If action is "block" or "flag": display response to user BUT skip `append_turn()` for the assistant turn
3. Always store the user's turn regardless of response action
4. Document the contract in the engineering guide for caller implementors

---

### Task 6.5: Generation Source Tracking

**Description:** Add `generation_source` field to `RAGResponse` and set it based on which path produced the answer.

**Requirements Covered:** REQ-1209

**Dependencies:** Task 6.1, 6.2, 6.3 (all routing paths must be implemented to know the source)

**Complexity:** S

**Subtasks:**

1. Add `generation_source: Optional[str] = None` to `RAGResponse` dataclass
2. Set `"retrieval"` when generating from retrieved documents (primary or fallback)
3. Set `"memory"` when generating from memory-only path
4. Set `"retrieval+memory"` when generating from docs + memory context
5. Set `None` when generation is skipped (BLOCK with no generation)

---

## Task Dependency Graph

```
Phase 1 (Foundation)
├── Task 1.1: Pre-Retrieval Guardrail                         [see RETRIEVAL_QUERY_DESIGN.md]
├── Task 1.3: Retry Logic
├── Task 1.4: Input Validation (can merge into 1.1)           [see RETRIEVAL_QUERY_DESIGN.md]
│
Phase 2 (Confidence & Routing)
├── Task 2.3: Risk Classification ◄────Task 1.1               [see RETRIEVAL_QUERY_DESIGN.md]
├── Task 2.1: 3-Signal Confidence
│
├── Task 1.2: Post-Generation Guardrail ◄── Task 2.1, 2.3
│
└── Task 2.2: Full-Pipeline LangGraph ◄── Task 1.1, 1.2, 2.1

Phase 3 (Retrieval Quality)
├── Task 3.1: Document Formatter
├── Task 3.2: Version Conflict Detection ◄── Task 3.1
├── Task 3.3: PromptTemplate Integration
└── Task 3.4: Multi-Turn Context                              [see RETRIEVAL_QUERY_DESIGN.md]

Phase 4 (Performance & Observability)
├── Task 4.1: Connection Pooling                              [see RETRIEVAL_QUERY_DESIGN.md]
├── Task 4.2: Embedding Cache                                 [see RETRIEVAL_QUERY_DESIGN.md]
├── Task 4.3: Query Result Cache                              [see RETRIEVAL_QUERY_DESIGN.md]
└── Task 4.4: Observability ◄── All pipeline stages

Phase 5 (Security)
├── Task 5.1: Externalize Injection Patterns ◄── Task 1.1     [see RETRIEVAL_QUERY_DESIGN.md]
├── Task 5.2: Pre-Retrieval PII Filtering ◄── Task 1.1        [see RETRIEVAL_QUERY_DESIGN.md]
└── Task 5.3: Post-Generation PII Filtering ◄── Task 1.2

Phase 6 (Conversation Memory)
├── Task 6.1: Conversation Memory Provider ──────────────────────┐  [see RETRIEVAL_QUERY_DESIGN.md]
├── Task 6.2: Sliding Window and Rolling Summary ◄── Task 6.1 ──┤  [see RETRIEVAL_QUERY_DESIGN.md]
├── Task 6.3: Conversation Lifecycle Operations ◄── Task 6.1,6.2┤  [see RETRIEVAL_QUERY_DESIGN.md]
└── Task 6.4: Memory Context Injection ◄── Task 6.2, Task 3.4 ──┘  [see RETRIEVAL_QUERY_DESIGN.md]

Phase 6 (Memory-Aware Generation Routing)
├── Task 6.1: Fallback Retrieval Routing ◄── Task 7.1 (query schema)     [see RETRIEVAL_QUERY_DESIGN.md]
├── Task 6.2: Memory-Gen Path & Hybrid Routing ◄── Task 6.1
├── Task 6.3: Suppress-Memory Routing ◄── Task 7.3 (reset detection)     [see RETRIEVAL_QUERY_DESIGN.md]
├── Task 6.4: BLOCK/FLAG Memory Filtering (caller-side)
└── Task 6.5: Generation Source Tracking ◄── Task 6.1, 6.2, 6.3
```

---

## Task-to-Requirement Mapping

| Task | Requirements Covered |
|------|---------------------|
| 1.2 Post-Generation Guardrail | REQ-701, REQ-702, REQ-703, REQ-704, REQ-705, REQ-706 |
| 1.3 Retry Logic | REQ-605, REQ-902 |
| 2.1 3-Signal Confidence | REQ-701, REQ-604 |
| 2.2 LangGraph Routing | REQ-706, REQ-902 |
| 3.1 Document Formatter | REQ-501, REQ-503 |
| 3.2 Version Conflict Detection | REQ-502 |
| 3.3 PromptTemplate Integration | REQ-601, REQ-602 |
| 4.4 Observability | REQ-801, REQ-802, REQ-803 |
| 5.3 Post-Generation PII Filtering | REQ-703 |
| 6.1 Fallback Retrieval Routing | REQ-1201 |
| 6.2 Memory-Gen Path & Hybrid Routing | REQ-1203, REQ-1204 |
| 6.3 Suppress-Memory Routing | REQ-1205 |
| 6.4 BLOCK/FLAG Memory Filtering | REQ-1207 |
| 6.5 Generation Source Tracking | REQ-1209 |

---

# Part B: Code Appendix

## B.3: 3-Signal Confidence Scoring — Contract

**Tasks:** Task 2.1
**Requirements:** REQ-701, REQ-604
**Type:** Contract (exact — copied to implementation plan Phase 0)

```python
from dataclasses import dataclass


@dataclass
class ConfidenceBreakdown:
    retrieval_score: float       # From reranker (objective)
    llm_score: float             # From LLM self-report (subjective)
    citation_score: float        # From citation coverage (structural)
    composite: float             # Weighted combination
    retrieval_weight: float
    llm_weight: float
    citation_weight: float


# Downward correction map for LLM overconfidence
LLM_CONFIDENCE_MAP = {
    "high": 0.85,      # Not 1.0 — LLMs overestimate
    "medium": 0.55,    # Not 0.6
    "low": 0.25,       # Not 0.3
}


def compute_retrieval_confidence(reranker_scores: list[float], top_n: int = 3) -> float:
    """Average of top-N reranker scores. Objective signal."""
    if not reranker_scores:
        return 0.0
    scores = sorted(reranker_scores, reverse=True)[:top_n]
    return sum(scores) / len(scores)


def parse_llm_confidence(llm_confidence_text: str) -> float:
    """Map LLM self-reported confidence to numerical score with downward correction."""
    return LLM_CONFIDENCE_MAP.get(llm_confidence_text.strip().lower(), 0.5)


def compute_citation_coverage(answer: str, retrieved_quotes: list[str]) -> float:
    """Fraction of answer sentences grounded in retrieved content."""
    sentences = _split_sentences(answer)
    if not sentences:
        return 0.0

    covered = 0
    for sentence in sentences:
        sentence_lower = sentence.lower().strip()
        if len(sentence_lower) < 10:
            # Skip very short sentences (e.g., "Yes.", "No.")
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
    """Compute composite confidence from 3 independent signals."""
    retrieval = compute_retrieval_confidence(reranker_scores)
    llm = parse_llm_confidence(llm_confidence_text)
    citation = compute_citation_coverage(answer, retrieved_quotes)

    composite = (
        retrieval * retrieval_weight +
        llm * llm_weight +
        citation * citation_weight
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
    """Basic sentence splitting. Replace with spaCy/nltk for production."""
    import re
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    return [s for s in sentences if s.strip()]


def _has_substantial_overlap(sentence: str, quote: str, threshold: int = 5) -> bool:
    """Check if sentence shares at least `threshold` consecutive words with a quote."""
    sentence_words = sentence.split()
    quote_words = quote.split()
    for i in range(len(sentence_words) - threshold + 1):
        ngram = " ".join(sentence_words[i:i + threshold])
        if ngram in " ".join(quote_words):
            return True
    return False
```

---

## B.4: Post-Generation Guardrail — Contract

**Tasks:** Task 1.2, Task 2.1
**Requirements:** REQ-701, REQ-702, REQ-703, REQ-704, REQ-705, REQ-706
**Type:** Contract (exact — copied to implementation plan Phase 0)

```python
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import re


class PostGuardrailAction(Enum):
    RETURN = "return"             # Answer is good — deliver to user
    RE_RETRIEVE = "re_retrieve"  # Low confidence — try again with broader params
    FLAG = "flag"                 # Escalate to human review
    BLOCK = "block"              # Do not return answer


@dataclass
class PostGuardrailResult:
    action: PostGuardrailAction
    answer: str                              # Possibly redacted/sanitized
    confidence: ConfidenceBreakdown
    risk_level: RiskLevel
    pii_redactions: list[dict] = field(default_factory=list)
    hallucination_flags: list[str] = field(default_factory=list)
    verification_warning: Optional[str] = None


class PostGenerationGuardrail:
    def __init__(self, config_path: str = "config/guardrails.yaml"):
        with open(config_path) as f:
            config = yaml.safe_load(f)

        post_config = config.get("post_generation", {})
        self.high_confidence_threshold = post_config.get("high_confidence_threshold", 0.70)
        self.low_confidence_threshold = post_config.get("low_confidence_threshold", 0.50)
        self.system_prompt_fragments = self._load_system_prompt_fragments(
            post_config.get("system_prompt_path", "prompts/rag_system.md")
        )

    def evaluate(
        self,
        answer: str,
        confidence: ConfidenceBreakdown,
        risk_level: RiskLevel,
        retrieved_docs: list[dict],
        retry_count: int = 0,
    ) -> PostGuardrailResult:
        # 1. PII filtering (always runs)
        answer, pii_redactions = self._filter_pii(answer)

        # 2. Output sanitization
        answer = self._sanitize_output(answer)

        # 3. Hallucination detection
        hallucination_flags = self._detect_hallucination(answer, retrieved_docs, risk_level)

        # 4. Risk-based output filtering (HIGH risk only)
        verification_warning = None
        if risk_level == RiskLevel.HIGH:
            answer, verification_warning = self._apply_risk_filtering(
                answer, retrieved_docs
            )

        # 5. Confidence routing
        action = self._route(confidence.composite, risk_level, retry_count)

        return PostGuardrailResult(
            action=action,
            answer=answer,
            confidence=confidence,
            risk_level=risk_level,
            pii_redactions=pii_redactions,
            hallucination_flags=hallucination_flags,
            verification_warning=verification_warning,
        )

    def _route(
        self, composite_score: float, risk_level: RiskLevel, retry_count: int
    ) -> PostGuardrailAction:
        if composite_score < self.low_confidence_threshold:
            if retry_count < 1:
                return PostGuardrailAction.RE_RETRIEVE
            return PostGuardrailAction.BLOCK

        if composite_score < self.high_confidence_threshold:
            if retry_count < 1:
                return PostGuardrailAction.RE_RETRIEVE
            return PostGuardrailAction.FLAG

        # composite >= high threshold
        if risk_level == RiskLevel.HIGH:
            return PostGuardrailAction.RETURN  # With verification warning attached
        return PostGuardrailAction.RETURN

    # FLAG action display note: when action is FLAG, the pipeline appends
    # verification_warning directly to generated_answer as a visible block
    # ("\n\n---\n⚠️ <warning>") in addition to setting the structured field.
    # This ensures display layers that only render answer text show the warning.

    def _filter_pii(self, text: str) -> tuple[str, list[dict]]:
        redactions = []
        # Email
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        for match in re.finditer(email_pattern, text):
            redactions.append({"type": "EMAIL", "position": match.span()})
        text = re.sub(email_pattern, "[EMAIL]", text)

        # Phone
        phone_pattern = r'\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)?\d{3}[-.\s]?\d{4}\b'
        for match in re.finditer(phone_pattern, text):
            redactions.append({"type": "PHONE", "position": match.span()})
        text = re.sub(phone_pattern, "[PHONE]", text)

        # Person names would use NER here — placeholder
        # names = ner_model.detect_persons(text)
        # for name in names:
        #     redactions.append({"type": "PERSON", ...})
        #     text = text.replace(name, "[PERSON]")

        return text, redactions

    def _sanitize_output(self, answer: str) -> str:
        # Remove any system prompt fragments that leaked
        for fragment in self.system_prompt_fragments:
            if fragment in answer:
                answer = answer.replace(fragment, "")

        # Remove internal document markers
        answer = re.sub(r'---\s*Document\s*\d+\s*---', '', answer)

        # Remove template variable artifacts
        answer = re.sub(r'\{(?:documents|question|context)\}', '', answer)

        return answer.strip()

    def _detect_hallucination(
        self, answer: str, retrieved_docs: list[dict], risk_level: RiskLevel
    ) -> list[str]:
        flags = []
        sentences = _split_sentences(answer)
        doc_texts = [doc.get("text", "") for doc in retrieved_docs]

        for sentence in sentences:
            if len(sentence.strip()) < 10:
                continue
            grounded = any(
                _has_substantial_overlap(sentence.lower(), doc.lower())
                for doc in doc_texts
            )
            if not grounded:
                flags.append(sentence)

        return flags

    def _apply_risk_filtering(
        self, answer: str, retrieved_docs: list[dict]
    ) -> tuple[str, str]:
        """For HIGH risk: flag numerical claims not found in source docs."""
        warning = "VERIFY BEFORE IMPLEMENTATION — This answer addresses a high-risk domain."

        # Find numerical values in the answer
        numerical_pattern = r'\b\d+\.?\d*\s*(?:V|mV|A|mA|MHz|GHz|kHz|ns|ps|us|ms|°C|K)\b'
        numbers_in_answer = re.findall(numerical_pattern, answer, re.IGNORECASE)

        doc_text = " ".join(doc.get("text", "") for doc in retrieved_docs)
        for num in numbers_in_answer:
            if num not in doc_text:
                warning += f"\n  - Value '{num}' not found verbatim in source documents."

        return answer, warning

    def _load_system_prompt_fragments(self, path: str) -> list[str]:
        """Load system prompt and extract key fragments for leak detection."""
        try:
            with open(path) as f:
                content = f.read()
            # Extract distinctive phrases (not common words)
            lines = [
                line.strip() for line in content.split("\n")
                if len(line.strip()) > 30
            ]
            return lines[:20]  # Top 20 distinctive lines
        except FileNotFoundError:
            return []
```

---

## B.5: Version Conflict Detection — Contract

**Tasks:** Task 3.2
**Requirements:** REQ-502
**Type:** Contract (exact — copied to implementation plan Phase 0)

```python
from dataclasses import dataclass
from typing import Optional
import re


@dataclass
class VersionConflict:
    spec_identifier: str           # Spec ID or filename stem
    version_a: str
    date_a: str
    version_b: str
    date_b: str


def detect_version_conflicts(documents: list[dict]) -> list[VersionConflict]:
    """Detect when retrieved docs share a spec ID / filename stem but differ in version."""
    version_map: dict[str, dict] = {}
    conflicts: list[VersionConflict] = []

    for doc in documents:
        metadata = doc.get("metadata", {})

        # Prefer spec_id; fall back to filename stem
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
    """Format conflicts for injection into LLM context."""
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
    """Extract base name without version suffix. E.g., 'Power_Spec_v3.pdf' → 'Power_Spec'."""
    if not filename:
        return None
    # Remove extension
    name = re.sub(r'\.[^.]+$', '', filename)
    # Remove version suffix patterns (_v3, _v2.1, _rev3, etc.)
    name = re.sub(r'[_-]?v\d+(\.\d+)?$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'[_-]?rev\d+$', '', name, flags=re.IGNORECASE)
    return name if name else None
```

---

## B.6: Structured Document Formatter — Pattern

**Tasks:** Task 3.1
**Requirements:** REQ-501, REQ-503
**Type:** Pattern (illustrative — shows approach, not exact contract)

```python
def format_retrieved_docs(
    documents: list[dict],
    conflicts: list[VersionConflict],
) -> str:
    """Format retrieved documents with structured metadata for LLM context injection."""
    formatted_chunks = []

    for i, doc in enumerate(documents, 1):
        metadata = doc.get("metadata", {})
        chunk = f"""--- Document {i} ---
Filename    : {metadata.get('filename', 'unknown')}
Version     : {metadata.get('version', 'unknown')}
Date        : {metadata.get('date', 'unknown')}
Domain      : {metadata.get('domain', 'unknown')}
Section     : {metadata.get('section', 'unknown')}
Spec ID     : {metadata.get('spec_id', 'N/A')}
Content:
{doc.get('text', '')}
"""
        formatted_chunks.append(chunk)

    # Prepend version conflict warnings if any
    conflict_warning = format_conflict_warning(conflicts)

    parts = []
    if conflict_warning:
        parts.append(conflict_warning)
    parts.append("\n".join(formatted_chunks))

    return "\n".join(parts)
```

---

## B.14: Retry Logic Wrapper — Contract

**Tasks:** Task 1.3
**Requirements:** REQ-605, REQ-902
**Type:** Contract (exact — copied to implementation plan Phase 0)

```python
import time
import logging
from functools import wraps
from typing import TypeVar, Callable, Optional

T = TypeVar("T")
logger = logging.getLogger(__name__)


def with_retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    backoff_factor: float = 2.0,
    fallback: Optional[Callable[..., T]] = None,
    exceptions: tuple = (Exception,),
):
    """Decorator: retry with exponential backoff. Falls back if all retries fail."""
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
                            max_delay
                        )
                        logger.warning(
                            f"{func.__name__} attempt {attempt + 1}/{max_retries + 1} "
                            f"failed: {e}. Retrying in {delay:.1f}s..."
                        )
                        time.sleep(delay)
                    else:
                        logger.error(
                            f"{func.__name__} exhausted all {max_retries + 1} attempts. "
                            f"Last error: {e}"
                        )

            # All retries exhausted — use fallback or raise
            if fallback is not None:
                logger.info(f"{func.__name__} using fallback.")
                return fallback(*args, **kwargs)
            raise last_exception

        return wrapper
    return decorator


# Usage example:
#
# def _heuristic_confidence(query: str) -> float:
#     word_count = len(query.split())
#     if word_count <= 2: return 0.4
#     if word_count <= 5: return 0.7
#     return 0.85
#
# @with_retry(max_retries=3, base_delay=1.0, fallback=_heuristic_confidence)
# def evaluate_query_confidence(query: str) -> float:
#     return call_ollama_for_confidence(query)
```

---

## B.11: PromptTemplate Integration — Pattern

**Tasks:** Task 3.3
**Requirements:** REQ-601, REQ-602
**Type:** Pattern (illustrative — shows approach, not exact contract)

```python
from langchain_core.prompts import ChatPromptTemplate
from pathlib import Path


def load_rag_prompt(
    system_prompt_path: str = "prompts/rag_system.md",
    human_template_path: str = "prompts/rag_human.md",
) -> ChatPromptTemplate:
    """
    Load prompt from markdown files.

    System prompt: static rules, no variables.
    Human template: contains {documents} and {question} placeholders.

    LangChain's ChatPromptTemplate handles curly braces in document content
    safely — only explicitly declared variables are substituted.
    """
    system_prompt = Path(system_prompt_path).read_text()
    human_template = Path(human_template_path).read_text()

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", human_template),
    ])

    return prompt


# Usage:
#
# prompt = load_rag_prompt()
# chain = prompt | llm | output_parser
#
# response = chain.invoke({
#     "documents": format_retrieved_docs(ranked_docs, conflicts),
#     "question": user_query,
# })
```

---

## B.12: Full-Pipeline LangGraph Definition — Contract

**Tasks:** Task 2.2
**Requirements:** REQ-706, REQ-902
**Type:** Contract (exact — RAGPipelineState TypedDict copied to Phase 0; graph definition is illustrative)

```python
from langgraph.graph import StateGraph, END
from typing import TypedDict, Optional


class RAGPipelineState(TypedDict):
    # Input
    question: str
    conversation_history: list[dict]

    # Query processing
    processed_query: str
    query_confidence: float
    query_action: str                  # "search" or "ask_user"
    clarification_message: Optional[str]

    # Pre-retrieval guardrail
    risk_level: str                    # "HIGH", "MEDIUM", "LOW"
    sanitized_query: str
    guardrail_passed: bool

    # Retrieval
    retrieved_docs: list[dict]
    kg_expanded_terms: list[str]

    # Reranking
    ranked_docs: list[dict]
    reranker_scores: list[float]

    # Document formatting
    formatted_context: str
    version_conflicts: list[dict]

    # Generation
    answer: str
    llm_confidence: str                # "high", "medium", "low"

    # Post-generation guardrail
    composite_confidence: float
    confidence_breakdown: dict
    post_guardrail_action: str         # "return", "re_retrieve", "flag", "block"
    final_answer: str
    verification_warning: Optional[str]

    # Control
    retry_count: int


def build_rag_pipeline() -> StateGraph:
    graph = StateGraph(RAGPipelineState)

    # Define nodes
    graph.add_node("process_query",           process_query_node)
    graph.add_node("pre_retrieval_guardrail",  pre_guardrail_node)
    graph.add_node("retrieve",                 retrieve_node)
    graph.add_node("rerank",                   rerank_node)
    graph.add_node("format_docs",              format_docs_node)
    graph.add_node("generate",                 generate_node)
    graph.add_node("post_generation_guardrail", post_guardrail_node)
    graph.add_node("return_answer",            return_answer_node)
    graph.add_node("ask_user",                 ask_user_node)
    graph.add_node("block_answer",             block_answer_node)
    graph.add_node("flag_for_review",          flag_for_review_node)

    # Entry point
    graph.set_entry_point("process_query")

    # Query processing → route on action
    graph.add_conditional_edges("process_query", route_after_query_processing, {
        "search": "pre_retrieval_guardrail",
        "ask_user": "ask_user",
    })

    # Pre-retrieval guardrail → route on pass/reject
    graph.add_conditional_edges("pre_retrieval_guardrail", route_after_guardrail, {
        "pass": "retrieve",
        "reject": "block_answer",
    })

    # Linear pipeline: retrieve → rerank → format → generate → evaluate
    graph.add_edge("retrieve",    "rerank")
    graph.add_edge("rerank",      "format_docs")
    graph.add_edge("format_docs", "generate")
    graph.add_edge("generate",    "post_generation_guardrail")

    # Post-generation guardrail → route on confidence
    graph.add_conditional_edges("post_generation_guardrail", route_after_post_guardrail, {
        "return":       "return_answer",
        "re_retrieve":  "retrieve",        # Loop back with broader params
        "flag":         "flag_for_review",
        "block":        "block_answer",
    })

    # Terminal nodes
    graph.add_edge("return_answer",    END)
    graph.add_edge("ask_user",         END)
    graph.add_edge("block_answer",     END)
    graph.add_edge("flag_for_review",  END)

    return graph.compile()


# --- Routing functions ---

def route_after_query_processing(state: RAGPipelineState) -> str:
    return state["query_action"]


def route_after_guardrail(state: RAGPipelineState) -> str:
    return "pass" if state["guardrail_passed"] else "reject"


def route_after_post_guardrail(state: RAGPipelineState) -> str:
    return state["post_guardrail_action"]


# --- Node implementations (signatures) ---

def process_query_node(state: RAGPipelineState) -> dict:
    """Reformulate query, score confidence, resolve multi-turn references."""
    # Implementation: use existing query processor + conversation history
    ...

def pre_guardrail_node(state: RAGPipelineState) -> dict:
    """Run pre-retrieval guardrail: validate, detect injection, classify risk, PII filter."""
    # Implementation: see B.1 PreRetrievalGuardrail
    ...

def retrieve_node(state: RAGPipelineState) -> dict:
    """Execute hybrid search (vector + BM25) with optional KG expansion."""
    # On retry: broaden params (increase search_limit, shift alpha toward BM25)
    search_limit = 10 if state["retry_count"] == 0 else 20
    alpha = 0.5 if state["retry_count"] == 0 else 0.3
    ...

def rerank_node(state: RAGPipelineState) -> dict:
    """Cross-encoder reranking with score thresholds."""
    # Filter out documents below minimum score threshold (0.30)
    ...

def format_docs_node(state: RAGPipelineState) -> dict:
    """Attach structured metadata, detect version conflicts, format context."""
    # Implementation: see B.5 and B.6
    ...

def generate_node(state: RAGPipelineState) -> dict:
    """Generate answer using anti-hallucination prompt with retry logic."""
    # Implementation: see B.14 retry wrapper + B.11 PromptTemplate
    # Memory gating: recent_turns is passed to the generator only when
    # retrieval_quality is "strong" or "moderate". When retrieval_quality is
    # "weak" or "insufficient", recent_turns is set to None before the
    # generate() call to prevent the LLM from echoing prior answers in place
    # of grounded content. memory_context (rolling summary) is always passed.
    ...

def post_guardrail_node(state: RAGPipelineState) -> dict:
    """Compute confidence, detect hallucination, filter PII, route."""
    # Implementation: see B.3 and B.4
    ...

def return_answer_node(state: RAGPipelineState) -> dict:
    """Package final answer with sources, confidence, and risk metadata."""
    ...

def ask_user_node(state: RAGPipelineState) -> dict:
    """Return clarification request to user."""
    ...

def block_answer_node(state: RAGPipelineState) -> dict:
    """Return 'Insufficient documentation found' message."""
    ...

def flag_for_review_node(state: RAGPipelineState) -> dict:
    """Escalate to human review queue."""
    ...
```

---

## B.13: Observability Wrapper — Contract

**Tasks:** Task 4.4
**Requirements:** REQ-801, REQ-802, REQ-803
**Type:** Contract (exact — StageMetrics, QueryTrace, traced decorator copied to Phase 0)

```python
import time
import uuid
import logging
from functools import wraps
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class StageMetrics:
    stage_name: str
    latency_ms: float
    metadata: dict = field(default_factory=dict)


@dataclass
class QueryTrace:
    trace_id: str
    risk_level: str
    stages: list[StageMetrics] = field(default_factory=list)
    total_latency_ms: float = 0.0

    def add_stage(self, stage: StageMetrics):
        self.stages.append(stage)
        self.total_latency_ms = sum(s.latency_ms for s in self.stages)


# Global trace context (per-request — use contextvars in async)
_current_trace: QueryTrace | None = None


def start_trace(risk_level: str = "LOW") -> QueryTrace:
    global _current_trace
    _current_trace = QueryTrace(
        trace_id=str(uuid.uuid4()),
        risk_level=risk_level,
    )
    return _current_trace


def get_current_trace() -> QueryTrace | None:
    return _current_trace


def traced(stage_name: str):
    """Decorator to capture timing and metadata for a pipeline stage."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            result = func(*args, **kwargs)
            elapsed_ms = (time.perf_counter() - start) * 1000

            trace = get_current_trace()
            if trace:
                # Extract metrics from result if it's a dict
                metadata = {}
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
                    f"[{trace.trace_id}] {stage_name}: {elapsed_ms:.1f}ms",
                    extra={"trace_id": trace.trace_id, "stage": stage_name},
                )

            return result
        return wrapper
    return decorator


# Usage:
#
# @traced("retrieval")
# def retrieve_node(state):
#     results = hybrid_search(...)
#     return {"retrieved_docs": results, "result_count": len(results)}
#
# The decorator automatically captures:
# - Latency (elapsed time)
# - Metadata (result_count and other scalar values from the return dict)
# - Logs with trace ID for correlation
```

---

## B.7: RAGResponse Extension and Generation Routing — Contract

**Tasks:** Task 6.5, Task 6.2, Task 6.3
**Requirements:** REQ-1209, REQ-1203, REQ-1205
**Type:** Contract (exact — copied to implementation plan Phase 0)

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

---

## B.8: Memory-Generation Routing Logic — Pattern

**Tasks:** Task 6.1, Task 6.2, Task 6.3
**Requirements:** REQ-1201, REQ-1203, REQ-1204, REQ-1205
**Type:** Pattern (illustrative — passed to implement-code, not copied to Phase 0)

```python
# Illustrative pattern — retrieval routing with memory-generation fallback
# Shows the decision logic inside rag_chain.run() after query processing

def route_retrieval_and_generation(
    query_result,       # QueryResult with standalone_query, suppress_memory, has_backward_reference
    memory_context,     # str | None
    memory_recent_turns,  # list[dict] | None
    retrieval_quality,  # str: "strong" | "moderate" | "weak" | "insufficient"
    reranked_results,   # list[RankedResult] from primary retrieval
):
    """Route between retrieval-generation, memory-generation, and BLOCK paths.

    Key design decisions:
    - Retrieval-first: always run retrieval before deciding. Don't pre-classify.
    - Fallback retrieval on standalone_query only when primary is weak AND not suppress_memory.
    - Memory-generation path only when ALL retrieval is weak AND backward-ref AND memory non-empty.
    - suppress_memory overrides everything: no memory in generation, standalone_query only.
    - Confidence routing runs on ALL paths — never bypassed.
    - Re-retrieval from REQ-706 is skipped on memory-gen path (no docs to re-retrieve).
    """
    # Determine generation context based on routing signals
    if query_result.suppress_memory:
        # REQ-1205: Context reset — no memory, standalone_query was primary
        gen_memory = None
        gen_turns = None
        generation_source = "retrieval"
    elif retrieval_quality in ("strong", "moderate"):
        if query_result.has_backward_reference:
            # REQ-1204: Hybrid — retrieval succeeded + backward ref
            gen_memory = memory_context
            gen_turns = memory_recent_turns
            generation_source = "retrieval+memory"
        else:
            # Standard retrieval path with memory as supplementary context
            gen_memory = memory_context
            gen_turns = memory_recent_turns
            generation_source = "retrieval"
    else:
        # Weak/insufficient retrieval
        if query_result.has_backward_reference and (memory_context or memory_recent_turns):
            # REQ-1203: Memory-generation path
            gen_memory = memory_context
            gen_turns = memory_recent_turns
            generation_source = "memory"
            reranked_results = []  # No document context
        else:
            # No backward ref or empty memory — standard weak path → BLOCK/FLAG
            gen_memory = None
            gen_turns = None
            generation_source = None  # Will be set to None on BLOCK

    return gen_memory, gen_turns, generation_source, reranked_results
```

---

## Document Chain

```
RETRIEVAL_GENERATION_SPEC.md ─► RETRIEVAL_GENERATION_DESIGN.md ─► RETRIEVAL_GENERATION_IMPLEMENTATION.md
```
