# Retrieval Pipeline — Generation and Safety Specification

**AION Knowledge Management Platform**
Version: 1.3 | Status: Draft | Domain: Retrieval Pipeline — Generation

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-03-11 | AI Assistant | Initial draft — 8-stage pipeline with 39 requirements |
| 1.1 | 2026-03-13 | AI Assistant | Performance budget cross-reference |
| 1.2 | 2026-03-17 | AI Assistant | Split from monolithic RETRIEVAL_SPEC.md. This file covers document formatting, generation, post-generation guardrails, observability, and NFR (sections 7-11, REQ-501 through REQ-903). For query processing and retrieval, see RETRIEVAL_QUERY_SPEC.md. |
| 1.3 | 2026-03-27 | AI Assistant | Added memory-aware generation routing section (REQ-1201–1207): fallback retrieval, memory-generation path, BLOCK/FLAG memory filtering, generation source tracking |

> **Document intent:** This is a normative requirements/specification document for the **generation, safety, and observability** stages of the retrieval pipeline.
> For query processing, retrieval, and reranking, see `RETRIEVAL_QUERY_SPEC.md`.
> For currently implemented runtime behavior, refer to `RETRIEVAL_ENGINEERING_GUIDE.md`, `RETRIEVAL_NEW_ENGINEER_ONBOARDING_CHECKLIST.md`, and `src/retrieval/README.md`.

---

## 7. Document Formatting

> **REQ-501** | Priority: MUST
> **Description:** Every document chunk injected into the LLM context MUST carry structured metadata. The metadata MUST include at minimum:
>
> - Filename (source document name)
> - Version (document version identifier)
> - Date (document date, ISO format)
> - Domain (e.g., physical_design, verification, dft, frontend)
> - Section (section heading or number within the document)
> - Spec ID (stable identifier across versions, if available)
>
> Metadata MUST be formatted in a consistent, parseable structure within the context string.
> **Rationale:** Structured metadata enables the LLM to cite accurately (filename, version, section). It also enables the post-generation guardrail to verify citations against source metadata.
> **Acceptance Criteria:** Each document chunk in the LLM context includes all required metadata fields. A missing field is populated with "unknown" rather than omitted. The format is consistent across all chunks.

> **REQ-502** | Priority: MUST
> **Description:** The system MUST detect version conflicts before generation. When two or more retrieved documents share the same specification ID (or filename stem) but differ in version, the system MUST:
>
> 1. Flag the conflict in the pipeline state
> 2. Include the conflict information in the LLM prompt
> 3. Surface the conflict to the user in the final response
>
> The LLM MUST NOT silently resolve version conflicts.
> **Rationale:** In engineering workflows, specifications evolve across tape-out cycles. Silently choosing one version over another when both are retrieved can produce answers based on outdated or incorrect parameters.
> **Acceptance Criteria:** When documents from Power_Spec_v2.pdf and Power_Spec_v3.pdf are both retrieved, the system flags a version conflict. The generated answer includes a note about the conflict. The user sees which versions were found.

> **REQ-503** | Priority: MUST
> **Description:** The system MUST prepare a formatted context string for LLM injection that includes all retrieved chunks with their metadata and any version conflict flags. The format MUST be deterministic (same input produces same output).
> **Rationale:** A well-structured context string improves LLM citation accuracy and makes hallucination detection more reliable.
> **Acceptance Criteria:** The context string follows a documented format specification. Chunks are numbered sequentially. Metadata precedes content for each chunk. Version conflicts appear as explicit warnings in the context string.

---

## 8. Generation

> **REQ-601** | Priority: MUST
> **Description:** The system MUST use an anti-hallucination system prompt that instructs the LLM to:
>
> 1. Answer ONLY from the provided retrieved documents
> 2. Never use training data or prior knowledge
> 3. Cite sources using a specified format (e.g., `[Filename, Version, Section]`)
> 4. Explicitly state when information is insufficient rather than guessing
> 5. Report its confidence level (high, medium, low) as part of the response
> **Rationale:** Without explicit anti-hallucination instructions, LLMs default to generating plausible-sounding text from training data. In engineering contexts, a hallucinated specification is a design risk.
> **Acceptance Criteria:** The system prompt is stored as a separate file (not inline code). It contains all five instruction categories above. Changing the prompt does not require code changes.

