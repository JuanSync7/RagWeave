# Sections 5, 6, 7 & 8 — Ingestion and Retrieval Pipelines

**AION Knowledge Management Platform**
*Draft content for integration into the main system specification.*

> **Note on section numbering:** Splitting the original Section 5 into two dedicated ingestion sections and splitting the original RAG Retrieval section into two dedicated retrieval sections shifts the downstream numbering. Document Processing is Section 5, Embedding Pipeline is Section 6, RAG Retrieval (Query & Retrieval) is Section 7, RAG Retrieval (Generation & Safety) is Section 8, User Interface becomes Section 9, and so on.

---

## 5. Document Processing Pipeline

> **Content moved.** The full conceptual overview of the Document Processing Pipeline is now the authoritative §1 of [`docs/ingestion/DOCUMENT_PROCESSING_SPEC_SUMMARY.md`](ingestion/DOCUMENT_PROCESSING_SPEC_SUMMARY.md).

---

## 6. Embedding Pipeline (moved)

> **Content moved.** The full conceptual overview of the Embedding Pipeline is now the authoritative §1 of [`docs/ingestion/EMBEDDING_PIPELINE_SPEC_SUMMARY.md`](ingestion/EMBEDDING_PIPELINE_SPEC_SUMMARY.md).

---

## 7. RAG Retrieval Pipeline — Query Processing and Retrieval

This phase is the real-time portion of the RAG pipeline. It begins the moment a user submits a natural language question and ends when a ranked set of document chunks, each scored for relevance to the query, is ready for answer generation. Its responsibility is to transform an ambiguous, context-dependent human query into a precise retrieval signal, search the knowledge base efficiently, and surface the most relevant evidence — all within tight latency constraints.

The phase processes each query through four sequential stages: query processing, an input guardrail, retrieval, and reranking. Query processing reformulates the raw query and resolves conversational context. The input guardrail validates the processed query and classifies its risk before it reaches the search layer. Retrieval combines dense vector search and keyword search to identify candidate document chunks. Reranking applies a more expensive, fine-grained model to reorder the candidates and eliminate irrelevant ones.

Four design principles govern this phase:

- **Fail-safe over fail-fast:** When optional components — query reformulation, knowledge graph expansion, embedding cache — are unavailable, the pipeline falls back to simpler alternatives rather than halting. A degraded result is better than no result.
- **Swappability over lock-in:** Every external dependency — embedding model, vector database, reranking model, LLM used for query processing — is configurable. Changing providers requires configuration changes, not code changes.
- **Explicit over implicit:** Query risk is classified deterministically from a configurable taxonomy and attached to pipeline state. Confidence is measured numerically at each stage. Nothing is inferred silently.
- **Configuration-driven behaviour:** Search parameters, scoring thresholds, cache sizes, and guardrail patterns are all controlled by a single configuration system with per-request overrides.

The four stages of this phase are:

```text
User Query (natural language)
    │
    ▼
┌──────────────────────────────────────┐
│ [1] QUERY PROCESSING                 │◄─── Conversation Memory
│     Reformulate, score confidence,   │     (sliding window + rolling
│     resolve multi-turn references    │      summary context injection)
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│ [2] INPUT GUARDRAIL                  │
│     Input validation, injection      │
│     detection, risk classification,  │
│     PII filtering (external LLM)     │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│ [3] RETRIEVAL                        │
│     Vector search + BM25 hybrid      │
│     Optional KG expansion            │
│     Metadata filtering               │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│ [4] RERANKING                        │
│     Cross-encoder rescoring          │
│     Score normalization & thresholds │
└──────────────┬───────────────────────┘
               │
               ▼
  Ranked Evidence Set (top-K chunks)
  → Passes to Section 8: Generation and Safety
```

### 7.1 Query Processing

