# Retrieval Pipeline — Generation and Safety Engineering Guide

**AION Knowledge Management Platform**
Version: 1.0 | Status: Draft | Domain: Retrieval Pipeline — Generation and Safety
Last updated: 2026-03-25

| Field | Value |
|-------|-------|
| **Companion Spec** | `RETRIEVAL_GENERATION_SPEC.md` v1.2 |
| **Design Document** | `RETRIEVAL_DESIGN.md` v1.2 |
| **Implementation Plan** | `RETRIEVAL_IMPLEMENTATION.md` |
| **Subsystem** | Document Formatting, Generation, Post-Generation Guardrail, Observability |
| **Source Modules** | `src/retrieval/formatting/`, `src/retrieval/confidence/`, `src/retrieval/guardrails/post_generation.py`, `src/retrieval/observability/`, `src/retrieval/prompt_loader.py`, `src/retrieval/retry.py` |

> **Document intent:** Post-implementation reference for the generation and safety stages of the retrieval pipeline. Covers what was built, why decisions were made, and how to maintain, test, and extend each component.
> For query processing and retrieval stages, see `RETRIEVAL_ENGINEERING_GUIDE.md`.
> For the formal requirements these modules implement, see `RETRIEVAL_GENERATION_SPEC.md`.

---

## 1. System Overview

The generation and safety subsystem transforms retrieved document chunks into grounded, verified answers. It sits between retrieval/reranking (upstream) and answer delivery (downstream) in the AION retrieval pipeline. Its job is to format retrieved context for LLM consumption, generate answers with anti-hallucination prompting, evaluate the answer for confidence and safety, and produce full observability traces for every query.

This subsystem exists because raw LLM generation over retrieved documents is unreliable without structural safeguards. LLMs hallucinate from training data, surface PII from source documents, echo system prompts, and produce answers with false confidence. The generation and safety subsystem makes these failure modes detectable, measurable, and actionable through a layered verification pipeline.

### Architecture

```
                         +-----------------------+
                         |  Retrieved + Ranked   |
                         |  Document Chunks      |
                         +----------+------------+
                                    |
                                    v
                    +-------------------------------+
                    |   Stage 1: Document Formatting |
                    |   - Attach structured metadata |
                    |   - Detect version conflicts   |
                    |   - Build deterministic context |
                    +---------------+---------------+
                                    |
                                    v
                    +-------------------------------+
                    |   Stage 2: Generation          |
                    |   - Load anti-hallucination    |
                    |     system prompt (Jinja2)     |
                    |   - LLM call via LiteLLM       |
                    |   - Retry with backoff          |
                    |   - Extract self-reported       |
                    |     confidence                 |
                    +---------------+---------------+
                                    |
                                    v
                    +-------------------------------+
                    |   Stage 3: Post-Generation     |
                    |   Guardrail                    |
                    |   - 3-signal confidence scoring |
                    |   - PII redaction              |
                    |   - Output sanitization        |
                    |   - HIGH risk filtering        |
                    |   - Confidence routing          |
                    +-------+-------+-------+-------+
                            |       |       |
                  +---------+  +----+----+  +----------+
                  |            |         |             |
                  v            v         v             v
              [RETURN]    [FLAG]   [RE-RETRIEVE]   [BLOCK]
              Deliver     Deliver  Loop back to    Return
              answer      answer + retrieval with  "Insufficient
              to user     warning  broader params  documentation"
                                   (max 1 retry)
                                        |
                                        v
                    +-------------------------------+
                    |   Stage 4: Observability       |
                    |   - Per-stage metrics capture   |
                    |   - End-to-end trace assembly   |
                    |   - Alerting threshold checks   |
                    +-------------------------------+
```

### Design Goals

- **Anti-hallucination**: Every generated claim must be traceable to a retrieved document. Ungrounded claims are flagged, not silently delivered.
- **PII safety**: PII in generated answers is detected and redacted before reaching the user, regardless of deployment mode.
- **Confidence-based routing**: A 3-signal composite score (retrieval quality + LLM self-report + citation coverage) determines whether an answer is returned, retried, or blocked.
- **Risk-proportional verification**: HIGH risk queries (electrical specs, safety compliance) receive additional verification. LOW risk queries receive standard checks.
- **Full observability**: Every query produces a structured trace with per-stage metrics, enabling trend analysis and regression detection.

### Technology Choices

- **LiteLLM** for LLM abstraction -- provider-agnostic API for generation calls, enabling switching between Ollama (local), OpenAI, Anthropic, or other providers without code changes.
- **Jinja2 / template engine** for prompt construction -- safely handles variable injection without interpreting curly braces in document content as template variables.
- **NER + regex** for PII detection -- regex patterns cover email, phone, and employee ID formats; optional NER covers person names for higher recall.
- **LangGraph** for pipeline orchestration -- state machine with conditional routing enables the re-retrieve loop without ad-hoc control flow.

---

## 2. Architecture Decisions

### Decision: 3-Signal Composite Confidence vs. Single Signal

**Context:** The system needs to decide whether to return, retry, or block a generated answer. A single confidence signal is insufficient because each signal type has different failure modes.

**Options considered:**
1. Single signal: LLM self-reported confidence only
2. Two signals: retrieval score + LLM confidence
3. Three signals: retrieval score + LLM confidence + citation coverage (weighted composite)

**Choice:** Three-signal weighted composite (0.50 retrieval, 0.25 LLM, 0.25 citation).

**Rationale:** LLM self-reported confidence is biased toward overconfidence and unreliable alone. Retrieval scores measure document relevance but not generation quality. Citation coverage measures structural grounding but can be gamed by citing without accuracy. Combining all three produces a more robust estimate than any single signal. The retrieval signal receives the highest weight (0.50) because it is the only fully objective signal.

**Consequences:**
- Positive: More robust routing decisions; single-signal failures do not dominate.
- Negative: Three signals add computation cost to every query.
- Watch for: Weight tuning is empirical -- monitor composite score distributions and adjust weights if one signal dominates inappropriately.

---

### Decision: Template Engine vs. f-string for Prompt Construction

**Context:** Retrieved documents frequently contain JSON, YAML, code snippets, and other content with curly braces `{}`. The prompt construction mechanism must handle this safely.

**Options considered:**
1. Python f-strings / `.format()` -- native, zero dependencies
2. Jinja2 / template engine -- explicit variable declaration, safe passthrough of document content
3. String concatenation -- no substitution risk, but fragile and hard to maintain

**Choice:** Jinja2 / template engine (via LangChain ChatPromptTemplate or equivalent).

**Rationale:** f-strings and `.format()` treat every `{key}` as a substitution target. A retrieved document containing `{"voltage": "1.8V"}` would cause a `KeyError` or silent corruption. Jinja2 only substitutes explicitly declared variables, passing all other content through unchanged. The system prompt is stored as a static markdown file with no template variables, further reducing injection risk.

**Consequences:**
- Positive: Documents with arbitrary content (JSON, code, curly braces) are safe.
- Negative: Adds a template engine dependency.
- Watch for: Ensure the system prompt file does not accidentally contain Jinja2 syntax.

---

### Decision: Single Re-Retrieval Retry vs. Multiple Retries

**Context:** When composite confidence falls in the 0.50--0.70 range, the system can retry with broader retrieval parameters. How many retries to allow?

**Options considered:**
1. No retry -- return or block immediately
2. Single retry (max 1 re-retrieval)
3. Multiple retries with escalating parameter changes

**Choice:** Single retry (max 1 re-retrieval).

**Rationale:** A single retry with broader parameters (increased top-k, shifted alpha toward BM25, relaxed filters) gives the system one chance to recover from a narrow initial retrieval. Multiple retries add latency proportional to retry count and rarely improve results beyond the first broadening. The re-retrieval rate is a monitored metric -- if it exceeds 30%, the root cause is retrieval quality, not retry count.

**Consequences:**
- Positive: Bounded latency impact (at most 2x retrieval + generation cost).
- Negative: Some queries that would benefit from a second retry are blocked instead.
- Watch for: Monitor re-retrieval success rate. If re-retrieval frequently fails to improve confidence, the broadening parameters may need tuning.

---

### Decision: Risk-Proportional Verification (HIGH/MEDIUM/LOW Taxonomy)

**Context:** Not all incorrect answers carry the same consequence. A wrong voltage specification is a design risk; a wrong setup instruction is an inconvenience.

**Options considered:**
1. Uniform verification for all queries
2. Binary high/low classification
3. Three-level taxonomy (HIGH/MEDIUM/LOW) with per-level verification rules

**Choice:** Three-level taxonomy with keyword-based classification.

**Rationale:** Three levels map naturally to the engineering domain: HIGH covers electrical specs, timing, safety compliance (incorrect answer = design risk); MEDIUM covers procedures, guidelines, checklists (incorrect answer = process error); LOW covers general questions (incorrect answer = inconvenience). HIGH risk answers receive additional numerical claim verification and a mandatory "VERIFY BEFORE IMPLEMENTATION" warning.

**Consequences:**
- Positive: Verification effort is proportional to consequence severity.
- Negative: Keyword-based classification misses semantic risk (paraphrases of HIGH risk terms).
- Watch for: Taxonomy drift -- new engineering domains may need new HIGH risk keywords.

---

### Decision: LangGraph Pipeline Orchestration vs. Linear Execution

**Context:** The pipeline has conditional routing (re-retrieve loop, block, flag) that does not fit a linear function chain.

**Options considered:**
1. Linear function chain with if/else branching
2. LangGraph state machine with conditional edges
3. Custom event-driven orchestration

**Choice:** LangGraph state machine.

**Rationale:** LangGraph provides typed state, declarative conditional edges, and built-in support for loops (re-retrieve). It also integrates with LangSmith for trace visualization. The `RAGPipelineState` TypedDict defines the shared state surface, and each pipeline stage reads from and writes to this state incrementally. Conditional edges from the post-guardrail node implement the routing table without nested if/else logic.

**Consequences:**
- Positive: Routing logic is declarative and auditable. State shape is typed.
- Negative: LangGraph is a framework dependency; debugging requires understanding its execution model.
- Watch for: State bloat -- `RAGPipelineState` grows with each new feature. Keep fields minimal and well-documented.

---

## 3. Module Reference

### 3.1 Document Formatter — `src/retrieval/formatting/formatter.py`

[Implementation pending -- see RETRIEVAL_IMPLEMENTATION.md Phase B, Task B-3.1]

#### Purpose

The document formatter transforms retrieved document chunks into a structured context string for LLM injection. Each chunk carries structured metadata (filename, version, date, domain, section, spec ID) so the LLM can cite accurately and the post-generation guardrail can verify citations against source metadata. The formatter ensures deterministic output: the same input always produces the same context string.

#### How It Works