> **REQ-602** | Priority: SHOULD
> **Description:** The system SHOULD use a template engine for prompt construction that safely handles variable injection. The template MUST NOT interpret content within retrieved documents as template variables (e.g., curly braces `{}` in JSON snippets within documents MUST NOT be treated as template placeholders).
> **Rationale:** Retrieved documents frequently contain JSON, YAML, code snippets, and other content with curly braces. Naive string formatting (f-strings, `.format()`) will break or produce incorrect prompts when documents contain `{key}` patterns.
> **Acceptance Criteria:** A retrieved document containing `{"voltage": "1.8V"}` does not cause a template error or variable substitution. Only explicitly declared template variables are substituted.

> **REQ-603** | Priority: MUST
> **Description:** The system MUST enforce a source citation format in generated answers. Each claim in the answer MUST reference a specific retrieved document using an identifier that the user can trace back to the source. The citation format MUST include at minimum: filename and section.
> **Rationale:** Citations make hallucination detectable. An engineer can verify a claim by checking the cited source. Without citations, there is no way to distinguish grounded claims from hallucinated ones.
> **Acceptance Criteria:** Every factual claim in a generated answer includes a citation. Citations are traceable to a specific retrieved document chunk. Answers without citations are flagged by the post-generation guardrail.

> **REQ-604** | Priority: MUST
> **Description:** The system MUST extract a self-reported confidence level from the LLM's response. The LLM is instructed to report confidence as "high", "medium", or "low". This value MUST be parsed from the response and mapped to a numerical score for use in the composite confidence calculation.
> **Rationale:** LLM self-reported confidence is one of three signals in the composite confidence score. While LLMs tend toward overconfidence, this signal provides useful information when combined with objective signals.
> **Acceptance Criteria:** The confidence level is reliably extracted from LLM responses. A downward correction is applied to account for overconfidence bias (e.g., "high" maps to 0.85, not 1.0). Parsing failures default to a neutral score (0.5).

> **REQ-605** | Priority: MUST
> **Description:** The system MUST implement retry logic with exponential backoff for all external LLM calls (generation and query processing). The retry configuration MUST include:
>
> - Maximum number of retries (configurable, default 3)
> - Base backoff interval (configurable)
> - Maximum backoff cap
> - Graceful fallback when all retries are exhausted
> **Rationale:** A single network hiccup or LLM provider timeout should not kill the entire query. Retry logic with backoff handles transient failures without overwhelming the service.
> **Acceptance Criteria:** A transient timeout on the first attempt is retried automatically. Backoff intervals increase between retries. After all retries are exhausted, the system returns a graceful error (not a crash). Retry count and intervals are configurable.

> **Implementation note (memory echo suppression):** When `retrieval_quality` is `"weak"` or `"insufficient"`, the `recent_turns` (verbatim conversation history turns) MUST be suppressed (set to `None`) before being passed to the generator. The `memory_context` (rolling summary) is still passed regardless of retrieval quality. This prevents the LLM from echoing prior answers when retrieved context is poor. See conversation memory requirements REQ-1001–REQ-1008 in `RETRIEVAL_QUERY_SPEC.md`.

---

## 8a. Memory-Aware Generation & Retrieval Routing

*Note: IDs in this section increment by 2 (odd-numbered). Even-numbered IDs REQ-1202, REQ-1206, REQ-1208 are reserved for future requirements within this section. REQ-1204 is assigned.*

> **REQ-1201** | Priority: MUST
> **Description:** When the primary retrieval (using `processed_query`) returns weak or insufficient results (retrieval quality below the "moderate" threshold) AND `suppress_memory` is False, the system MUST execute a fallback retrieval using the `standalone_query`. The system MUST use whichever retrieval produces higher-quality results (as measured by the best reranker score from each retrieval pass).
> **Rationale:** Memory-enriched query reformulation can over-narrow the search query by injecting irrelevant prior context. The standalone query, reformulated without memory, serves as a hedge. Running fallback retrieval only when the primary fails keeps the cost marginal (~20-30% of conversational queries).
> **Acceptance Criteria:** Given a memory-enriched query "component X SPI clock frequency timing" that returns weak retrieval, the system automatically retries with the standalone query "clock frequency specification". If the standalone retrieval returns moderate or strong results, those results are used for generation. Fallback retrieval does NOT run when primary retrieval is strong/moderate. Fallback retrieval does NOT run when `suppress_memory` is True (standalone_query was already the primary).