This stage takes the raw natural language question and transforms it into a precise retrieval query. An LLM reformulates the query to add domain context, remove ambiguity, and generate alternative phrasings for ambiguous inputs. The reformulated query is scored for confidence on a 0.0–1.0 scale. Queries above a configurable threshold proceed to retrieval; queries below the threshold trigger a clarification request returned to the user. If the first reformulation attempt produces low confidence, the system retries up to a configurable maximum before falling back to the clarification path.

The query processor also resolves conversational references in multi-turn sessions. Pronouns and context-dependent references in follow-up questions — "it", "that", "the previous one", "tell me more" — are resolved against recent conversation history before reformulation. Without this resolution, every query is treated as independent, making natural follow-up impossible.

We can adjust several aspects of this stage to find the optimal performance:

- **Confidence threshold:** The minimum score required to proceed to retrieval. A lower threshold passes more queries through; a higher threshold triggers clarification requests more aggressively.
- **Retry count:** How many reformulation attempts are made before routing to the clarification path.
- **Alternative phrasings:** The number of alternative query phrasings generated for ambiguous inputs, which broadens the hybrid search.

### 7.2 Conversation Memory

The system maintains persistent, tenant-isolated conversation memory across requests. Each conversation stores the ordered sequence of query–answer turns and a rolling summary that condenses turns that fall outside the active window. Memory is injected into query processing via a sliding window — the N most recent turns are included as context so that coreference resolution and reformulation can reason over prior conversation state.

When the conversation grows beyond the window, older turns are compacted into a rolling summary rather than discarded. This preserves long-range thematic context — what topics the user has been investigating, what documents have already been discussed — without growing the injected context unboundedly.

We can adjust several aspects of this stage:

- **Window size:** How many recent turns are injected as context. Larger windows improve coreference resolution but increase token cost.
- **TTL:** How long inactive conversations are retained before automatic expiration.
- **Per-request memory control:** Memory injection can be disabled for a single request, overriding the global default without affecting other requests.

### 7.3 Input Guardrail

Every query passes through an input guardrail before reaching the search layer. The guardrail performs four checks:

**Input validation:** Query length, search parameter ranges, and filter values are validated against configured bounds. Invalid inputs are rejected with descriptive error messages before any search occurs.

**Injection detection:** Queries are scanned against an externally configurable set of prompt injection patterns. Matching queries are rejected with a generic user-facing message that does not reveal which pattern was matched. Patterns are loaded from a configuration file so they can be updated without code changes.

**Risk classification:** Each query is classified as HIGH, MEDIUM, or LOW risk using a deterministic keyword taxonomy loaded from configuration. The risk level is attached to the pipeline state and used downstream to control verification friction and output filtering. Deterministic, auditable classification ensures consistent behavior.

**PII detection (conditional):** When the pipeline routes to an external LLM provider, the guardrail detects and redacts personally identifiable information from the query before it is sent externally. PII is replaced with typed placeholders. The original query is preserved internally for retrieval but never transmitted to external services.

We can adjust several aspects of this stage:

- **Injection detection patterns:** The pattern set used to detect prompt injection is loaded from an external configuration file and can be updated without code changes. Patterns can be added, removed, or versioned independently of pipeline releases.
- **Risk classification taxonomy:** The keyword taxonomy that drives HIGH / MEDIUM / LOW classification is also externally configurable. Operators can tune classification sensitivity for their domain — broadening the HIGH-risk keyword set in safety-critical contexts or narrowing it where strict classification creates too much friction.
- **Validation bounds:** Query length limits and search parameter ranges are configurable to match the constraints of the underlying search infrastructure.
- **PII redaction toggle:** PII detection and redaction can be enabled or disabled independently of the injection detection check, allowing operators to separate these concerns where the external LLM routing configuration makes redaction unnecessary.

### 7.4 Retrieval

This stage searches the knowledge base for the most relevant document chunks using a hybrid strategy that combines dense vector similarity search with BM25 keyword search.

**Vector search** embeds the processed query using the same embedding model used during ingestion and computes similarity against all stored document vectors. Semantically related content surfaces even when the exact query terms do not appear in the document.