1. Receive a list of ranked document dicts, each containing `text` and `metadata` fields.
2. Detect version conflicts by delegating to `detect_version_conflicts()` from `formatting/types.py`.
3. If conflicts exist, prepend a conflict warning block (via `format_conflict_warning()`) to the context string.
4. For each document chunk, in order:
   a. Extract metadata fields: `filename`, `version`, `date`, `domain`, `section`, `spec_id`.
   b. Default any missing field to `"unknown"`.
   c. Format as a numbered block with metadata header followed by content body.
5. Concatenate all formatted blocks into a single context string.
6. Return the context string along with the list of detected `VersionConflict` objects.

Representative format for a single chunk:

```
--- Document 1 ---
Filename: Power_Spec_v3.pdf
Version: v3
Date: 2026-01-15
Domain: physical_design
Section: 4.2 Supply Rails
Spec ID: PS-001

The VDD supply rail operates at 0.85V nominal with a tolerance of +/-5%...
```

#### Key Design Decisions

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|----------------|
| Metadata header above content | Inline metadata, JSON wrapper | LLM reads sequentially; header-first aids citation accuracy |
| Default missing fields to "unknown" | Omit missing fields, raise error | Omission causes inconsistent format; errors halt the pipeline |
| Sequential numbering (Document 1, 2, ...) | UUID-based, hash-based | Sequential numbers are LLM-friendly for citation references |
| Deterministic format | Randomized ordering, relevance-weighted | Determinism enables reproducible tests and guardrail verification |

#### Configuration

| Parameter | Type | Default | Effect |
|-----------|------|---------|--------|
| `metadata_fields` | `list[str]` | `["filename", "version", "date", "domain", "section", "spec_id"]` | Fields extracted from document metadata |
| `missing_field_default` | `str` | `"unknown"` | Value used when a metadata field is absent |
| `chunk_separator` | `str` | `"--- Document {n} ---"` | Delimiter between formatted chunks |

#### Error Behavior

- Empty document list: returns an empty string and an empty conflict list. No exception.
- Document with no `metadata` key: all metadata fields default to `"unknown"`. No exception.
- Document with no `text` key: content body is empty string. No exception.
- The formatter never raises exceptions. All edge cases produce valid (possibly empty) output.

#### Test Guide

- **Behaviors to test**: Single doc with all fields; doc with missing fields; multiple docs with sequential numbering; deterministic output (same input twice); empty doc list; conflict warning prepended when conflicts exist.
- **Mock requirements**: None -- the formatter is pure computation over dict inputs.
- **Boundary conditions**: Zero documents; one document; document with all metadata missing; document with empty text.
- **Error scenarios**: Missing `metadata` key entirely; missing `text` key; `None` values in metadata fields.
- **Known test gaps**: Very large document lists (100+ chunks) are not explicitly tested for performance.

---

### 3.2 Version Conflict Detection — `src/retrieval/formatting/conflicts.py`

[Implementation pending -- see RETRIEVAL_IMPLEMENTATION.md Phase B, Task B-3.2]

The Phase B implementation of `conflicts.py` will integrate the conflict detection logic (already implemented in `formatting/types.py`) into the formatting pipeline. The core detection functions `detect_version_conflicts()` and `format_conflict_warning()` are fully implemented in Phase 0.

#### Purpose

Version conflict detection identifies when two or more retrieved documents share the same specification ID (or filename stem) but differ in version. In engineering workflows, specifications evolve across tape-out cycles, and silently choosing one version over another produces answers based on outdated or incorrect parameters. This module flags conflicts, injects warnings into the LLM context, and surfaces conflict information in the final response.

#### How It Works

1. Receive the list of retrieved document dicts (same input as the formatter).
2. Group documents by a grouping key: `spec_id` if present, otherwise filename stem extracted by `_extract_filename_stem()`.
3. For each group, compare version fields. If two documents in the same group have different `version` values, emit a `VersionConflict` record.
4. `format_conflict_warning()` converts the conflict list into a warning block for LLM injection.
5. The warning explicitly instructs the LLM: "You MUST note this conflict in your answer. Do NOT silently choose one version over another."

Key algorithm -- filename stem extraction (`_extract_filename_stem`):

```python
def _extract_filename_stem(filename: str) -> Optional[str]:
    """Extract base name without version suffix.
    Examples:
        'Power_Spec_v3.pdf' -> 'Power_Spec'
        'Timing_rev2.1.pdf' -> 'Timing'
    """
    if not filename:
        return None
    name = re.sub(r'\.[^.]+$', '', filename)           # strip extension
    name = re.sub(r'[_-]?v\d+(\.\d+)?$', '', name, flags=re.IGNORECASE)   # strip _v3, _v2.1
    name = re.sub(r'[_-]?rev\d+(\.\d+)?$', '', name, flags=re.IGNORECASE) # strip _rev2
    return name if name else None
```

#### Key Design Decisions

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|----------------|
| Group by spec_id first, filename stem as fallback | Filename only, metadata hash | spec_id is the stable identifier across versions; filename stem is a reasonable fallback |
| Report first conflict per group only | Report all pairwise conflicts | One conflict record per spec is sufficient for the user; pairwise grows quadratically |
| LLM-directed warning text | Silent metadata flag | The LLM must explicitly acknowledge the conflict; silent flags are ignored |

#### Configuration

| Parameter | Type | Default | Effect |
|-----------|------|---------|--------|
| (No standalone configuration) | -- | -- | Conflict detection uses document metadata directly; version suffix regex patterns are hardcoded in `_extract_filename_stem` |

#### Error Behavior

- Document with no `spec_id` and no `filename`: skipped (no grouping key). No exception.
- Document with missing `version` field: treated as `"unknown"`. If two documents in the same group both have version `"unknown"`, no conflict is reported (same version string).
- Empty document list: returns empty conflict list.
- The module never raises exceptions.

#### Test Guide

- **Behaviors to test**: Two docs same spec_id different versions produce one conflict; same spec_id same version produces no conflict; filename stem extraction for various patterns (`_v3`, `_rev2.1`, no suffix); `format_conflict_warning` with and without conflicts.
- **Mock requirements**: None -- pure computation.
- **Boundary conditions**: Three docs with two different versions of the same spec; document with no spec_id and no filename; empty string filename.
- **Error scenarios**: Missing metadata key entirely; `None` values for spec_id and filename.
- **Known test gaps**: Documents with non-standard version naming schemes (e.g., "draft1", "final") are not detected by the regex.

---

### 3.3 Prompt Template Loader — `src/retrieval/prompt_loader.py`

[Implementation pending -- see RETRIEVAL_IMPLEMENTATION.md Phase B, Task B-3.3]

#### Purpose

The prompt template loader constructs the LLM prompt from a static system prompt file and a human turn template with named placeholders. It replaces raw string formatting (`f-strings`, `.format()`) with a template engine that safely handles variable injection. Retrieved documents containing curly braces (JSON, code snippets) pass through without being interpreted as template variables.

#### How It Works

1. On initialization (or first call), load the system prompt from a markdown file specified in configuration (`prompts/rag_system.md` by default). The system prompt is static -- no variable substitution.
2. Load the human turn template from a separate file. The template contains named placeholders: `{documents}` and `{question}`.
3. On each generation request:
   a. Receive the formatted context string (from the document formatter) and the user question.
   b. Substitute `{documents}` and `{question}` in the human turn template.
   c. Return the assembled prompt as a list of message dicts (`[{"role": "system", ...}, {"role": "user", ...}]`).
4. Template files are cached at module scope after first load. Changes to prompt files take effect on restart.

> **Behavior Note — Memory echo suppression (rag_chain.py Stage 6):** The pipeline passes two memory inputs to the generator: `memory_context` (a rolling conversation summary) and `recent_turns` (verbatim prior Q&A turns). `recent_turns` is gated on retrieval quality: it is passed only when `retrieval_quality` is `"strong"` or `"moderate"`. When retrieval quality is `"weak"` or `"insufficient"`, `recent_turns` is set to `None` before calling `generate()` to prevent the LLM from echoing prior answers in place of grounded content. `memory_context` is always passed regardless of retrieval quality.

The system prompt contains all five anti-hallucination instruction categories (REQ-601):
- Answer ONLY from provided retrieved documents
- Never use training data or prior knowledge
- Cite sources using `[Filename, Version, Section]` format
- Explicitly state when information is insufficient
- Report confidence level (high, medium, low)

#### Key Design Decisions

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|----------------|
| Jinja2 / ChatPromptTemplate | f-strings, `.format()`, string concatenation | Safe handling of curly braces in document content |
| System prompt in separate markdown file | Inline in code, YAML block | Editable without code changes; markdown supports rich formatting |
| Static system prompt (no variables) | Variables in system prompt | Reduces injection surface; system instructions are fixed |
| Cache after first load | Reload on every call, file watcher | Restart-to-reload is sufficient; avoids file I/O per query |

#### Configuration

| Parameter | Type | Default | Effect |
|-----------|------|---------|--------|
| `system_prompt_path` | `str` | `"prompts/rag_system.md"` | Path to the anti-hallucination system prompt file |
| `human_template_path` | `str` | `"prompts/rag_human.md"` | Path to the human turn template with placeholders |

#### Error Behavior

- Missing prompt file: raises `FileNotFoundError` with the path. This is a startup-fatal error -- the system cannot generate without a prompt.
- Template substitution failure (unexpected placeholder): raises `KeyError`. This indicates a template/code mismatch.
- Document content with `{curly_braces}`: passes through safely (template engine only substitutes declared variables).

#### Test Guide

- **Behaviors to test**: System prompt loads from file; human template substitutes `{documents}` and `{question}`; document content with curly braces passes through; system prompt contains all five anti-hallucination categories; prompt changes take effect after restart.
- **Mock requirements**: Mock filesystem (or use `tmp_path` fixture) for prompt files.
- **Boundary conditions**: Empty documents string; very long documents string; question with special characters.
- **Error scenarios**: Missing prompt file; corrupted template file; template with undeclared variable.
- **Known test gaps**: Template engine behavior with deeply nested Jinja2 syntax in document content (unlikely but untested).

---

### 3.4 Confidence Scoring Utilities — `src/retrieval/confidence/scoring.py`

**Status: Implemented** (Phase 0 -- pure utility, fully functional).

The actual implementation lives at `src/retrieval/confidence/scoring.py` and imports its type contracts from `src/retrieval/confidence/schemas.py` (note: the implementation uses `schemas.py` rather than the `types.py` name used in the implementation plan).

#### Purpose

Pure, deterministic utility functions for computing the 3-signal composite confidence score. These functions have no I/O, no side effects, and no external dependencies beyond the `ConfidenceBreakdown` dataclass. They implement the confidence model from the spec: `composite = (W_r * retrieval) + (W_l * llm) + (W_c * citation)`.