> **REQ-1203** | Priority: MUST
> **Description:** When ALL retrieval passes (primary and fallback) return weak or insufficient results AND the query has `has_backward_reference = True`, the system MUST generate from conversation memory context (`memory_context` + `recent_turns`) without document context. When `has_backward_reference` is True but both `memory_context` and `recent_turns` are empty (fresh conversation with no prior turns), the memory-generation path MUST NOT be taken; the system MUST fall through to the standard weak-retrieval behavior (BLOCK per REQ-706). When confidence routing is applied to a memory-generated answer, the re-retrieval step from REQ-706 is skipped — there are no documents to re-retrieve in a memory-only context; routing proceeds directly to BLOCK if composite confidence is below 0.50, or FLAG if between 0.50 and 0.70. This memory-generation path MUST still apply confidence routing (REQ-706) to the output — the confidence routing safety net is never bypassed.
> **Rationale:** Backward-reference queries ("tell me more about the above") cannot be answered from document retrieval — they reference conversation history. Without a memory-generation path, these queries are incorrectly BLOCK'd. Confidence routing on the memory-generated answer ensures low-quality memory answers are still caught.
> **Acceptance Criteria:** Given the query "Tell me more about the above" with prior conversation about SPI timing, when retrieval returns weak results, the system generates from memory context. The generated answer references prior conversation content. Confidence routing still runs on the memory-generated answer. If the memory-generated answer has composite confidence below 0.50, it is still BLOCK'd. Given a fresh conversation (empty memory) with query 'Tell me more about the above' where `has_backward_reference = True`, the system does NOT attempt memory-generation and returns BLOCK instead. Given a memory-generated answer with composite confidence 0.55, the system FLAGs (not re-retrieves) because re-retrieval is not applicable on the memory-generation path.

> **REQ-1204** | Priority: MUST
> **Description:** When `has_backward_reference` is True AND primary or fallback retrieval returns strong or moderate results, the system MUST use the standard retrieval-generation path with both retrieved documents AND conversation memory context (`memory_context` + `recent_turns`) in the generation prompt. The memory-generation path (REQ-1203) MUST NOT be triggered when retrieval quality is strong or moderate, regardless of the backward-reference signal.
> **Rationale:** A query like "Based on what we discussed, what does the spec say about timing?" has a backward reference but also needs document retrieval. When retrieval succeeds, using documents plus memory produces a better answer than memory alone. The retrieval-first architecture means retrieval quality always takes priority over backward-reference detection.
> **Acceptance Criteria:** Given the query "Based on what we discussed, what does the spec say about timing?" with `has_backward_reference = True` and strong retrieval results, the system generates from retrieved documents plus memory context. The memory-generation path is not triggered. The `generation_source` is "retrieval+memory".

> **REQ-1205** | Priority: MUST
> **Description:** When `suppress_memory` is True (context-reset detected by query processor), the system MUST use `standalone_query` as the primary and only retrieval query. The system MUST NOT inject `memory_context` or `recent_turns` into the generation prompt. No fallback retrieval is attempted (the standalone query IS the primary).
> **Rationale:** When the user explicitly requests a context reset ("forget about past convo"), injecting conversation history contradicts their intent. Using standalone_query ensures retrieval is not polluted by irrelevant prior context, and excluding memory from generation prevents the LLM from referencing prior turns.
> **Acceptance Criteria:** Given "Forget about past conversation, what's the timing spec for Y?" with `suppress_memory = True`, retrieval uses only the standalone query. The generation prompt contains no conversation history. The generated answer does not reference prior conversation turns.

> **REQ-1207** | Priority: MUST
> **Description:** Responses where `post_guardrail_action` is "block" or "flag" MUST NOT be stored in conversation memory. The response MUST still be displayed to the user (with appropriate warning for "flag" responses), but the caller MUST skip the `append_turn()` call for the assistant response. User turns MUST always be stored regardless of the response action.
> **Rationale:** Storing BLOCK messages ("Insufficient documentation found...") and FLAG warnings in conversation memory causes error echo accumulation: subsequent queries see the error message in `recent_turns` and the LLM reproduces it. By excluding unreliable responses from memory, future turns start with clean context.
> **Acceptance Criteria:** After a BLOCK response to "Who is Sam Altman?", the next query "What is the moon size?" does not contain "Insufficient documentation found" in its memory context. The BLOCK response was displayed to the user but not stored. The user's query "Who is Sam Altman?" IS stored (user turns always persist). FLAG responses are displayed with their warning but also excluded from memory storage.