**BM25 keyword search** runs in parallel against the full-text content of document chunks. Exact lexical matches — identifiers, codes, acronyms, and technical terminology — are captured here even when semantic similarity is low.

The two result sets are fused using a configurable weight (alpha). At alpha = 0.0 the system returns only BM25 results; at alpha = 1.0 only vector results; at the default alpha = 0.5 both contribute equally. Score normalization is applied before fusion so both sources operate on a common scale.

We can adjust several aspects of this stage:

- **Alpha:** The balance between lexical and semantic search. Corpora with dense technical terminology benefit from higher BM25 weight; corpora with natural-language content benefit from higher vector weight.
- **Search limit:** How many candidates are fetched before reranking. A larger pool improves recall at the cost of reranking latency.
- **Metadata filters:** Hard filters on source, domain, document type, or version can be applied at search time to narrow the search space before scoring.
- **KG expansion (optional):** When a knowledge graph is available, query terms are expanded with related entities before the BM25 search. Expansion is configurable in depth and breadth and can be disabled independently without affecting the rest of the pipeline.

### 7.5 Reranking

A cross-encoder model rescores each (query, document chunk) pair from the retrieval candidate set. Unlike the approximate scoring used during retrieval, a cross-encoder attends to the full query–document interaction and can detect subtle relevance cues, correctly deprioritising chunks that matched on surface vocabulary but address a different concept.

Reranker scores are normalised to [0.0, 1.0]. A configurable score floor filters out chunks below the minimum relevance threshold before they reach generation — chunks scoring below this floor are excluded entirely. If all chunks fall below the threshold, the stage returns no evidence and the pipeline signals "insufficient documentation" rather than generating an answer from irrelevant content.

The configurable top-K parameter controls how many reranked chunks proceed to generation. A smaller K reduces generation context size and cost; a larger K improves recall at the cost of a more diffuse generation context.

We can adjust several aspects of this stage:

- **Reranker model:** The cross-encoder model can be swapped via configuration. More capable models produce better relevance discrimination; lighter models reduce reranking latency.
- **Score floor:** The minimum reranker score a chunk must achieve to proceed to generation. Raising the floor increases precision at the risk of returning no evidence for borderline queries; lowering it increases recall at the risk of passing low-relevance content to the LLM.
- **Top-K:** How many chunks pass to generation after reranking. Tuned independently of the retrieval search limit — a large candidate pool with a small top-K balances recall at retrieval with a tight, focused generation context.

---

## 8. RAG Retrieval Pipeline — Generation and Safety

This phase receives the ranked evidence set produced by Section 7 and is responsible for synthesising a grounded, source-cited answer and delivering it to the user safely. Its responsibilities span context assembly, answer generation, output safety checks, and answer delivery. It is the safety boundary of the RAG pipeline: everything that reaches the user passes through it.

The phase has four stages: context preparation structures the evidence for LLM consumption; generation produces the answer with source citations; the output guardrail measures confidence, detects hallucination, and filters unsafe content; and answer delivery routes the validated answer to the user and persists the interaction to conversation memory.

Four design principles govern this phase:

- **Grounded answers over fluent answers:** The generation system is explicitly designed to prefer an honest "I don't know" over a fluent but hallucinated response. Anti-hallucination instructions, citation requirements, and citation coverage checks all enforce this priority.
- **Multi-signal confidence over single-signal:** No single signal reliably measures answer quality. Retrieval quality, LLM self-report, and citation coverage are combined into a composite score that is more robust than any individual measure.
- **Risk-proportional friction:** Higher-risk queries receive more verification overhead — confirmation warnings, additional output filtering — without applying that overhead uniformly to all queries.
- **Fail-safe over fail-fast:** When the LLM is unavailable, the system returns the raw retrieved chunks rather than an error. When confidence is insufficient, the system returns an explicit "insufficient documentation" message rather than a low-confidence guess.

The four stages of this phase are:

```text
Ranked Evidence Set (top-K chunks with relevance scores)
    │
    ▼
┌──────────────────────────────────────┐
│ [5] CONTEXT PREPARATION              │
│     Structured metadata attachment   │
│     Version conflict detection       │
│     Context string assembly          │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│ [6] GENERATION                       │
│     Anti-hallucination prompt        │
│     Source citation enforcement      │
│     LLM confidence self-report       │
│     Retry with exponential backoff   │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│ [7] OUTPUT GUARDRAIL                 │
│     Composite confidence scoring     │
│     Hallucination detection          │
│     PII redaction, output sanitize   │
│     Confidence routing               │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│ [8] ANSWER DELIVERY                  │───► Conversation Memory
│     Return answer with sources,      │     (persist turn, update
│     confidence, risk-based display   │      rolling summary)
└──────────────────────────────────────┘
```

### 8.1 Context Preparation

Before the answer is generated, the retrieved chunks are assembled into a structured context string for LLM injection. Each chunk is accompanied by its metadata — source document name, version, section heading, and domain — so the LLM can produce accurate, traceable citations. The metadata is formatted consistently across all chunks; missing fields are populated with a documented sentinel value rather than omitted.

A version conflict check runs at this stage. When two or more retrieved chunks originate from different versions of the same document, the conflict is flagged in the pipeline state, surfaced explicitly in the context string, and included in the final response. The LLM is not allowed to silently resolve version conflicts — both versions are presented to the user so they can apply their own judgement.

We can adjust several aspects of this stage:

- **Metadata field set:** The minimum required fields (source name, version, section, domain) are fixed, but additional metadata fields can be included per deployment context without changing the core format.
- **Context string format template:** The format used to serialise chunks and their metadata into the context string is stored as external configuration and can be tuned for different LLM providers or prompt structures without a code change.
- **Version conflict handling:** The strictness of version conflict behaviour is configurable — operators can choose between warn-and-continue (surface the conflict but proceed with generation) or surface-and-halt (return the conflict to the user without generating an answer).

### 8.2 Answer Generation

The LLM receives the structured context string alongside the user's original query and a system prompt that enforces five anti-hallucination constraints: answer only from the provided documents; never use training-data knowledge; cite every factual claim using a standard format; explicitly state when the provided context is insufficient to answer the question; and report a self-assessed confidence level as part of the response.

The system prompt is stored as a separate configuration file, not inlined in code, so it can be tuned without a code change. A safe template engine is used for prompt construction to ensure that content within retrieved documents — JSON snippets, code blocks, or other text containing curly braces — is not misinterpreted as template variables.

All LLM calls use retry logic with exponential backoff. If all retries are exhausted, the system returns the raw retrieved chunks without synthesis rather than an error.

We can adjust several aspects of this stage:

- **LLM selection:** The generation model can be swapped via configuration. More capable models provide better reasoning on complex queries; lighter models reduce latency and cost.
- **Prompt engineering:** The system prompt and instruction structure can be iterated without code changes.
- **Temperature / sampling parameters:** Generation temperature should be set low for factual, deterministic answers. Higher values are appropriate only for exploratory or creative query types.

### 8.3 Output Guardrail and Confidence Routing

Every generated answer passes through the output guardrail before it reaches the user. The guardrail runs four checks and makes a routing decision based on the combined result.

**Composite confidence scoring** combines three independent signals into a single score:

| Signal | Weight | Source |
|--------|--------|--------|
| Retrieval confidence | 0.50 | Average reranker score across top retrieved chunks |
| LLM self-reported confidence | 0.25 | Extracted from the LLM's response |
| Citation coverage | 0.25 | Fraction of answer sentences grounded in retrieved chunks |

The weights are configurable. Each individual signal is logged alongside the composite for debugging.

**Hallucination detection** measures citation coverage: every factual sentence in the answer is checked against the retrieved chunks. Sentences that cannot be traced to any retrieved document are flagged. Answers with citation coverage below a configurable threshold are treated as potentially hallucinated.