#### How It Works

1. **`compute_retrieval_confidence(reranker_scores, top_n=3)`** -- Averages the top-N reranker scores (sigmoid-normalized, each in [0.0, 1.0]). Returns 0.0 if the score list is empty. Using top-N instead of the single best score smooths outliers.

2. **`parse_llm_confidence(llm_confidence_text)`** -- Maps LLM self-reported confidence ("high", "medium", "low") to numerical scores with downward correction for overconfidence bias:

```python
LLM_CONFIDENCE_MAP = {
    "high": 0.85,    # Not 1.0 -- LLMs systematically overestimate
    "medium": 0.55,  # Slight downward correction
    "low": 0.25,     # Slight downward correction
}
```

Parsing is case-insensitive with whitespace trimming. Supports partial matches (e.g., "high confidence" matches "high"). Defaults to 0.5 (neutral) when parsing fails.

3. **`compute_citation_coverage(answer, retrieved_texts, min_overlap_words=5)`** -- Dual-approach citation coverage:
   - Primary signal (70% weight): Counts sentences with valid citation markers `[1]`, `[2]` referencing actual chunk indices.
   - Secondary signal (30% weight): N-gram overlap -- checks for 5+ consecutive word overlap between answer sentences and retrieved text.
   - Sentences shorter than 4 words are filtered out as non-substantive.

4. **`compute_composite_confidence(...)`** -- Combines all three signals:

```python
composite = (retrieval_weight * retrieval_score
             + llm_weight * llm_score
             + citation_weight * citation_score)
```

Validates that weights sum to 1.0 (raises `ValueError` if not). Returns a `ConfidenceBreakdown` dataclass with all signals and the composite.

#### Key Design Decisions

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|----------------|
| Top-3 average for retrieval confidence | Single best score, median, all-score average | Top-3 smooths outliers while reflecting overall retrieval quality |
| Downward correction for LLM confidence | Raw mapping (high=1.0), no correction | LLMs are systematically overconfident; correction produces useful composite scores |
| Dual citation approach (markers + n-gram) | Markers only, semantic similarity, exact match | Markers are primary but can be gamed; n-gram overlap catches unattributed usage |
| Weight validation (must sum to 1.0) | Normalize automatically, no validation | Explicit validation catches configuration errors early |
| 4-word minimum for sentence filtering | No filtering, 10-char threshold | 4 words filters headings and artifacts without discarding short claims |

#### Configuration

| Parameter | Type | Default | Effect |
|-----------|------|---------|--------|
| `top_n` | `int` | `3` | Number of top reranker scores to average |
| `retrieval_weight` | `float` | `0.50` | Weight for retrieval confidence signal |
| `llm_weight` | `float` | `0.25` | Weight for LLM self-reported confidence signal |
| `citation_weight` | `float` | `0.25` | Weight for citation coverage signal |
| `min_overlap_words` | `int` | `5` | Minimum consecutive word overlap for n-gram grounding check |

#### Error Behavior

- Empty reranker scores: `compute_retrieval_confidence` returns 0.0. No exception.
- Empty or `None`-like confidence text: `parse_llm_confidence` returns 0.5 (neutral default). No exception.
- Empty answer: `compute_citation_coverage` returns 1.0 (vacuously true -- no sentences to check). No exception.
- Weights not summing to 1.0: `compute_composite_confidence` raises `ValueError` with a message listing the actual weights.
- All other edge cases produce valid float results clamped to [0.0, 1.0].

#### Test Guide

- **Behaviors to test**: Retrieval confidence with various score list lengths; LLM confidence parsing for all labels plus edge cases (empty, unknown, mixed case, partial match); citation coverage with grounded/ungrounded/mixed sentences; composite calculation with default and custom weights; weight validation.
- **Mock requirements**: None -- all functions are pure computation.
- **Boundary conditions**: Empty lists; single-element lists; all-zero scores; all-1.0 scores; weights summing to exactly 1.0 vs. floating point edge (0.999999).
- **Error scenarios**: Weights not summing to 1.0 (expect `ValueError`); `None` passed as confidence text (handled gracefully).
- **Known test gaps**: Citation coverage accuracy with very long answers (100+ sentences) is not benchmarked for correctness.

---

### 3.5 Confidence Routing Engine — `src/retrieval/confidence/engine.py`

[Implementation pending -- see RETRIEVAL_IMPLEMENTATION.md Phase B, Task B-2.1]

#### Purpose

The confidence routing engine takes a `ConfidenceBreakdown` (from scoring utilities), a `RiskLevel`, and the current `retry_count`, and determines the routing action: RETURN, RE_RETRIEVE, FLAG, or BLOCK. It implements the routing table from REQ-706 and ensures that HIGH risk answers always carry a verification warning regardless of confidence.

#### How It Works

1. Receive the composite confidence score, risk level, and retry count.
2. Apply the routing table:

| Composite Score | Risk Level | Retry Count | Action |
|----------------|------------|-------------|--------|
| > 0.70 | LOW or MEDIUM | any | RETURN |
| > 0.70 | HIGH | any | FLAG (return with verification warning) |
| 0.50 -- 0.70 | any | 0 | RE_RETRIEVE |
| 0.50 -- 0.70 | any | >= 1 | FLAG |
| < 0.50 | any | 0 | RE_RETRIEVE |
| < 0.50 | any | >= 1 | BLOCK |

3. If action is FLAG, attach verification warning text: "WARNING: This answer pertains to a HIGH risk domain. VERIFY BEFORE IMPLEMENTATION against authoritative source documents."
4. Return the `PostGuardrailAction` enum value and optional verification warning.

> **Behavior Note — FLAG display:** When the action is FLAG, the pipeline (`rag_chain.py` Stage 7.5) appends the `verification_warning` text directly to `generated_answer` as a visible block (`\n\n---\n⚠️ <warning text>`), in addition to populating the structured `verification_warning` field. This ensures the warning is visible to any display layer that renders only the answer string.

#### Key Design Decisions

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|----------------|
| Threshold-based routing table | Continuous score-to-action function, ML classifier | Thresholds are interpretable, auditable, and configurable |
| HIGH risk always gets warning | Warning only below threshold | Incorrect electrical specs are design risks regardless of confidence |
| RE_RETRIEVE on first failure, then escalate | Always block, always escalate | One retry balances recovery opportunity against latency |

#### Configuration

| Parameter | Type | Default | Effect |
|-----------|------|---------|--------|
| `high_confidence_threshold` | `float` | `0.70` | Composite above this: return (or flag if HIGH risk) |
| `low_confidence_threshold` | `float` | `0.50` | Composite below this on retry: block |
| `max_retry_count` | `int` | `1` | Maximum re-retrieval attempts before escalation |

#### Error Behavior

- Invalid risk level string: defaults to LOW (safest default -- no extra verification). Logs a warning.
- Negative composite score: treated as below low threshold (BLOCK or RE_RETRIEVE).
- `retry_count` exceeding `max_retry_count`: escalate (FLAG or BLOCK based on composite).

#### Test Guide

- **Behaviors to test**: All six routing table cells; HIGH risk always produces verification warning; retry_count=0 vs. retry_count=1 behavior; exact threshold boundaries (0.50, 0.70).
- **Mock requirements**: None -- routing logic is pure computation over inputs.
- **Boundary conditions**: Composite exactly at 0.70 (boundary: > 0.70 means 0.70 itself is NOT above threshold); composite exactly at 0.50; retry_count exactly at max.
- **Error scenarios**: Invalid risk level; negative composite; retry_count = -1.
- **Known test gaps**: Interaction between confidence routing and the pipeline re-retrieve loop (requires integration test with LangGraph).

---

### 3.6 Post-Generation Guardrail — `src/retrieval/guardrails/post_generation.py`

[Implementation pending -- see RETRIEVAL_IMPLEMENTATION.md Phase B, Task B-1.2]

#### Purpose

The post-generation guardrail is the central safety gate between LLM generation and answer delivery. It evaluates the generated answer through five sequential checks (PII redaction, output sanitization, hallucination detection, HIGH risk filtering, confidence routing) and produces a `PostGuardrailResult` that tells the pipeline what to do with the answer. This is the most complex module in the generation subsystem.

#### How It Works

1. **PII Redaction (REQ-703)**: Scan the generated answer for PII patterns.
   a. Regex patterns detect email addresses, phone numbers, and SSN/employee IDs.
   b. Optional NER detects person names (when NER model is available).
   c. Replace detected PII with typed placeholders: `[EMAIL]`, `[PHONE]`, `[PERSON]`, `[EMPLOYEE_ID]`.
   d. Record all redactions in the result for audit.

2. **Output Sanitization (REQ-704)**: Remove leaked system prompt fragments, internal metadata markers, template artifacts.
   a. Load the system prompt text (from `prompt_loader`).
   b. Check if any substring of the system prompt appears in the answer.
   c. Strip internal markers (e.g., `--- Document 3 ---`).
   d. Strip unsubstituted template variables (e.g., `{documents}`).

3. **Hallucination Detection (REQ-702)**: Check citation coverage.
   a. Split the answer into sentences.
   b. For each sentence, check if it is grounded in the retrieved documents (n-gram overlap or citation marker).
   c. Flag ungrounded sentences in the result.

4. **HIGH Risk Filtering (REQ-705)**: For queries classified as HIGH risk:
   a. Extract numerical values from the answer (voltages, frequencies, temperatures, timing values).
   b. Check if each value has an exact match in the retrieved document text.
   c. Flag unverified numerical claims.
   d. Attach verification warning: "VERIFY BEFORE IMPLEMENTATION".

5. **Confidence Routing (REQ-706)**: Delegate to the confidence routing engine.
   a. Use the pre-computed `ConfidenceBreakdown` and `RiskLevel`.
   b. Receive the routing action (RETURN / RE_RETRIEVE / FLAG / BLOCK).
   c. If BLOCK: replace the answer text with "Insufficient documentation found to answer this query. Please refine your question or consult the source documents directly."

6. Return `PostGuardrailResult` with: action, cleaned answer, confidence breakdown, risk level, PII redactions, hallucination flags, and optional verification warning.

#### Key Design Decisions

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|----------------|
| Sequential check pipeline (PII -> sanitize -> hallucinate -> risk -> route) | Parallel checks, single-pass | Sequential allows each step to operate on the output of the previous; PII must be redacted before any external delivery |
| Regex + optional NER for PII | NER only, regex only, external PII API | Regex covers structured PII (email, phone) reliably; NER adds person name coverage without requiring an external service |
| System prompt leak detection by substring match | Hash comparison, regex patterns | Substring match catches partial leaks; system prompt is loaded at startup and available for comparison |
| Numerical claim verification only for HIGH risk | All risk levels, none | Proportional to consequence; LOW risk numerical claims are low-stakes |
| BLOCK replaces answer entirely | Return partial answer, return with disclaimer | Returning an untrustworthy answer, even with disclaimers, is worse than admitting insufficient documentation |