> **REQ-1209** | Priority: SHOULD
> **Description:** The `RAGResponse` SHOULD include a `generation_source` field indicating which context was used for generation: `"retrieval"` (documents from primary or fallback retrieval), `"memory"` (conversation history via memory-generation path), or `"retrieval+memory"` (documents plus memory context). When generation is skipped (BLOCK with no generation), the field SHOULD be `null`.
> **Rationale:** Downstream consumers (CLI, API, monitoring) need to know which path produced the answer for display, debugging, and quality tracking. The generation source also enables differentiated confidence thresholds per source type in future iterations.
> **Acceptance Criteria:** A response generated from retrieved documents has `generation_source = "retrieval"`. A response from the memory-generation path has `generation_source = "memory"`. A response where both memory and documents were in the prompt has `generation_source = "retrieval+memory"`. A BLOCK response has `generation_source = null`.

---

## 9. Post-Generation Guardrail

> **REQ-701** | Priority: MUST
> **Description:** The system MUST compute a composite confidence score from three independent signals:
>
> | Signal | Weight | Source | Objectivity |
> |--------|--------|--------|-------------|
> | Retrieval Confidence | 0.50 | Top-3 reranker score average | Objective |
> | LLM Self-Reported Confidence | 0.25 | Extracted from LLM response | Subjective |
> | Citation Coverage | 0.25 | Fraction of answer sentences grounded in retrieved quotes | Structural |
>
> The weights MUST be configurable. The combined score MUST be in the range 0.0–1.0.
> **Rationale:** No single signal is reliable alone. Reranker scores measure retrieval quality but not generation quality. LLM confidence is useful but biased. Citation coverage measures structural grounding. Combining all three produces a more robust confidence estimate.
> **Acceptance Criteria:** The composite score is computed for every generated answer. Changing the weights in configuration changes the composite score. Each individual signal is logged alongside the composite for debugging.

> **REQ-702** | Priority: MUST
> **Description:** The system MUST verify that claims in the generated answer are grounded in the retrieved documents. Every factual sentence in the answer SHOULD be traceable to a specific retrieved chunk. Sentences that cannot be traced to any retrieved document MUST be flagged.
> **Rationale:** This is the primary hallucination detection mechanism. If the LLM generates content not present in the retrieved context, it is hallucinating from training data.
> **Acceptance Criteria:** The system computes citation coverage (fraction of answer sentences with matching retrieved content). Answers with citation coverage below a configurable threshold are flagged. Flagged answers trigger the confidence routing logic (re-retrieve or escalate).

> **REQ-703** | Priority: MUST
> **Description:** The system MUST detect and redact PII from generated answers before they reach the user. PII detection MUST cover at minimum:
>
> - Email addresses (regex)
> - Phone numbers (regex)
> - Social security numbers / employee IDs (regex)
> - Person names (named entity recognition)
>
> Detected PII MUST be replaced with typed placeholders (e.g., `[EMAIL]`, `[PHONE]`, `[PERSON]`).
> **Rationale:** Retrieved documents may contain PII (author names, contact information, employee references). The LLM may surface this PII in generated answers. PII in answers is a data handling violation regardless of whether the source documents are internal.
> **Acceptance Criteria:** An answer containing "Contact <john.smith@company.com> for details" is redacted to "Contact [EMAIL] for details". PII detection runs on every generated answer. Redactions are logged for audit.

> **REQ-704** | Priority: MUST
> **Description:** The system MUST sanitize generated output to remove:
>
> - Leaked system prompt fragments
> - Internal metadata or formatting artifacts
> - Template variable names or placeholders that were not substituted
> - Raw document chunk boundaries or markers
> **Rationale:** LLMs occasionally echo system prompt content or internal formatting in their output. Leaking the system prompt reveals anti-hallucination instructions and injection patterns.
> **Acceptance Criteria:** The generated answer does not contain any substring from the system prompt. Internal markers (e.g., `--- Document 3 ---`) are stripped from the final output.