**PII redaction** scans the generated answer for personally identifiable information — email addresses, phone numbers, employee identifiers, and person names — and replaces detected items with typed placeholders before the answer is returned.

**Output sanitisation** removes leaked system prompt fragments, internal metadata markers, unfilled template placeholders, and chunk boundary markers from the answer text.

**Confidence routing** decides what to do based on the composite score and the query's risk level:

| Composite Score | Risk Level | Action |
|-----------------|------------|--------|
| > 0.70 | LOW or MEDIUM | Return answer to user |
| > 0.70 | HIGH | Return answer with verification warning |
| 0.50–0.70 | Any | Re-retrieve with broader parameters (one retry) |
| < 0.50 | Any | Return "Insufficient documentation found" |

Re-retrieval is attempted at most once. If the retry does not raise confidence above the threshold, the system returns the insufficient documentation message rather than a low-confidence answer.

We can adjust several aspects of this stage:

- **Confidence signal weights:** The 0.50 / 0.25 / 0.25 split across retrieval confidence, LLM self-report, and citation coverage can be rebalanced. Deployments with consistently unreliable LLM self-reporting can reduce that signal's weight; deployments where citation coverage is a stronger quality signal can increase its weight.
- **Routing thresholds:** The 0.70 (return answer) and 0.50 (insufficient documentation) boundaries that drive routing decisions are configurable. Stricter deployments can raise these thresholds; higher-recall deployments with human review downstream can lower them.
- **Hallucination detection threshold:** The minimum citation coverage fraction below which an answer is treated as potentially hallucinated is configurable independently of the routing thresholds.
- **PII redaction patterns:** The set of entity types subject to redaction can be extended or restricted per deployment context.

### 8.4 Observability

The pipeline records a complete end-to-end trace for every query. The trace is keyed by a unique trace ID and includes a record for each pipeline stage — inputs, outputs, timing, and stage-specific metrics. Captured metrics include: reformulation count and confidence score (query processing); validation pass/fail, risk classification, and PII detections (input guardrail); search latency and result count (retrieval); score distribution (reranking); version conflicts detected (context preparation); generation latency, token count, and LLM confidence (generation); composite confidence, citation coverage, PII redactions, and routing action (output guardrail).

These traces enable post-hoc diagnosis of why a specific query produced a low-quality answer — whether the root cause was poor retrieval, low reranker scores, an LLM confidence problem, or insufficient citation coverage — without requiring a full re-run.

The system defines alerting thresholds for key metrics: if average composite confidence drops below a configurable floor, if the re-retrieval rate exceeds a threshold (indicating systemic retrieval quality degradation), or if end-to-end latency exceeds budget targets, automated alerts are triggered.

We can adjust several aspects of this stage:

- **Alerting thresholds:** The floor values for composite confidence, re-retrieval rate, and end-to-end latency that trigger alerts are all independently configurable to match the SLA expectations of the deployment.
- **Trace retention:** How long per-query traces are retained before expiry is configurable to balance storage cost against the depth of post-hoc diagnostic history required.
- **Trace verbosity:** The level of detail captured per stage — for example, whether raw retrieved chunk content is stored alongside scores, or only scores — can be tuned to reduce storage footprint in high-volume deployments.

---

## 9. Guardrails Framework

The guardrails framework is a dedicated safety and intent management layer that sits at two boundaries of the retrieval pipeline: immediately before the search stage (input rails) and immediately after answer generation (output rails). Its purpose is to ensure that queries entering the pipeline are appropriate, well-scoped, and free of injection or safety risks, and that answers leaving the pipeline are grounded, accurate, and safe to deliver to the user.

Unlike the safety checks embedded within individual pipeline stages (§7.3, §8.3), the guardrails framework treats input and output safety as a coordinated, independently configurable layer — one that can be updated, toggled, and tuned without touching the retrieval and generation logic it wraps. Each rail produces a structured verdict; a central merge gate combines those verdicts with the query processing result to make the final routing decision.