#### Configuration

| Parameter | Type | Default | Effect |
|-----------|------|---------|--------|
| `pii_patterns` | `dict[str, str]` | Regex patterns for email, phone, SSN, employee ID | PII detection patterns |
| `ner_enabled` | `bool` | `false` | Whether to use NER for person name detection |
| `ner_model` | `str` | `""` | NER model identifier (when enabled) |
| `system_prompt_path` | `str` | `"prompts/rag_system.md"` | Path for system prompt leak detection |
| `high_confidence_threshold` | `float` | `0.70` | Passed to confidence routing engine |
| `low_confidence_threshold` | `float` | `0.50` | Passed to confidence routing engine |
| `block_message` | `str` | `"Insufficient documentation found..."` | Message returned on BLOCK action |

#### Error Behavior

- NER model unavailable: falls back to regex-only PII detection. Logs a warning but does not fail.
- System prompt file unavailable: skips system prompt leak detection. Logs a warning.
- Confidence scoring raises `ValueError` (bad weights): propagates the exception to the caller. This is a configuration error that should fail fast.
- All other errors within the guardrail produce a valid `PostGuardrailResult` with `action=BLOCK` as the safe default.

#### Test Guide

- **Behaviors to test**: PII redaction for each type (email, phone, SSN, person name); output sanitization for system prompt leak, markers, template artifacts; hallucination flag generation; HIGH risk numerical verification; all routing table outcomes; full pipeline through all five stages.
- **Mock requirements**: Mock NER model (when testing person name detection); mock prompt file contents (for system prompt leak detection). Do NOT mock: regex PII detection, confidence scoring math, version conflict detection.
- **Boundary conditions**: Answer with no PII; answer that is entirely a system prompt fragment; HIGH risk answer where all numerical values are verified; composite exactly at threshold boundaries.
- **Error scenarios**: NER model throws exception (expect graceful fallback); system prompt file missing; empty answer string; empty retrieved docs list.
- **Known test gaps**: NER false positive rate on engineering-specific terms (e.g., "Smith chart" detected as person name); system prompt leak detection with paraphrased fragments.

---

### 3.7 Observability and Tracing — `src/retrieval/observability/tracing.py`

[Implementation pending -- see RETRIEVAL_IMPLEMENTATION.md Phase B, Task B-4.4]

The Phase 0 types and decorators are fully implemented in `src/retrieval/observability/types.py`. The Phase B `tracing.py` module wires these into the full pipeline with alerting thresholds and structured output.

#### Purpose

The observability module provides end-to-end tracing and per-stage metrics for every query. It assigns a unique trace ID to each query, captures latency and metadata for each pipeline stage, and checks alerting thresholds for systemic degradation. The trace is included in the final response for debugging.

#### How It Works

1. **Trace initialization**: `start_trace(risk_level)` creates a `QueryTrace` with a UUID trace ID and sets it in a `ContextVar` for downstream propagation.

2. **Per-stage instrumentation**: The `@traced(stage_name)` decorator wraps each pipeline stage function:
   a. Records `time.perf_counter()` before and after execution.
   b. Computes elapsed milliseconds.
   c. Extracts scalar metadata from dict return values (int, float, str, bool fields).
   d. Appends a `StageMetrics` record to the current trace.
   e. Logs with trace ID for correlation.

3. **Stage metrics captured (per REQ-802)**:

| Stage | Metrics |
|-------|---------|
| Document Formatting | chunk_count, version_conflicts_detected |
| Generation | generation_latency_ms, llm_confidence, token_count |
| Post-Generation Guardrail | composite_confidence, citation_coverage, pii_redactions, routing_action |

4. **Alerting (REQ-803)**: After the post-generation guardrail, check metrics against configurable thresholds:
   - Average composite confidence below 0.60
   - End-to-end latency exceeding target
   - PII detection rate above baseline
   - Re-retrieval rate above 30%

5. **Trace propagation**: The trace is carried through `ContextVar`, which is async-safe and works across sync and async execution contexts.

Key code -- the `@traced` decorator (from Phase 0 `types.py`):

```python
def traced(stage_name: str) -> Callable:
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            start = time.perf_counter()
            result = func(*args, **kwargs)
            elapsed_ms = (time.perf_counter() - start) * 1000
            trace = get_current_trace()
            if trace:
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
            return result
        return wrapper
    return decorator
```

#### Key Design Decisions

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|----------------|
| `ContextVar` for trace propagation | Thread-local, explicit parameter passing | ContextVar is async-safe and avoids threading every function signature |
| UUID for trace IDs | Sequential counter, hash-based | UUIDs are globally unique without coordination |
| Decorator-based instrumentation | Explicit timing in each stage, middleware | Decorators are non-invasive and consistently applied |
| Scalar metadata extraction from dict returns | Full return value capture, manual metadata | Automatic extraction captures the most useful debugging signals without manual effort |

#### Configuration

| Parameter | Type | Default | Effect |
|-----------|------|---------|--------|
| `alert_confidence_threshold` | `float` | `0.60` | Alert when average composite confidence drops below this |
| `alert_latency_target_ms` | `float` | `10000` | Alert when end-to-end latency exceeds this |
| `alert_pii_rate_threshold` | `float` | `0.10` | Alert when PII detection rate exceeds this fraction |
| `alert_reretrieval_rate_threshold` | `float` | `0.30` | Alert when re-retrieval rate exceeds 30% |

#### Error Behavior

- No active trace (decorator called without `start_trace`): metrics are silently discarded. The decorated function still executes normally.
- Stage function raises exception: the decorator does NOT catch it. The exception propagates to the caller. Partial timing is not recorded (the trace gets whatever was captured before the failure).
- `ContextVar` not propagated (e.g., new thread without context copying): `get_current_trace()` returns `None`, and metrics are skipped.

#### Test Guide

- **Behaviors to test**: `start_trace` creates trace with UUID; `@traced` captures latency; `@traced` extracts scalar metadata from dict returns; multiple stages accumulate in trace; `total_latency_ms` equals sum of stage latencies; `get_current_trace()` returns `None` when no trace active; risk level propagated.
- **Mock requirements**: None for Phase 0 types. For Phase B alerting: mock the alert dispatch mechanism.
- **Boundary conditions**: Traced function returns non-dict (no metadata extracted); traced function returns empty dict; zero-latency function.
- **Error scenarios**: Decorator on a function that raises; no active trace context.
- **Known test gaps**: Async execution context propagation; concurrent trace isolation under multi-threaded load.

---

### 3.8 Retry Wrapper — `src/retrieval/retry.py`

[Implementation pending as a standalone file -- see RETRIEVAL_IMPLEMENTATION.md Phase 0, Task 0.3. The contract and full implementation are defined in the implementation plan.]

#### Purpose

A generic retry decorator with exponential backoff for all external LLM calls. When all retries are exhausted, an optional fallback function is called for graceful degradation. This wrapper is applied to query processing LLM calls (reformulation, evaluation) and generation LLM calls.

#### How It Works

1. `@with_retry(max_retries=3, base_delay=1.0, max_delay=30.0, backoff_factor=2.0, fallback=fn)` decorates a function.
2. On each call:
   a. Execute the wrapped function.
   b. If it succeeds, return the result immediately.
   c. If it raises an exception matching the `exceptions` tuple:
      - If attempts remain, compute delay = `min(base_delay * backoff_factor^attempt, max_delay)`.
      - Sleep for the computed delay.
      - Retry.
   d. If all retries are exhausted:
      - If `fallback` is provided, call `fallback(*args, **kwargs)` and return its result.
      - If no `fallback`, re-raise the last exception.

Key code:

```python
def with_retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    backoff_factor: float = 2.0,
    fallback: Optional[Callable[..., T]] = None,
    exceptions: tuple = (Exception,),
) -> Callable:
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        delay = min(base_delay * (backoff_factor ** attempt), max_delay)
                        time.sleep(delay)
                    else:
                        logger.error("Exhausted all %d attempts.", max_retries + 1)
            if fallback is not None:
                return fallback(*args, **kwargs)
            raise last_exception
        return wrapper
    return decorator
```

#### Key Design Decisions

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|----------------|
| Decorator pattern | Inline retry loops, retry middleware | Reusable across all LLM call sites without code duplication |
| Exponential backoff with cap | Fixed delay, linear backoff | Exponential reduces thundering herd; cap prevents unreasonable waits |
| Optional fallback function | Always raise, always return None | Fallback enables graceful degradation (heuristic confidence, skip generation) per REQ-902 |
| `functools.wraps` preservation | No preservation | Preserves `__name__` and `__doc__` for debugging and introspection |

#### Configuration

| Parameter | Type | Default | Effect |
|-----------|------|---------|--------|
| `max_retries` | `int` | `3` | Maximum retry attempts (not counting initial call) |
| `base_delay` | `float` | `1.0` | Initial delay in seconds between retries |
| `max_delay` | `float` | `30.0` | Maximum delay cap in seconds |
| `backoff_factor` | `float` | `2.0` | Multiplier for delay between retries |
| `exceptions` | `tuple` | `(Exception,)` | Exception types to catch and retry on |

#### Error Behavior

- `max_retries=0`: function is called once; on failure, fallback is called (if provided) or exception is re-raised.
- Fallback raises: the fallback's exception propagates to the caller (retry wrapper does not catch fallback errors).
- Exception type not in `exceptions` tuple: exception propagates immediately, no retry.
- `backoff_factor=1.0`: constant delay (no exponential growth).

#### Test Guide

- **Behaviors to test**: Success on first try (no retries); fail once then succeed; fail all attempts with fallback; fail all attempts without fallback (exception raised); backoff delay growth; max delay cap; only specified exceptions caught; fallback receives same args/kwargs; `functools.wraps` preservation.
- **Mock requirements**: Mock the wrapped function to control success/failure. Mock `time.sleep` to avoid actual delays in tests.
- **Boundary conditions**: `max_retries=0`; `base_delay=0`; `max_delay=0`; `backoff_factor=0`.
- **Error scenarios**: Fallback function raises; non-matching exception type.
- **Known test gaps**: Thread safety under concurrent calls to the same decorated function.

---

### Type and Schema Files

#### `src/retrieval/confidence/schemas.py` (Implemented)

**Purpose:** Typed contracts for confidence scoring and post-generation routing.