> **REQ-705** | Priority: SHOULD
> **Description:** For queries classified as HIGH risk (per REQ-203), the system SHOULD apply additional output filtering:
>
> - Numerical values (voltages, frequencies, temperatures, timing values) that do not have an exact quote match in a retrieved document SHOULD be flagged or suppressed
> - The answer SHOULD include a verification warning (e.g., "VERIFY BEFORE IMPLEMENTATION")
> **Rationale:** In HIGH risk domains (electrical specifications, safety compliance), an incorrect number is not a UX problem — it is a design risk. Requiring exact quote matches for numerical claims adds a safety margin.
> **Acceptance Criteria:** A HIGH risk answer containing "The voltage is 3.3V" where no retrieved document contains "3.3V" is flagged. The flag is visible to the user. LOW risk answers are not subject to this additional filtering.

> **REQ-706** | Priority: MUST
> **Description:** The system MUST route based on the composite confidence score and risk level:
>
> | Composite Score | Risk Level | Action |
> |----------------|------------|--------|
> | > 0.70 | LOW or MEDIUM | Return answer to user |
> | > 0.70 | HIGH | Return answer with verification warning |
> | 0.50–0.70 | Any | Re-retrieve with broader parameters (one retry) |
> | < 0.50 | Any | Do not return generated answer; return "Insufficient documentation found" |
>
> Re-retrieval MUST be attempted at most once. If re-retrieval does not improve confidence above the threshold, the system MUST escalate (flag for review or return insufficient documentation message).
> **Rationale:** This routing logic ensures that low-confidence answers are never silently returned to the user. The single retry with broader parameters gives the system one chance to recover before giving up.
> **Acceptance Criteria:** An answer with composite confidence 0.45 triggers re-retrieval. If re-retrieval produces confidence 0.72, the answer is returned. If re-retrieval produces confidence 0.48, the system returns "Insufficient documentation found". HIGH risk answers always include a verification warning regardless of confidence.
>
> **Implementation note (FLAG action — display compatibility):** When the routing action is FLAG, the `verification_warning` text is appended directly to `generated_answer` as a visible block (`\n\n---\n⚠️ <warning text>`), in addition to being stored in the structured `verification_warning` field. This ensures the warning is visible to any display layer that renders only the answer text.

---

## 10. Observability

> **REQ-801** | Priority: MUST
> **Description:** The system MUST produce an end-to-end trace for every query processed. The trace MUST include a unique trace ID, the risk level, and a record for each pipeline stage.
> **Rationale:** Without tracing, there is no way to diagnose why a specific query produced a bad answer. Was it poor retrieval? Bad reranking? LLM hallucination? Tracing makes the failure mode visible.
> **Acceptance Criteria:** Every query response includes a trace ID. The trace is retrievable by ID and shows all pipeline stages with their inputs, outputs, and timing.

> **REQ-802** | Priority: MUST
> **Description:** The system MUST capture per-stage metrics for every query:
>
> | Stage | Metrics |
> |-------|---------|
> | Query Processing | Reformulation count, confidence score, action taken |
> | Pre-Retrieval Guardrail | Validation pass/fail, risk classification, PII detections |
> | Retrieval | Search latency, result count, filter hit rate, KG expansion terms |
> | Reranking | Score distribution (min, max, mean), top-1 score |
> | Document Formatting | Chunk count, version conflicts detected |
> | Generation | Generation latency, LLM confidence, token count |
> | Post-Generation Guardrail | Composite confidence, citation coverage, PII redactions, routing action |
>
> **Rationale:** These metrics enable trend analysis, regression detection, and targeted optimization.
> **Acceptance Criteria:** All listed metrics are captured and available for querying/dashboarding. Metrics are structured (key-value, not embedded in log messages).

> **REQ-803** | Priority: SHOULD
> **Description:** The system SHOULD define alerting thresholds for key metrics and trigger alerts when thresholds are breached:
>
> - Average composite confidence drops below 0.60
> - End-to-end latency exceeds configurable target
> - PII detection rate exceeds baseline (potential data quality issue)
> - Re-retrieval rate exceeds 30% (retrieval quality degradation)
> **Rationale:** Automated alerts surface systemic problems before users report them.
> **Acceptance Criteria:** Alerts are triggered when thresholds are breached. Alerts include the metric name, current value, threshold, and time window.

---

## 11. Non-Functional Requirements