Four principles govern the framework:

- **Defense in depth:** Multiple independent checks — deterministic pattern matching and semantic classification — operate together. No single check is relied upon exclusively; each layer provides coverage the others may miss.
- **Fail-safe over fail-fast:** When a rail encounters an error, the system defaults to a safe fallback action rather than crashing the pipeline. Rails that time out or encounter infrastructure failures return a pass-with-warning rather than blocking the query indefinitely.
- **Parallel input, sequential output:** Input rails run concurrently with the existing query processing stages to minimise latency impact — their cost is bounded by the slowest rail, not their sum. Output rails run sequentially after generation, in a defined priority order, because later rails depend on the results of earlier ones.
- **Configurable strictness:** Every threshold, pattern set, toggle flag, and handler response is externally configurable. Deployments calibrate the guardrails to their risk profile without code changes.

The framework processes queries and answers through the following structure:

```text
[Query arrives]
    │
    ├──────────────────────────────────────────────────────────────┐
    │                                                              │
    ▼ (existing query processing — §7.1)                          ▼ (input rails — parallel)
┌────────────────────────────────┐       ┌──────────────────────────────────────────┐
│ Query Processing               │       │ [A] Intent Classification                │
│   Sanitize → Reformulate →     │       │ [B] Injection & Jailbreak Detection      │
│   Evaluate → Route             │       │ [C] Input PII Detection & Redaction      │
└──────────────┬─────────────────┘       │ [D] Input Toxicity Filtering             │
               │                         └──────────────┬───────────────────────────┘
               │                                        │
               └──────────────────┬─────────────────────┘
                                   ▼
                    ┌──────────────────────────────────┐
                    │ RAIL MERGE GATE                  │
                    │   Combine verdicts + route       │
                    │   search / reject / off-topic    │
                    └──────────────┬───────────────────┘
                                   │ (if routing action = search)
                                   ▼
                    ┌──────────────────────────────────┐
                    │ Retrieval (§7.4–7.5)             │
                    │ + Generation (§8.1–8.2)          │
                    └──────────────┬───────────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────────────────────┐
                    │ OUTPUT RAILS (sequential)                    │
                    │ [E] Faithfulness & Hallucination Detection   │
                    │ [F] Output PII Detection & Redaction         │
                    │ [G] Output Toxicity Filtering                │
                    └──────────────┬───────────────────────────────┘
                                   │
                                   ▼
                    [Validated answer delivered to user]
```

### 9.1 Intent Classification and Query Routing

The first input rail classifies each query into one of a set of canonical intent categories before it reaches the retrieval layer. The default taxonomy covers the primary query types a knowledge management system encounters: knowledge search (the primary RAG path), conversational exchanges such as greetings and farewells, off-topic requests that fall outside the system's knowledge domain, and administrative queries such as help requests or system status questions.

Classification runs concurrently with the query processing stage and does not add to the critical path for knowledge search queries. Queries classified as anything other than knowledge search are diverted to intent-specific handlers that return responses directly — without entering the retrieval, embedding, or generation stages. This eliminates wasted work on queries the pipeline cannot meaningfully answer and keeps latency budgets intact.

The classifier returns a confidence score alongside the intent label. Below a configurable threshold the system falls back to the knowledge search path, regardless of the classified intent. An ambiguous classification should never prevent a legitimate search query from being answered — falling through to search is the safe default.

We can adjust several aspects of this stage:

- **Intent taxonomy:** The set of recognised intents is externally configurable. New intent categories can be added and existing ones removed without code changes, allowing the taxonomy to grow with the use case.
- **Confidence threshold:** Below this value the system falls back to the knowledge search path, preventing over-eager diversion of legitimate queries with ambiguous phrasing.
- **Handler responses:** The responses returned for non-search intents — greeting text, off-topic refusal, help message — are stored in configuration and can be customised per deployment without code changes.

### 9.2 Input Safety Screening