```python
@dataclass
class ConfidenceBreakdown:
    """Three-signal composite confidence breakdown."""
    retrieval_score: float     # Objective: from reranker scores
    llm_score: float           # Subjective: from LLM self-report
    citation_score: float      # Structural: from citation coverage
    composite: float           # Weighted combination
    retrieval_weight: float = 0.50
    llm_weight: float = 0.25
    citation_weight: float = 0.25

class PostGuardrailAction(Enum):
    """Routing action after post-generation confidence evaluation."""
    RETURN = "return"
    RE_RETRIEVE = "re_retrieve"
    FLAG = "flag"
    BLOCK = "block"
```

Design note: `ConfidenceBreakdown` stores weights alongside scores so the breakdown is self-documenting. Any consumer of the breakdown can verify which weights produced the composite without consulting configuration.

#### `src/retrieval/guardrails/types.py` (Phase 0 Contract -- defined in implementation plan)

**Purpose:** Guardrail type contracts for pre-retrieval and post-generation stages.

```python
class RiskLevel(Enum):
    HIGH = "HIGH"      # Incorrect answer = design risk
    MEDIUM = "MEDIUM"  # Incorrect answer = process error
    LOW = "LOW"        # Incorrect answer = inconvenience

class PostGuardrailAction(Enum):
    RETURN = "return"
    RE_RETRIEVE = "re_retrieve"
    FLAG = "flag"
    BLOCK = "block"

@dataclass
class PostGuardrailResult:
    action: PostGuardrailAction
    answer: str
    confidence: ConfidenceBreakdown
    risk_level: RiskLevel
    pii_redactions: list[dict] = field(default_factory=list)
    hallucination_flags: list[str] = field(default_factory=list)
    verification_warning: Optional[str] = None
```

Design note: `PostGuardrailResult` carries all evaluation details (PII redactions, hallucination flags, verification warning) alongside the routing action. This enables the observability layer to log the full evaluation without re-computing any signals.

#### `src/retrieval/formatting/types.py` (Phase 0 Contract -- defined in implementation plan)

**Purpose:** Version conflict detection types and utilities.

```python
@dataclass
class VersionConflict:
    spec_identifier: str    # Spec ID or filename stem
    version_a: str
    date_a: str
    version_b: str
    date_b: str
```

The `detect_version_conflicts()` and `format_conflict_warning()` functions are fully implemented in this file (see Section 3.2 for details).

#### `src/retrieval/observability/types.py` (Phase 0 Contract -- defined in implementation plan)

**Purpose:** Observability type contracts and the `@traced` decorator.

```python
@dataclass
class StageMetrics:
    stage_name: str
    latency_ms: float
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass
class QueryTrace:
    trace_id: str
    risk_level: str
    stages: list[StageMetrics] = field(default_factory=list)
    total_latency_ms: float = 0.0
```

The `start_trace()`, `get_current_trace()`, and `@traced()` functions are fully implemented in this file (see Section 3.7 for details).

---

## 4. End-to-End Data Flow

### Scenario 1: Happy Path -- HIGH Confidence, LOW Risk

**Query:** "What is the recommended decoupling capacitor value for the USB VBUS rail?"
**Risk Level:** LOW (no HIGH or MEDIUM keywords matched)
**Outcome:** Direct answer returned to user.

**Stage 1: Document Formatting**

Input: 5 ranked document chunks with reranker scores [0.92, 0.88, 0.85, 0.71, 0.63]

```python
# State after formatting
{
    "formatted_context": "--- Document 1 ---\nFilename: USB_Power_Design_Guide_v2.pdf\nVersion: v2\nDate: 2025-11-20\nDomain: physical_design\nSection: 3.4 Decoupling Strategy\nSpec ID: USB-PD-001\n\nThe recommended decoupling capacitor for VBUS is 100nF ceramic (X7R) placed within 2mm of the connector pin...\n\n--- Document 2 ---\n...",
    "version_conflicts": [],  # No conflicts detected
}
```

**Stage 2: Generation**

Input: formatted context + user question, assembled via prompt template loader.

```python
# State after generation
{
    "answer": "The recommended decoupling capacitor for the USB VBUS rail is 100nF ceramic (X7R type), placed within 2mm of the connector pin [USB_Power_Design_Guide_v2.pdf, v2, Section 3.4]. For additional bulk decoupling, a 10uF tantalum capacitor is recommended at the input of the voltage regulator [USB_Power_Design_Guide_v2.pdf, v2, Section 3.5]. Confidence: high",
    "llm_confidence": "high",
}
```

**Stage 3: Post-Generation Guardrail**

PII redaction: No PII detected. Output sanitization: No leaks. Hallucination detection: All sentences have valid citations. HIGH risk filtering: Skipped (LOW risk). Confidence routing:

```python
# Confidence breakdown
{
    "retrieval_score": 0.883,   # avg(0.92, 0.88, 0.85)
    "llm_score": 0.85,          # "high" -> 0.85
    "citation_score": 0.92,     # 12/13 sentences cited
    "composite": 0.886,         # 0.50*0.883 + 0.25*0.85 + 0.25*0.92
    "retrieval_weight": 0.50,
    "llm_weight": 0.25,
    "citation_weight": 0.25,
}

# Post-guardrail result
{
    "action": "return",           # composite 0.886 > 0.70, LOW risk
    "answer": "The recommended decoupling capacitor...",
    "confidence": ConfidenceBreakdown(...),
    "risk_level": "LOW",
    "pii_redactions": [],
    "hallucination_flags": [],
    "verification_warning": None,
}
```

**Stage 4: Observability**

```python
# Query trace
{
    "trace_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "risk_level": "LOW",
    "stages": [
        {"stage_name": "document_formatting", "latency_ms": 12.3, "metadata": {"chunk_count": 5, "version_conflicts_detected": 0}},
        {"stage_name": "generation", "latency_ms": 2340.1, "metadata": {"llm_confidence": "high", "token_count": 156}},
        {"stage_name": "post_guardrail", "latency_ms": 87.4, "metadata": {"composite_confidence": 0.886, "citation_coverage": 0.92, "pii_redactions": 0, "routing_action": "return"}},
    ],
    "total_latency_ms": 2439.8,
}
```

**Output to user:** The generated answer with citations, trace ID in response metadata.

---

### Scenario 2: Re-Retrieval Path -- Low Confidence, MEDIUM Risk

**Query:** "What is the signoff checklist for the power intent review?"
**Risk Level:** MEDIUM ("signoff" and "review" are MEDIUM keywords)
**Outcome:** First attempt low confidence, re-retrieve, second attempt succeeds.

**First Attempt -- Stage 1: Document Formatting**

Input: 3 ranked chunks with reranker scores [0.61, 0.52, 0.44]

```python
{
    "formatted_context": "--- Document 1 ---\n...",
    "version_conflicts": [],
}
```

**First Attempt -- Stage 2: Generation**

```python
{
    "answer": "The power intent review checklist includes verifying UPF file completeness and checking supply network connectivity. However, the specific signoff criteria may vary by project. Confidence: medium",
    "llm_confidence": "medium",
}
```

**First Attempt -- Stage 3: Post-Generation Guardrail**

```python
# Confidence breakdown
{
    "retrieval_score": 0.523,    # avg(0.61, 0.52, 0.44)
    "llm_score": 0.55,           # "medium" -> 0.55
    "citation_score": 0.35,      # Weak citation coverage
    "composite": 0.486,          # 0.50*0.523 + 0.25*0.55 + 0.25*0.35
}

# Routing: composite 0.486 < 0.50, retry_count=0 -> RE_RETRIEVE
{
    "action": "re_retrieve",
    "retry_count": 0,  # First attempt
}
```

**Re-Retrieval**: Pipeline loops back to retrieval with broader parameters:
- `search_limit` increased (e.g., 10 -> 20)
- `alpha` shifted toward BM25 (e.g., 0.7 -> 0.4)
- `retry_count` incremented to 1

**Second Attempt -- Stage 1: Document Formatting**

Input: 7 ranked chunks (broader retrieval), reranker scores [0.82, 0.79, 0.74, 0.68, 0.61, 0.55, 0.48]

```python
{
    "formatted_context": "--- Document 1 ---\nFilename: Power_Intent_Review_Checklist_v4.pdf\n...",
    "version_conflicts": [],
}
```

**Second Attempt -- Stage 2: Generation**

```python
{
    "answer": "The signoff checklist for power intent review includes: 1) UPF file completeness verification [Power_Intent_Review_Checklist_v4.pdf, v4, Section 2.1], 2) Supply network connectivity check [Power_Intent_Review_Checklist_v4.pdf, v4, Section 2.2], 3) Isolation cell placement audit [Power_Intent_Review_Checklist_v4.pdf, v4, Section 2.3]... Confidence: high",
    "llm_confidence": "high",
}
```

**Second Attempt -- Stage 3: Post-Generation Guardrail**

```python
# Confidence breakdown
{
    "retrieval_score": 0.783,    # avg(0.82, 0.79, 0.74)
    "llm_score": 0.85,           # "high" -> 0.85
    "citation_score": 0.88,      # Strong citation coverage
    "composite": 0.824,          # 0.50*0.783 + 0.25*0.85 + 0.25*0.88
}

# Routing: composite 0.824 > 0.70, MEDIUM risk -> RETURN
{
    "action": "return",
    "answer": "The signoff checklist for power intent review includes...",
    "verification_warning": None,  # MEDIUM risk, no extra warning
}
```

**Output to user:** The improved answer from the second attempt. Trace includes both attempts.

---

### Scenario 3: Block Path -- Insufficient Documentation

**Query:** "What are the ASIL-D fault coverage requirements for the automotive SoC watchdog timer?"
**Risk Level:** HIGH ("asil", "fault", "safety" are HIGH keywords)
**Outcome:** Blocked after re-retrieval fails to improve confidence.

**First Attempt -- Post-Generation Guardrail**

```python
{
    "retrieval_score": 0.31,     # avg(0.38, 0.29, 0.26) -- poor retrieval
    "llm_score": 0.55,           # "medium" -> 0.55
    "citation_score": 0.15,      # Very low citation coverage
    "composite": 0.330,          # 0.50*0.31 + 0.25*0.55 + 0.25*0.15
}

# Routing: composite 0.330 < 0.50, retry_count=0 -> RE_RETRIEVE
{
    "action": "re_retrieve",
}
```

**Second Attempt (broader retrieval) -- Post-Generation Guardrail**

```python
{
    "retrieval_score": 0.41,     # Slightly improved but still poor
    "llm_score": 0.55,
    "citation_score": 0.22,
    "composite": 0.398,          # 0.50*0.41 + 0.25*0.55 + 0.25*0.22
}

# Routing: composite 0.398 < 0.50, retry_count=1 -> BLOCK
{
    "action": "block",
    "answer": "Insufficient documentation found to answer this query. Please refine your question or consult the source documents directly.",
    "verification_warning": "WARNING: This answer pertains to a HIGH risk domain. VERIFY BEFORE IMPLEMENTATION against authoritative source documents.",
}
```