> **Note:** Performance-specific requirements (fast-path routing, per-stage timeout budgets, evaluation harness, load testing, and capacity validation) are defined in the companion document `docs/performance/RAG_RETRIEVAL_PERFORMANCE_SPEC.md`. Requirements in this section cover general pipeline non-functional concerns.

> **REQ-901** | Priority: SHOULD
> **Description:** The system SHOULD meet the following latency targets for each pipeline stage under standard load:
>
> | Stage | Target Latency |
> |-------|---------------|
> | Query Processing | < 2s |
> | Pre-Retrieval Guardrail | < 100ms |
> | Retrieval (search) | < 500ms |
> | Reranking | < 1s |
> | Document Formatting | < 50ms |
> | Generation | < 5s |
> | Post-Generation Guardrail | < 500ms |
> | **Total end-to-end** | **< 10s** |
>
> **Rationale:** Interactive usage requires responsive answers. Each stage has a latency budget proportional to its computational complexity.
> **Acceptance Criteria:** Median latency per stage is measured and compared against targets. P95 latency is also tracked.

> **REQ-902** | Priority: MUST
> **Description:** The system MUST degrade gracefully when optional components are unavailable:
>
> | Component Unavailable | Degraded Behavior |
> |----------------------|-------------------|
> | External LLM (generation) | Return retrieved documents without synthesis; skip generation |
> | External LLM (query processing) | Use heuristic confidence scoring; skip reformulation |
> | Knowledge Graph | Skip KG expansion; use original query for BM25 |
> | Embedding cache | Recompute embeddings (slower, but functional) |
> | Query result cache | Recompute full pipeline (slower, but functional) |
>
> The system MUST NOT crash or return an unhandled error when any single optional component is unavailable.
> **Rationale:** In production, components fail. The pipeline must continue operating in a degraded but functional state rather than failing entirely.
> **Acceptance Criteria:** Each degradation scenario is tested. The system logs a warning when operating in degraded mode. The response indicates which components were unavailable.

> **REQ-903** | Priority: MUST
> **Description:** All configurable thresholds, weights, patterns, and parameters MUST be externalized to configuration files (not hardcoded in source code). Changes to configuration MUST take effect on restart without code changes.
>
> Configuration categories:
>
> - Search parameters (alpha, search_limit, rerank_top_k)
> - Confidence thresholds and weights
> - Risk classification taxonomy
> - Injection detection patterns
> - PII detection patterns
> - Retry parameters (count, backoff intervals)
> - Latency targets
> - Cache sizes and TTLs
> **Rationale:** Hardcoded values require code changes and redeployment to tune. Externalized configuration enables rapid iteration on retrieval quality without engineering cycles.
> **Acceptance Criteria:** Every threshold, weight, and pattern referenced in this specification is loaded from a configuration file. The configuration file format is documented. Missing configuration values fall back to documented defaults.

---

## 12. Requirements Traceability Matrix