Three input rails screen each query for injection attempts, personally identifiable information, and toxic content. All three execute in parallel with query processing so their combined latency is bounded by whichever rail is slowest, not by their sum.

**Injection and jailbreak detection** scans each query for prompt injection patterns and semantic jailbreak attempts. A fast deterministic layer — a configurable set of patterns loaded from an external file — provides low-latency coverage of known injection signatures. A semantic detection layer provides defense-in-depth against paraphrased or encoded injection attempts that bypass literal pattern matching. Queries rejected by either layer receive a generic user-facing message that does not reveal which mechanism triggered the rejection, preventing adversarial iteration.

**Input PII detection and redaction** identifies personally identifiable information in the query — email addresses, phone numbers, government identifiers, and similar sensitive data — and replaces detected items with typed placeholders before the query is forwarded to the retrieval pipeline or any external LLM. Typed placeholders preserve the query's grammatical structure for downstream processing while ensuring that sensitive values are never transmitted externally or written to pipeline logs.

**Input toxicity filtering** screens queries for hate speech, threats, and other categories of harmful content. Queries exceeding the configured toxicity threshold are rejected with a consistent, non-inflammatory message. The threshold is independently configurable — different deployment contexts carry different tolerance for aggressive phrasing.

We can adjust several aspects of this stage:

- **Injection detection patterns:** The pattern set is loaded from an external configuration file. Patterns can be added, removed, or versioned independently of pipeline releases, without code changes.
- **Injection sensitivity:** Three sensitivity levels (strict, balanced, permissive) allow deployments to calibrate how aggressively borderline queries are flagged. Internal deployments with trusted users can operate permissively; public-facing deployments should use strict settings.
- **PII categories:** The set of PII entity types subject to detection and redaction is configurable. Deployments handling domains with specific sensitive data types can extend the default category set.
- **PII toggle:** PII detection and redaction can be enabled or disabled independently of injection detection and toxicity filtering.
- **Toxicity threshold:** The sensitivity of the toxicity classifier is configurable — technical platforms with professional audiences can tolerate more aggressive phrasing than consumer-facing deployments.

### 9.3 Rail Merge Gate

The rail merge gate is the decision point that combines the results of the query processing stage and all input rails into a single routing action. It applies a defined priority ordering to resolve conflicts between rails:

1. **Injection rejection overrides everything.** A query flagged for injection or jailbreak is blocked regardless of its intent classification or any other rail verdict.
2. **Toxicity rejection overrides intent routing.** A toxic query is blocked even if it would otherwise have been classified as a legitimate knowledge search.
3. **Intent classification drives the routing path.** Non-search intents are diverted to their handlers; knowledge search intents proceed to retrieval.
4. **PII redaction modifies the query but does not change the routing path.** A query with detected PII proceeds to retrieval with the redacted version — PII detection is non-blocking.

The gate produces a structured verdict object that is attached to the pipeline state and passed through to the response. This object records which rails executed, what verdict each produced, and any redactions applied — enabling callers and operators to audit the rail decisions for any specific query without re-running the pipeline.

We can adjust several aspects of this stage:

- **Priority ordering:** The priority rules above represent the safe default. The relative precedence of security rails is configurable for deployments with a well-understood risk model that justifies a different ordering.
- **Verdict detail:** The depth of the structured verdict attached to responses is configurable — deployments with strict audit requirements can capture full per-rail timing and metadata; higher-throughput deployments can reduce the attached detail to conserve response payload size.

### 9.4 Output Safety Verification

After an answer is generated, three output rails verify that it is accurate, grounded, and safe to deliver. The rails execute sequentially in a fixed priority order: faithfulness checking runs first, followed by PII redaction, then toxicity filtering. An answer rejected by an earlier rail does not proceed to subsequent rails, avoiding unnecessary processing.