**Output to user:** The block message with a note that this is a HIGH risk domain. Trace shows both attempts with confidence breakdowns for debugging.

---

## 5. Configuration Reference

All parameters are externalized to configuration files per REQ-903. Changes take effect on restart.

### Confidence Scoring

| Parameter | Type | Default | Valid Range | Effect |
|-----------|------|---------|-------------|--------|
| `confidence.retrieval_weight` | `float` | `0.50` | 0.0--1.0 (must sum to 1.0 with other weights) | Weight for retrieval confidence signal in composite |
| `confidence.llm_weight` | `float` | `0.25` | 0.0--1.0 | Weight for LLM self-reported confidence signal |
| `confidence.citation_weight` | `float` | `0.25` | 0.0--1.0 | Weight for citation coverage signal |
| `confidence.top_n_scores` | `int` | `3` | 1--50 | Number of top reranker scores to average |
| `confidence.min_overlap_words` | `int` | `5` | 1--20 | Minimum consecutive word overlap for n-gram grounding |
| `confidence.llm_high_correction` | `float` | `0.85` | 0.0--1.0 | Numerical score for LLM "high" confidence |
| `confidence.llm_medium_correction` | `float` | `0.55` | 0.0--1.0 | Numerical score for LLM "medium" confidence |
| `confidence.llm_low_correction` | `float` | `0.25` | 0.0--1.0 | Numerical score for LLM "low" confidence |
| `confidence.llm_default` | `float` | `0.50` | 0.0--1.0 | Default score when LLM confidence parsing fails |

### Confidence Routing

| Parameter | Type | Default | Valid Range | Effect |
|-----------|------|---------|-------------|--------|
| `post_generation.high_confidence_threshold` | `float` | `0.70` | 0.0--1.0 | Composite above this: return (or flag if HIGH risk) |
| `post_generation.low_confidence_threshold` | `float` | `0.50` | 0.0--1.0 | Composite below this on retry: block |
| `post_generation.max_retry_count` | `int` | `1` | 0--5 | Maximum re-retrieval attempts |

### Retry

| Parameter | Type | Default | Valid Range | Effect |
|-----------|------|---------|-------------|--------|
| `retry.max_retries` | `int` | `3` | 0--10 | Maximum retry attempts for LLM calls |
| `retry.base_delay` | `float` | `1.0` | 0.1--10.0 seconds | Initial delay between retries |
| `retry.max_delay` | `float` | `30.0` | 1.0--120.0 seconds | Maximum delay cap |
| `retry.backoff_factor` | `float` | `2.0` | 1.0--5.0 | Multiplier for delay between retries |

### PII Detection

| Parameter | Type | Default | Valid Range | Effect |
|-----------|------|---------|-------------|--------|
| `pii.ner_enabled` | `bool` | `false` | true/false | Enable NER-based person name detection |
| `pii.ner_model` | `str` | `""` | Model identifier string | NER model to use when enabled |
| `pii.email_pattern` | `str` | (standard email regex) | Valid regex | Regex for email detection |
| `pii.phone_pattern` | `str` | (standard phone regex) | Valid regex | Regex for phone number detection |
| `pii.ssn_employee_pattern` | `str` | (SSN/employee ID regex) | Valid regex | Regex for SSN and employee ID detection |

### Risk Classification

| Parameter | Type | Default | Valid Range | Effect |
|-----------|------|---------|-------------|--------|
| `risk_taxonomy.HIGH` | `list[str]` | See `config/guardrails.yaml` | List of keyword strings | Keywords that trigger HIGH risk classification |
| `risk_taxonomy.MEDIUM` | `list[str]` | See `config/guardrails.yaml` | List of keyword strings | Keywords that trigger MEDIUM risk classification |

### Observability Alerts

| Parameter | Type | Default | Valid Range | Effect |
|-----------|------|---------|-------------|--------|
| `alerts.confidence_threshold` | `float` | `0.60` | 0.0--1.0 | Alert when average composite drops below |
| `alerts.latency_target_ms` | `float` | `10000` | 1000--60000 | Alert when E2E latency exceeds (ms) |
| `alerts.pii_rate_threshold` | `float` | `0.10` | 0.0--1.0 | Alert when PII detection fraction exceeds |
| `alerts.reretrieval_rate_threshold` | `float` | `0.30` | 0.0--1.0 | Alert when re-retrieval fraction exceeds |

### Prompt Paths

| Parameter | Type | Default | Valid Range | Effect |
|-----------|------|---------|-------------|--------|
| `prompts.system_prompt_path` | `str` | `"prompts/rag_system.md"` | Valid file path | Path to anti-hallucination system prompt |
| `prompts.human_template_path` | `str` | `"prompts/rag_human.md"` | Valid file path | Path to human turn template with placeholders |

---

## 6. Integration Contracts

### Entry Point

The generation and safety subsystem receives control from the reranking stage. The entry point is the document formatting node in the LangGraph pipeline.

### Input Contract

The generation subsystem expects the following fields populated in `RAGPipelineState`:

```python
# Required from upstream (retrieval + reranking stages)
{
    "question": str,                  # Original or reformulated user query
    "ranked_docs": list[dict],        # Reranked document chunks, each with 'text' and 'metadata'
    "reranker_scores": list[float],   # Sigmoid-normalized scores, one per ranked doc
    "risk_level": str,                # "HIGH", "MEDIUM", or "LOW" from pre-retrieval guardrail
    "retry_count": int,               # Current re-retrieval count (starts at 0)
    "trace_id": str,                  # Active trace ID from observability
    "search_alpha": float,            # Current search alpha (may change on re-retrieve)
    "search_limit": int,              # Current search limit (may increase on re-retrieve)
}
```

Each document in `ranked_docs` must have this shape:

```python
{
    "text": str,           # Document chunk content
    "metadata": {
        "filename": str,   # Source document filename
        "version": str,    # Document version identifier
        "date": str,       # Document date (ISO format)
        "domain": str,     # Engineering domain
        "section": str,    # Section heading or number
        "spec_id": str,    # Stable identifier across versions
    }
}
```

### Output Contract

The generation subsystem populates these fields in `RAGPipelineState`:

```python
# Populated by this subsystem
{
    "formatted_context": str,             # Formatted context string injected into LLM
    "version_conflicts": list[dict],      # Detected version conflicts
    "answer": str,                        # Raw LLM answer
    "llm_confidence": str,                # "high", "medium", or "low"
    "composite_confidence": float,        # 3-signal composite score
    "confidence_breakdown": dict,         # Full ConfidenceBreakdown as dict
    "post_guardrail_action": str,         # "return" / "re_retrieve" / "flag" / "block"
    "final_answer": str,                  # After PII redaction + sanitization
    "verification_warning": Optional[str],# For HIGH risk answers
}
```

The answer delivery stage consumes:
- `final_answer`: the cleaned, redacted answer text
- `post_guardrail_action`: determines delivery behavior
- `confidence_breakdown`: included in response metadata
- `verification_warning`: appended to answer if present
- `trace_id`: included in response metadata for debugging

### External Dependency Contracts

**LLM API (via LiteLLM):**
- Endpoint: configurable (local Ollama, OpenAI, Anthropic, etc.)
- Request format: chat completion with `messages` list (system + user)
- Response format: chat completion response with `choices[0].message.content`
- Expected behavior: returns generated text; may timeout or return error codes
- Retry: handled by `with_retry` wrapper (max 3 retries, exponential backoff)
- Fallback on exhaustion: skip generation, return retrieved docs without synthesis

**NER Model (optional, for person name PII detection):**
- Used only when `pii.ner_enabled=true`
- Expected input: text string
- Expected output: list of named entities with type and span
- Fallback on unavailability: degrade to regex-only PII detection

---

## 7. Testing Guide

### Component Testability Map

| Module | Unit-testable | Integration needed | External deps required |
|--------|--------------|-------------------|----------------------|
| `formatting/formatter.py` | Yes (pure dict transform) | No | None |
| `formatting/conflicts.py` | Yes (pure computation) | No | None |
| `formatting/types.py` | Yes (pure computation) | No | None |
| `prompt_loader.py` | Yes (with mock filesystem) | No | Filesystem (mockable) |
| `confidence/scoring.py` | Yes (pure math) | No | None |
| `confidence/schemas.py` | Yes (dataclass) | No | None |
| `confidence/engine.py` | Yes (pure routing logic) | No | None |
| `guardrails/post_generation.py` | Partially (PII regex: yes; NER: needs mock) | Yes (full pipeline flow) | NER model (optional) |
| `observability/types.py` | Yes (decorator + dataclass) | No | None |
| `observability/tracing.py` | Yes (with mock alert dispatch) | Yes (pipeline integration) | Alert backend (mockable) |
| `retry.py` | Yes (with mock time.sleep) | No | None |

### Mock Boundary Catalog

**Must mock:**
- LLM API calls (generation, query processing) -- use deterministic response fixtures
- NER model (when testing person name detection) -- return controlled entity lists
- `time.sleep` in retry tests -- avoid actual delays
- Filesystem for prompt file loading -- use `tmp_path` or `mock.patch`
- Alert dispatch mechanism in observability tests

**Must NOT mock:**
- Confidence scoring math (`compute_composite_confidence`, `compute_retrieval_confidence`, etc.) -- these are the critical calculations; test with real arithmetic
- Regex PII detection -- test actual patterns against real-world PII strings
- Version conflict detection (`detect_version_conflicts`) -- test actual grouping logic
- Citation coverage calculation -- test actual n-gram overlap and citation parsing
- Routing table logic -- test actual threshold comparisons

### Critical Test Scenarios

These scenarios, if broken, cause maximum user-visible damage:

1. **Composite confidence calculation correctness**: Verify that `compute_composite_confidence` with known inputs produces exact expected output. A wrong composite routes every query incorrectly.

2. **Confidence routing at exact threshold boundaries**: Test composite = 0.70 (NOT above threshold, should NOT return for non-HIGH), composite = 0.700001 (above), composite = 0.50 (in re-retrieve range), composite = 0.499999 (below low threshold on retry = BLOCK). Off-by-one on threshold comparison affects every query near the boundary.

3. **PII redaction in generated answers**: Verify email, phone, and employee ID patterns are redacted. A single missed PII pattern is a data handling violation.

4. **System prompt leak prevention**: Generate an answer that contains a substring of the system prompt. Verify the substring is stripped. A leaked system prompt reveals anti-hallucination instructions and injection surface.

5. **Version conflict detection and injection into LLM context**: Two documents with the same spec_id but different versions must produce a conflict warning in the formatted context. Silent version conflicts produce answers based on outdated specs.