| REQ ID | Section | Priority | Pipeline Stage |
|--------|---------|----------|---------------|
| REQ-101 | 3 | MUST | Query Processing |
| REQ-102 | 3 | MUST | Query Processing |
| REQ-103 | 3 | SHOULD | Query Processing |
| REQ-104 | 3 | MUST | Query Processing |
| REQ-201 | 4 | MUST | Pre-Retrieval Guardrail |
| REQ-202 | 4 | MUST | Pre-Retrieval Guardrail |
| REQ-203 | 4 | MUST | Pre-Retrieval Guardrail |
| REQ-204 | 4 | SHOULD | Pre-Retrieval Guardrail |
| REQ-205 | 4 | MUST | Pre-Retrieval Guardrail |
| REQ-301 | 5 | MUST | Retrieval |
| REQ-302 | 5 | MUST | Retrieval |
| REQ-303 | 5 | MUST | Retrieval |
| REQ-304 | 5 | MAY | Retrieval |
| REQ-305 | 5 | MUST | Retrieval |
| REQ-306 | 5 | SHOULD | Retrieval |
| REQ-307 | 5 | SHOULD | Retrieval |
| REQ-308 | 5 | SHOULD | Retrieval |
| REQ-401 | 6 | MUST | Reranking |
| REQ-402 | 6 | MUST | Reranking |
| REQ-403 | 6 | MUST | Reranking |
| REQ-501 | 7 | MUST | Document Formatting |
| REQ-502 | 7 | MUST | Document Formatting |
| REQ-503 | 7 | MUST | Document Formatting |
| REQ-601 | 8 | MUST | Generation |
| REQ-602 | 8 | SHOULD | Generation |
| REQ-603 | 8 | MUST | Generation |
| REQ-604 | 8 | MUST | Generation |
| REQ-605 | 8 | MUST | Generation |
| REQ-701 | 9 | MUST | Post-Generation Guardrail |
| REQ-702 | 9 | MUST | Post-Generation Guardrail |
| REQ-703 | 9 | MUST | Post-Generation Guardrail |
| REQ-704 | 9 | MUST | Post-Generation Guardrail |
| REQ-705 | 9 | SHOULD | Post-Generation Guardrail |
| REQ-706 | 9 | MUST | Post-Generation Guardrail |
| REQ-801 | 10 | MUST | Observability |
| REQ-802 | 10 | MUST | Observability |
| REQ-803 | 10 | SHOULD | Observability |
| REQ-901 | 11 | SHOULD | Non-Functional |
| REQ-902 | 11 | MUST | Non-Functional |
| REQ-903 | 11 | MUST | Non-Functional |
| REQ-1001 | 3a | MUST | Conversation Memory |
| REQ-1002 | 3a | MUST | Conversation Memory |
| REQ-1003 | 3a | SHOULD | Conversation Memory |
| REQ-1004 | 3a | MUST | Conversation Memory |
| REQ-1005 | 3a | MUST | Conversation Memory |
| REQ-1006 | 3a | MUST | Conversation Memory |
| REQ-1007 | 3a | SHOULD | Conversation Memory |
| REQ-1008 | 3a | SHOULD | Conversation Memory |
| REQ-1201 | 8a | MUST | Memory-Aware Generation Routing |
| REQ-1203 | 8a | MUST | Memory-Aware Generation Routing |
| REQ-1204 | 8a | MUST | Memory-Aware Generation Routing |
| REQ-1205 | 8a | MUST | Memory-Aware Generation Routing |
| REQ-1207 | 8a | MUST | Memory-Aware Generation Routing |
| REQ-1209 | 8a | SHOULD | Memory-Aware Generation Routing |

**Total Requirements: 53** (MUST: 38, SHOULD: 13, MAY: 1)

---

## Generation and Safety Requirements Traceability Matrix

| REQ ID | Section | Priority | Pipeline Stage |
|--------|---------|----------|---------------|
| REQ-501 | 7 | MUST | Document Formatting |
| REQ-502 | 7 | MUST | Document Formatting |
| REQ-503 | 7 | MUST | Document Formatting |
| REQ-601 | 8 | MUST | Generation |
| REQ-602 | 8 | SHOULD | Generation |
| REQ-603 | 8 | MUST | Generation |
| REQ-604 | 8 | MUST | Generation |
| REQ-605 | 8 | MUST | Generation |
| REQ-701 | 9 | MUST | Post-Generation Guardrail |
| REQ-702 | 9 | MUST | Post-Generation Guardrail |
| REQ-703 | 9 | MUST | Post-Generation Guardrail |
| REQ-704 | 9 | MUST | Post-Generation Guardrail |
| REQ-705 | 9 | SHOULD | Post-Generation Guardrail |
| REQ-706 | 9 | MUST | Post-Generation Guardrail |
| REQ-801 | 10 | MUST | Observability |
| REQ-802 | 10 | MUST | Observability |
| REQ-803 | 10 | SHOULD | Observability |
| REQ-901 | 11 | SHOULD | Non-Functional |
| REQ-902 | 11 | MUST | Non-Functional |
| REQ-903 | 11 | MUST | Non-Functional |
| REQ-1201 | 8a | MUST | Memory-Aware Generation Routing |
| REQ-1203 | 8a | MUST | Memory-Aware Generation Routing |
| REQ-1204 | 8a | MUST | Memory-Aware Generation Routing |
| REQ-1205 | 8a | MUST | Memory-Aware Generation Routing |
| REQ-1207 | 8a | MUST | Memory-Aware Generation Routing |
| REQ-1209 | 8a | SHOULD | Memory-Aware Generation Routing |

**Total Requirements: 26** (MUST: 20, SHOULD: 5, MAY: 0)

For query processing, retrieval, memory, and reranking requirements, see `RETRIEVAL_QUERY_SPEC.md`.