**Faithfulness and hallucination detection** verifies that each claim in the generated answer is grounded in the retrieved context chunks. It computes a faithfulness score by measuring how much of the answer's factual content can be traced back to retrieved evidence. A lightweight entity and numeric value check supplements this by flagging introduced facts — dates, names, statistics — that do not appear in any retrieved chunk, targeting the hallucination pattern most harmful in knowledge-base applications. When the faithfulness score falls below a configurable threshold, the system either rejects the answer and returns a fallback message, or flags the answer with a low-confidence warning — configurable per deployment.

**Output PII redaction** applies the same PII detection and redaction logic as the input rail, to the generated answer before it reaches the user. This is necessary because the LLM may reproduce PII present in retrieved document chunks even when the query itself was clean. Detected PII is replaced with typed placeholders in the returned answer.

**Output toxicity filtering** screens the generated answer for harmful content. LLMs can occasionally produce toxic output when prompted with adversarial context that slipped past the input rail. Detected toxic segments are replaced with a filtering placeholder before the answer is returned.

We can adjust several aspects of this stage:

- **Faithfulness threshold:** The minimum faithfulness score required to return an answer. Raising the threshold increases precision at the risk of more frequent fallbacks on borderline answers; lowering it increases recall at the risk of returning weakly-grounded responses.
- **Faithfulness action:** Whether an answer falling below the threshold is rejected outright (returning a fallback message) or flagged (returning the answer with a low-confidence warning in response metadata). Configured per deployment.
- **Claim-level scoring:** Faithfulness checks can operate at the whole-answer level (faster, coarser) or at the individual-claim level (slower, allows surgical removal of only the unsupported sentences rather than rejecting the full answer).
- **Output PII and toxicity toggles:** Output PII detection and output toxicity filtering are each independently toggleable. Some deployments require output filtering even when input filtering is disabled, or vice versa.

### 9.5 Rail Orchestration and Resilience

The rail framework is initialised once at worker startup and reused across all queries within the worker process. Per-query initialisation would violate latency budgets; the startup cost is paid once and amortised over the worker's lifetime.

A master toggle controls the entire guardrails framework. When disabled, the pipeline behaves exactly as it does without the framework — the in-pipeline safety checks (§7.3, §8.3) remain active, but the extended rail layer does not execute and introduces no overhead. This enables rapid rollback if the framework causes unexpected issues, and ensures the integration is fully inert in environments that do not require it.

Each rail is individually toggleable via configuration. Disabling a single rail affects only that rail; all other rails remain active. This allows rails to be introduced incrementally and rolled back individually without touching the rest of the safety layer.

When a rail encounters an error — LLM provider unreachable, parse failure, timeout — the system defaults to a safe fallback rather than crashing the pipeline. Rails that depend on an LLM (intent classification, faithfulness checking) fall back to deterministic alternatives when the LLM provider is unavailable. Any rail that exceeds its timeout budget returns a pass-with-warning verdict and allows the pipeline to continue. If the rail framework itself encounters a critical failure, the master toggle auto-disables and the pipeline reverts to pre-framework behaviour.

Every rail execution emits a structured telemetry event containing the rail name, verdict, execution time, and query identifier (never the raw query text). This event stream is the primary tool for operators calibrating rail thresholds over time — it provides the empirical rejection rate, per-rail latency, and false-positive signal needed to tune sensitivity for each deployment.

We can adjust several aspects of this stage:

- **Master toggle:** The entire guardrails framework can be disabled with a single configuration flag, reverting to the pre-integration safety behaviour. This is the rollback mechanism for production incidents.
- **Individual rail toggles:** Each rail can be independently enabled or disabled, allowing progressive rollout and targeted rollback without affecting the other rails.
- **LLM provider for semantic rails:** Rails that use LLM-based classification (intent classification, faithfulness checking) can be configured to use a different model or provider than the generation LLM — a lighter or faster model can be used where deep reasoning is not required.
- **Per-rail timeout budget:** The maximum time the pipeline will wait for a single rail before treating the result as a pass-with-warning. Tuning this prevents a slow or degraded rail from blocking the response.