6. **HIGH risk answer gets verification warning regardless of confidence**: A HIGH risk answer with composite = 0.95 must still carry "VERIFY BEFORE IMPLEMENTATION". Missing this warning exposes engineers to unverified electrical specifications.

7. **Single re-retrieval retry limit enforcement**: After one re-retrieval (retry_count=1), the system must NOT re-retrieve again. It must escalate to FLAG or BLOCK. Infinite re-retrieval loops cause unbounded latency.

8. **Citation coverage calculation**: An answer where every sentence cites a valid document chunk index must produce high citation coverage. An answer with no citations must produce low coverage. Incorrect coverage feeds directly into the composite score.

9. **LLM confidence overconfidence correction**: "high" must map to 0.85 (not 1.0). Without downward correction, the composite score is biased upward, causing the system to return low-quality answers.

10. **Block action replaces answer entirely**: When routing action is BLOCK, the final answer must be the fallback message, not the generated answer. Returning a low-confidence generated answer defeats the safety purpose.

11. **Template engine safe passthrough**: A document containing `{"voltage": "1.8V"}` must not cause template substitution errors. Template failures crash the generation stage.

12. **Retry exhaustion with fallback**: When all LLM retries fail and a fallback is configured, the fallback must be called. Without this, a transient LLM outage crashes the pipeline instead of degrading gracefully.

### State Invariants

Properties that must be true at every pipeline stage:

- `risk_level` never changes after the pre-retrieval guardrail sets it. All downstream stages read the same risk level.
- `retry_count` never exceeds 1. The re-retrieve loop increments it once, and on the second evaluation, the system must escalate.
- `trace_id` is set once at trace start and never changes. All stage metrics reference the same trace.
- Confidence weights always sum to 1.0. A configuration error that violates this raises `ValueError` before any scoring occurs.
- `final_answer` is never the raw LLM output -- it is always the post-guardrail processed output (PII-redacted, sanitized).
- Every `PostGuardrailResult` has a non-null `action` and `confidence` field. No partially-constructed results escape the guardrail.

### Regression Catalog

Most likely failure modes to watch for:

- **Confidence weight drift**: Weights are changed in config but do not sum to 1.0. Causes `ValueError` at runtime. Add config validation.
- **New PII pattern breaks existing patterns**: A poorly written regex in the PII pattern list causes catastrophic backtracking or matches normal text. Test all patterns individually and measure execution time.
- **System prompt change breaks leak detection**: The system prompt is updated but the leak detection logic still checks against the old prompt. Ensure leak detection reloads the prompt on restart.
- **Reranker score scale change**: If the reranker model is updated and scores shift from [0, 1] to a different range, retrieval confidence calculation produces wrong results. Add a score range assertion.
- **LLM response format change**: If the LLM stops reporting confidence as "high/medium/low" (e.g., returns "High confidence" or "8/10"), parsing defaults to 0.5 for every query. Monitor LLM confidence parse success rate.
- **Template variable collision**: A new template variable is added but conflicts with content in retrieved documents. Test with representative document corpora.
- **N-gram overlap false positives**: Common engineering phrases ("the system must") appear in both the answer and retrieved docs, inflating citation coverage. Consider domain-specific stop phrases.

---

## 8. Operational Notes

### Running

Start the retrieval pipeline with generation enabled:

```bash
# Required environment variables
export LITELLM_MODEL="ollama/llama3"           # LLM model identifier
export LITELLM_API_BASE="http://localhost:11434" # LLM API endpoint
export RAG_CONFIG_PATH="config/"                # Path to configuration directory

# Optional
export NER_ENABLED="false"                      # Enable NER for person name PII detection
export LOG_LEVEL="INFO"                         # Logging verbosity
```

The generation subsystem is enabled by default when the LLM endpoint is reachable. If the LLM is unavailable, the pipeline degrades gracefully: retrieval results are returned without synthesis (per REQ-902).

### Monitoring Signals

**Healthy operation indicators:**
- Average composite confidence: 0.65--0.85 range
- Re-retrieval rate: < 15%
- PII detection rate: < 5% (most answers should not contain PII)
- Generation latency: < 5s median
- Post-guardrail latency: < 500ms median
- Block rate: < 10% (most queries should produce usable answers)

**Degradation indicators:**
- Average composite confidence dropping below 0.60: retrieval quality degradation or LLM quality regression
- Re-retrieval rate exceeding 30%: initial retrieval consistently failing to find relevant documents
- PII detection rate spiking: source document corpus may have been updated with PII-heavy content
- Generation latency exceeding 10s: LLM provider latency issue or model overload
- Block rate exceeding 20%: knowledge base coverage gap for the query domain

### Failure Modes and Debug Paths

**`post_guardrail_action=block` spike:**
1. Check the composite confidence breakdown in recent traces. Which signal is low?
2. If `retrieval_score` is low: retrieval quality problem. Check reranker scores, search parameters, index health.
3. If `citation_score` is low: LLM is generating without citing. Check system prompt for anti-hallucination instructions. Check if prompt template is loading correctly.
4. If `llm_score` is consistently 0.5: LLM confidence parsing is failing. Check LLM response format for confidence reporting.

**Hallucination rate increase (ungrounded sentences):**
1. Check citation coverage in recent traces. Compare against baseline.
2. Check if the system prompt was recently changed. Anti-hallucination instructions may have been weakened.
3. Check if new documents were ingested that the LLM confuses with training data.
4. Check if the LLM model was updated. Different models have different hallucination rates.

**PII detection rate spike:**
1. Check which PII types are being detected (email, phone, person name).
2. If person names: check if NER was recently enabled or the NER model changed.
3. If emails/phones: recent document ingestion may have introduced PII-heavy documents.
4. Check for false positives: engineering terms like "smith chart" may trigger person name NER.

**Re-retrieval rate exceeding 30%:**
1. Check if the query domain shifted (new team, new project).
2. Check if the vector index was recently rebuilt or documents were removed.
3. Check if search parameters changed (alpha, search_limit).
4. Check if reranker model was updated (score distribution shift).

### Specific Log Events

| Event Name | Meaning | When to Investigate |
|------------|---------|-------------------|
| `confidence.weight_validation_failed` | Configured weights do not sum to 1.0 | Immediately -- pipeline cannot score |
| `post_guardrail.pii_redacted` | PII was found and redacted from answer | Routine unless rate spikes |
| `post_guardrail.system_prompt_leak` | System prompt fragment detected in answer | Investigate LLM behavior immediately |
| `post_guardrail.routing.block` | Answer blocked due to low confidence | Check if retrieval quality degraded |
| `post_guardrail.routing.re_retrieve` | Low confidence triggered re-retrieval | Routine unless rate exceeds 30% |
| `post_guardrail.high_risk_unverified_value` | Numerical value in HIGH risk answer not found in sources | Investigate source coverage |
| `retry.exhausted` | All LLM retry attempts failed | Check LLM provider health |
| `retry.fallback_used` | Fallback function called after retry exhaustion | LLM was unavailable; pipeline running in degraded mode |
| `prompt_loader.file_not_found` | Prompt file missing at configured path | Fatal -- generation will not work |
| `tracing.alert.confidence_low` | Average composite confidence below threshold | Review recent query/retrieval quality |
| `tracing.alert.latency_exceeded` | End-to-end latency exceeded target | Check per-stage latencies in trace |
| `tracing.alert.reretrieval_rate_high` | Re-retrieval rate exceeded 30% | Retrieval quality degradation |
| `version_conflict.detected` | Multiple versions of same spec found | Routine -- check if outdated docs should be removed |

---

## 9. Known Limitations

- **PII detection relies on regex + optional NER.** Regex-based detection has false positive rates (e.g., "smith chart" detected as person name by NER) and false negative rates (e.g., PII in non-standard formats like "john dot smith at corp dot com"). Regex patterns do not cover all international phone number formats.

- **Citation coverage is sentence-level.** Granularity limits precision for short answers where a single sentence may contain multiple claims. A sentence with one cited claim and one hallucinated claim receives full credit if the citation marker is present.

- **Re-retrieval uses broadened parameters.** Broadening (increased top-k, shifted alpha, relaxed filters) does not guarantee improved confidence on the second attempt. If the knowledge base does not contain relevant documents, broader retrieval retrieves more irrelevant documents.

- **LLM self-reported confidence is subjective and biased toward overconfidence.** Even with downward correction (mapping "high" to 0.85 instead of 1.0), the LLM's self-assessment does not reflect actual answer quality. This signal is useful only in combination with the two objective signals.

- **Risk classification is keyword-based.** The classifier does not handle semantic risk -- paraphrases of HIGH risk terms (e.g., "power supply voltage" matches "voltage", but "how many volts does it need" does not). Semantic risk classification would require an LLM call, adding latency and cost.

- **System prompt leak detection uses substring matching.** If the LLM paraphrases the system prompt rather than echoing it verbatim, the leak is not detected. Semantic leak detection would require embedding comparison.

- **Version conflict detection relies on filename stems and spec_id.** Documents with non-standard naming conventions (e.g., "draft1.pdf", "final.pdf") are not detected as version conflicts. The filename stem regex handles `_v3` and `_rev2` patterns only.

- **N-gram overlap for citation coverage uses exact word matching.** Synonyms, abbreviations, and rephrasings are not recognized as grounded. The 5-word minimum consecutive overlap threshold filters very short matches but may miss legitimate citations that paraphrase the source.

- **Alerting thresholds are static.** Thresholds are configured once and do not adapt to changing baseline metrics. A healthy system with 5% re-retrieval rate and a system with 25% re-retrieval rate use the same 30% alert threshold.

---

## 10. Extension Guide

### Adding a New Confidence Signal

To add a fourth signal to the composite confidence score (e.g., semantic similarity between answer and retrieved docs):

1. **Define the signal function** in `src/retrieval/confidence/scoring.py`:
   - Create a new function `compute_semantic_similarity(answer, retrieved_texts) -> float` returning [0.0, 1.0].
   - Keep it pure: no I/O, deterministic.

2. **Update the `ConfidenceBreakdown` dataclass** in `src/retrieval/confidence/schemas.py`:
   - Add `semantic_score: float` field.
   - Add `semantic_weight: float = 0.0` field (default 0.0 preserves backward compatibility).

3. **Update `compute_composite_confidence`** in `scoring.py`:
   - Add `semantic_weight` parameter (default 0.0).
   - Add the term `semantic_weight * semantic_score` to the composite calculation.
   - Update the weight validation to check that all four weights sum to 1.0.

4. **Update configuration**:
   - Add `confidence.semantic_weight` to the config file.
   - Adjust existing weights to sum to 1.0 with the new signal.

5. **Update tests**:
   - Add unit tests for the new signal function in `tests/retrieval/test_confidence_scoring.py`.
   - Update composite calculation tests to include the new weight.
   - Add boundary condition tests for the new signal (empty input, all-match, no-match).

6. **Update observability**:
   - The `ConfidenceBreakdown` is logged automatically. The new field appears in traces.

### Adding a New PII Pattern

To add a new PII detection pattern (e.g., credit card numbers):

1. **Add the regex pattern** to `config/guardrails.yaml` (or the PII configuration section):
   ```yaml
   pii_patterns:
     credit_card: '\b(?:\d{4}[-\s]?){3}\d{4}\b'
     placeholder: "[CREDIT_CARD]"
   ```

2. **No code changes required** if the PII detection loop in `post_generation.py` iterates over all patterns in the config. The pattern is loaded at startup.

3. **Add test cases** to `tests/retrieval/test_post_generation_guardrail.py`:
   - Test the new pattern with valid credit card numbers.
   - Test that the pattern does not match non-credit-card 16-digit numbers (e.g., product serial numbers).

4. **Restart the service** for the new pattern to take effect.

### Adding a New Risk Domain

To add a new risk domain (e.g., "CRITICAL" above HIGH):

1. **Update `RiskLevel` enum** in `src/retrieval/guardrails/types.py`:
   ```python
   class RiskLevel(Enum):
       CRITICAL = "CRITICAL"
       HIGH = "HIGH"
       MEDIUM = "MEDIUM"
       LOW = "LOW"
   ```

2. **Update the risk taxonomy** in `config/guardrails.yaml`:
   ```yaml
   risk_taxonomy:
     CRITICAL:
       - "safety critical"
       - "life threatening"
       - "radiation hardened"
   ```

3. **Update the routing table** in `src/retrieval/confidence/engine.py`:
   - Define routing behavior for CRITICAL risk (e.g., always require verification, lower confidence thresholds).

4. **Update `PostGuardrailResult`** and `post_generation.py`:
   - Define what additional checks CRITICAL queries receive.

5. **Update tests**:
   - Add CRITICAL risk classification tests.
   - Add routing tests for CRITICAL risk at all confidence levels.

6. **Update observability**:
   - Ensure the new risk level appears correctly in traces and metrics.

### Adding a New Guardrail Check

To add a new check to the post-generation guardrail (e.g., factual consistency between answer and a knowledge graph):

1. **Implement the check function** in `src/retrieval/guardrails/post_generation.py`:
   ```python
   def _check_kg_consistency(answer: str, kg_facts: list[dict]) -> list[str]:
       """Check answer claims against knowledge graph facts.
       Returns list of inconsistent claims."""
       ...
   ```

2. **Insert the check** into the sequential pipeline in `evaluate_answer()`:
   - Place it after hallucination detection (Step 3) and before confidence routing (Step 5).
   - The check should write its results to the `PostGuardrailResult` (add a new field if needed).

3. **Decide on routing impact**:
   - Does a failed check lower the composite score? Update confidence routing.
   - Does a failed check independently trigger FLAG or BLOCK? Add routing logic.

4. **Update the `PostGuardrailResult` dataclass** in `guardrails/types.py`:
   - Add a field for the new check's output (e.g., `kg_inconsistencies: list[str]`).

5. **Add tests**:
   - Unit test the check function in isolation.
   - Integration test the check within the full guardrail pipeline.
   - Verify that the check's routing impact works correctly.

6. **Update observability**:
   - Add the new check's metrics to the post-guardrail stage metadata.

---

## 11. Memory-Aware Generation Routing

The generation subsystem uses two boolean signals produced by the query processor — `has_backward_reference` and `suppress_memory` — alongside the reranker score distribution to select one of four generation paths. This section documents the full routing matrix, fallback retrieval logic, memory-only generation, BLOCK/FLAG memory filtering, and the `generation_source` field that makes the chosen path observable in the response.

---

### 11.1 Routing Decision Table

The routing decision is made in `rag_chain.run()` after the reranker scores are available. "Strong/moderate retrieval" means the best reranker score exceeds the strong retrieval threshold (default: 0.50). "Weak retrieval" means the best reranker score falls below that threshold.

| `suppress_memory` | Retrieval quality | `has_backward_reference` | `memory_context` | Action | `generation_source` |
|-------------------|-------------------|--------------------------|------------------|--------|---------------------|
| `True` | any | any | any | Use `standalone_query`; strip memory from generation | `"retrieval"` |
| `False` | strong/moderate | `True` | any | Generate from docs + memory | `"retrieval+memory"` |
| `False` | strong/moderate | `False` | non-empty | Generate from docs + memory | `"retrieval+memory"` |
| `False` | strong/moderate | `False` | empty | Generate from docs only | `"retrieval"` |
| `False` | weak | `True` | non-empty | Generate from memory only (skip docs) | `"memory"` |
| `False` | weak | `True` | empty | BLOCK — no memory and no retrieval (fresh conversation guard) | `null` |
| `False` | weak | `False` | any | Standard BLOCK/FLAG path (confidence routing) | `null` |

The fresh-conversation guard (row 6) prevents the memory-generation path from being invoked when `memory_context` is empty. Attempting memory-only generation with no memory content would cause the LLM to hallucinate from training data.

---

### 11.2 Fallback Retrieval

When primary retrieval (on `processed_query`) produces weak scores and `suppress_memory` is `False`, a second retrieval attempt runs on `standalone_query` before the routing decision is finalized.

```
primary_retrieval(processed_query)  -->  best_score < threshold?
                                                  |
                                        secondary_retrieval(standalone_query)
                                                  |
                              compare best scores from both attempts
                                                  |
                              use whichever result set has the higher best score
```

The winning result set is written back to `RAGPipelineState` as `ranked_docs` / `reranker_scores` before routing proceeds. If the secondary attempt also produces weak scores, routing continues into the memory-routing decision matrix above.

Fallback retrieval does not increment `retry_count`. It is a pre-routing probe, not a post-confidence-evaluation re-retrieve.

---

### 11.3 Memory-Generation Path

When routing selects `generation_source="memory"`, the generator receives only `memory_context` and `recent_turns` — no retrieved documents are included in the prompt. The generation call is otherwise identical (same model, same retry wrapper).

After generation, the post-guardrail confidence routing still runs, but with one change: **the RE_RETRIEVE routing action is suppressed on the memory path**. Because there are no viable retrieved documents (that is why this path was selected), re-retrieving again would loop back to the same weak result. Instead, a RE_RETRIEVE outcome is re-routed to FLAG.

The full modified routing table for the memory path:

| Standard action | Memory-path action |
|-----------------|-------------------|
| RETURN | RETURN |
| FLAG | FLAG |
| RE_RETRIEVE | FLAG (re-route) |
| BLOCK | BLOCK |

---

### 11.4 BLOCK/FLAG Memory Filtering

Caller contract: responses where `post_guardrail_action in ("block", "flag")` **must NOT be stored** via `append_turn()` into the conversation memory store.

Rationale: if a blocked or flagged answer is stored as an assistant turn, subsequent memory-aware queries will inject that error response into generation context ("based on what we discussed, the system said..."), propagating incorrect content into future answers. User turns are always stored, regardless of the guardrail outcome.

This is a caller-side responsibility enforced in `rag_chain.run()` before delegating to the memory provider. The memory provider itself does not enforce this — it stores whatever it is given.

---

### 11.5 `generation_source` Field

`generation_source` is a string field set in `RAGPipelineState` by `rag_chain.run()` after the routing decision is made.

| Value | Meaning |
|-------|---------|
| `"retrieval"` | Answer generated from retrieved documents only |
| `"retrieval+memory"` | Answer generated from retrieved documents and injected conversation memory |
| `"memory"` | Answer generated from conversation memory only (no retrieved documents) |
| `null` | Pipeline did not reach generation (BLOCK, or guardrail rejection upstream) |

`generation_source` is included in the response metadata. Clients and observability dashboards can use this field to distinguish answer provenance and detect shifts in routing distribution (e.g., an unexpected spike in `"memory"` responses may indicate retrieval degradation).

---

## Appendix: Requirement Coverage

| Spec Requirement | Covered By |
|------------------|------------|
| REQ-501 (Structured metadata on chunks) | Section 3.1 — `src/retrieval/formatting/formatter.py` |
| REQ-502 (Version conflict detection) | Section 3.2 — `src/retrieval/formatting/conflicts.py` + `formatting/types.py` |
| REQ-503 (Deterministic formatted context) | Section 3.1 — `src/retrieval/formatting/formatter.py` |
| REQ-601 (Anti-hallucination system prompt) | Section 3.3 — `src/retrieval/prompt_loader.py` |
| REQ-602 (Safe template engine for prompts) | Section 3.3 — `src/retrieval/prompt_loader.py` |
| REQ-603 (Source citation format enforcement) | Section 3.6 — `src/retrieval/guardrails/post_generation.py` (hallucination detection) |
| REQ-604 (LLM confidence extraction with correction) | Section 3.4 — `src/retrieval/confidence/scoring.py` |
| REQ-605 (Retry with exponential backoff) | Section 3.8 — `src/retrieval/retry.py` |
| REQ-701 (3-signal composite confidence) | Section 3.4 — `src/retrieval/confidence/scoring.py` + Section 3.5 — `confidence/engine.py` |
| REQ-702 (Hallucination detection / grounding check) | Section 3.6 — `src/retrieval/guardrails/post_generation.py` |
| REQ-703 (PII redaction from answers) | Section 3.6 — `src/retrieval/guardrails/post_generation.py` |
| REQ-704 (Output sanitization — prompt leak, artifacts) | Section 3.6 — `src/retrieval/guardrails/post_generation.py` |
| REQ-705 (HIGH risk numerical claim verification) | Section 3.6 — `src/retrieval/guardrails/post_generation.py` |
| REQ-706 (Confidence routing: return/re-retrieve/flag/block) | Section 3.5 — `src/retrieval/confidence/engine.py` + Section 3.6 — `post_generation.py` |
| REQ-801 (End-to-end trace with unique ID) | Section 3.7 — `src/retrieval/observability/tracing.py` + `observability/types.py` |
| REQ-802 (Per-stage metrics capture) | Section 3.7 — `src/retrieval/observability/tracing.py` + `observability/types.py` |
| REQ-803 (Alerting thresholds) | Section 3.7 — `src/retrieval/observability/tracing.py` |
| REQ-901 (Per-stage latency targets) | Section 3.7 — `src/retrieval/observability/tracing.py` (latency capture) + Section 5 — Configuration Reference |
| REQ-902 (Graceful degradation) | Section 3.8 — `src/retrieval/retry.py` (fallback mechanism) + Section 3.6 — `post_generation.py` (safe defaults) |
| REQ-903 (All config externalized) | Section 5 — Configuration Reference (all parameters externalized) |
