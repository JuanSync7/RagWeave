## 1) Generic System Overview

### Purpose

The Feedback Loop exists to close the gap between production system behavior and the operator's ability to improve it. Without this system, user quality signals — whether an answer was helpful, whether it retrieved the right sources, whether it was accurate — evaporate at the moment of interaction. Operators are left tuning retrieval and generation parameters based on offline benchmarks alone, with no visibility into how actual production queries are performing. The Feedback Loop captures those signals, aggregates them into statistically meaningful patterns, and surfaces actionable recommendations that operators can act on directly, compressing the improvement cycle from guesswork to evidence-driven decision.

### How It Works

The system operates as a five-stage pipeline. In the first stage, a rating capture component accepts a binary quality signal (positive or negative) from any user interface — console or command line. The submission is returned immediately without waiting for persistence; the rating is buffered and written asynchronously to ensure no latency is added to the user experience. Optionally, the user may attach a structured failure category and a free-text comment to a negative rating.

In the second stage, every rating is stored alongside a complete context snapshot: the query text, all retrieval parameters active at the time, the identifiers and relevance scores of every retrieved chunk, the generated answer, the conversation context, and the user identity (subject to a configurable anonymization policy). This context is what makes each rating actionable rather than merely a vote.

In the third stage, a background analysis process — running on a configurable schedule, isolated from query-serving infrastructure — clusters low-rated queries by semantic similarity, correlates rating outcomes with parameter values, and identifies source documents disproportionately associated with poor answers. Patterns are only promoted if they meet configurable minimum sample size thresholds, preventing premature or noisy recommendations.

In the fourth stage, confirmed patterns are classified into one of three recommendation categories — indexing gaps, parameter adjustments, or document quality issues — and surfaced in an operator-only dashboard, ordered by estimated impact. Operators can dismiss, act on, or approve recommendations. Duplicate detection ensures the same pattern does not generate multiple recommendations across analysis runs.

In the fifth stage, when an operator approves an indexing gap recommendation, the system dispatches a pre-approved ingestion trigger that initiates a document contribution run, bypassing the normal manual review step. Every trigger is fully logged in an audit trail before dispatch.

### Tunable Knobs

Operators can control the anonymization policy for stored user identities, choosing between full identity, stable pseudonymous identifiers, or fully anonymous storage. The retention period for raw rating events is configurable independently of recommendation retention. The minimum evidence thresholds — for query clustering, parameter correlation, and document flagging — can be tuned separately to control the noise-versus-sensitivity tradeoff. The analysis schedule, the peak hours window during which analysis is suppressed, and the compute resource allocation for analysis runs are all configurable. An optional auto-trigger policy, disabled by default, can be enabled with configurable confidence and impact gates to allow high-certainty indexing gap recommendations to dispatch ingestion without manual approval. The failure mode list presented to users on negative ratings is configurable without code changes.

### Design Rationale

The system is shaped by several foundational constraints. Rating capture must be invisible to the user — any perceptible latency at the moment of rating trains users to skip it, so asynchronous buffering is non-negotiable. Context co-location with ratings is equally foundational: a rating without the retrieval parameters and chunk IDs that produced the answer cannot be used for root cause analysis, so the context snapshot is mandatory, not optional. Minimum evidence enforcement before surfacing recommendations is a trust mechanism — premature recommendations erode operator confidence faster than they create value. The operator-in-the-loop design reflects an explicit principle that automated action on recommendations requires a human decision except where the operator has explicitly configured an auto-trigger policy. Finally, analysis isolation from query-serving infrastructure is a correctness requirement: shared compute during analysis would degrade the primary user experience.

### Boundary Semantics

The system's entry point is a user rating action — a thumbs-up or thumbs-down attached to a specific query response, submitted through any supported interface. The system takes responsibility for everything from that moment through recommendation surfacing and ingestion trigger dispatch. The exit point is an operator-approved action: either a recommendation dismissal, a manual parameter change, or an ingestion run initiated by the trigger. The actual execution of ingestion — chunking, embedding, indexing — falls outside this system's boundary and is handled by the ingestion pipeline. Rating events and recommendations are the primary persisted state; raw events are subject to configurable retention and purge, while derived recommendations persist independently of the raw events that generated them.

---

## 2) Document Header

| Field | Value |
|-------|-------|
| **Companion spec** | `FEEDBACK_LOOP_SPEC.md` |
| **Spec version** | 1.0 |
| **Summary version** | 1.0 |
| **Status** | Draft |
| **Domain** | Feedback Loop |
| **Summary purpose** | Concise digest of the companion spec — intent, scope, structure, and key decisions. Not a replacement for the spec. |

**See also:** `WEB_CONSOLE_SPEC.md`, `CLI_SPEC.md`, `USER_CONTRIBUTION_SPEC.md`, `INGESTION_PIPELINE_SPEC.md`, `RETRIEVAL_QUERY_SPEC.md`, `RAG_RETRIEVAL_PERFORMANCE_SPEC.md`

---

## 3) Scope and Boundaries

**Entry point:** A user rates a query response via the rating UI or CLI command.

**Exit point:** An operator views a prioritized tuning recommendation and optionally approves an action (parameter change or ingestion trigger) from the recommendations panel.

### In Scope

- Rating capture across all interfaces (console UI and CLI)
- Context snapshot storage with full query context per rating event
- Query pattern analysis (semantic clustering, parameter correlation, document flagging)
- Tuning recommendation generation, categorization, prioritization, and lifecycle management
- Feedback-driven ingestion triggers initiated from approved recommendations
- Audit trail for all feedback-driven trigger actions
- Operational metrics and health endpoint integration

### Out of Scope

- Automatic parameter changes without operator approval
- A/B testing infrastructure (SHOULD-level enhancement, not a core requirement)
- Quality evaluation against ground-truth datasets (see `RAG_RETRIEVAL_PERFORMANCE_SPEC.md`)
- Rating of ingestion quality or document processing
- User-to-user feedback visibility
- Real-time feedback integration into the live retrieval pipeline
- Execution of ingestion runs (handled by the ingestion pipeline and User Contribution feature)

---

## 4) Architecture / Pipeline Overview

```
User / Operator (Browser or CLI)
         |
         | thumbs up/down + optional failure mode + optional comment
         v
+-------------------------------------------+
| [1] RATING CAPTURE                        |
|     Accept rating + context ref           |
|     Return immediately (non-blocking)     |
|     Buffer → async persist to store       |
+-------------------------------------------+
         | rating event (async)
         v
+-------------------------------------------+
| [2] CONTEXT SNAPSHOT STORE                |
|     Durable, queryable storage            |
|     Rating + query text + parameters +    |
|     chunk IDs + scores + answer + conv ID |
|     Configurable anonymization policy     |
|     Configurable retention + purge        |
+-------------------------------------------+
         | scheduled / on-demand (isolated compute)
         v
+-------------------------------------------+
| [3] QUERY PATTERN ANALYSIS                |
|     Cluster low-rated queries             |
|     Correlate ratings with parameters     |
|     Flag low-quality source documents     |
|     Enforce minimum sample size thresholds|
+-------------------------------------------+
         | patterns (above minimum evidence)
         v
+-------------------------------------------+
| [4] RECOMMENDATION ENGINE                 |
|     Categorize: indexing gap /            |
|     parameter adjustment / doc quality   |
|     Prioritize by estimated impact        |
|     Deduplicate across analysis runs      |
|     Surface in Admin Console (admin only) |
+-------------------------------------------+
         | operator approves (indexing gap)
         v
+-------------------------------------------+
| [5] FEEDBACK-DRIVEN INGESTION TRIGGER     | (optional path)
|     Write audit log entry (pre-dispatch)  |
|     Create pre-approved contribution      |
|     Dispatch ingestion run                |
|     Notify operator on completion/failure |
+-------------------------------------------+
         |
         v
  [Ingestion pipeline — out of scope]
```

**Optional path:** Auto-trigger policy (disabled by default) allows high-confidence indexing gap recommendations to proceed without explicit operator approval, subject to configurable confidence and impact gates.

---

## 5) Requirement Framework

**ID convention:** `REQ-xxx` numeric identifiers with section-scoped hundreds ranges.

**Priority keywords:** RFC 2119 — `MUST` (non-conformant without it), `SHOULD` (recommended, may be omitted with justification), `MAY` (optional at implementor discretion).

**Each requirement contains:** Description, Rationale, and Acceptance Criteria.

**ID range table:**

| Section | ID Range | Component |
|---------|----------|-----------|
| 3 | REQ-1xx | Rating Capture |
| 4 | REQ-2xx | Context Snapshot Storage |
| 5 | REQ-3xx | Query Pattern Analysis |
| 6 | REQ-4xx | Tuning Recommendations |
| 7 | REQ-5xx | Feedback-Driven Ingestion Triggers |
| 8 | REQ-9xx | Non-Functional Requirements |

**Totals:** 31 requirements — 26 MUST, 5 SHOULD, 0 MAY.

---

## 6) Functional Requirement Domains

**Rating Capture (REQ-100 to REQ-199)**
Covers cross-interface parity (all surfaces route to the same backend endpoint), non-blocking asynchronous submission, explicit query-response association using a provided identifier, optional structured failure mode selection on negative ratings, optional free-text comments, and non-intrusive UI positioning.

**Context Snapshot Storage (REQ-200 to REQ-299)**
Covers mandatory full-context snapshot with every rating event (query text, parameters, chunk IDs and scores, generated answer, conversation ID, user identity, timestamp), three-option anonymization policy (full identity / pseudonymous / anonymous), multi-dimensional queryability with pagination, and configurable retention with purge that does not affect derived recommendations.

**Query Pattern Analysis (REQ-300 to REQ-399)**
Covers semantic clustering of low-rated queries using the same embedding model as retrieval, parameter-outcome correlation analysis, source document flagging by co-occurrence differential, minimum sample size enforcement (independently configurable for each analysis type), scheduled background execution on isolated compute, and on-demand runs from the Admin Console.

**Tuning Recommendations (REQ-400 to REQ-499)**
Covers admin-only recommendations panel, three-category classification (indexing gap / parameter adjustment / document quality), mandatory seven-field recommendation structure (category, description, hypothesized cause, suggested action, estimated impact, sample size, confidence), impact-ordered default view with dismiss/action lifecycle, duplicate detection and update across analysis runs, and optional A/B test initiation for parameter adjustment recommendations.

**Feedback-Driven Ingestion Triggers (REQ-500 to REQ-599)**
Covers one-click ingestion approval from indexing gap recommendations (creating pre-approved contributions), pre-dispatch audit logging, operator notification on completion or failure, and optional auto-trigger policy with configurable confidence and impact gates.

---

## 7) Non-Functional and Security Themes

**Performance and non-blocking capture**
- Rating endpoint must remain within a strict latency budget under concurrent load
- Asynchronous persistence decouples capture speed from store write speed

**Durability and resilience**
- Rating events must survive transient store outages via durable buffering; zero events lost is the standard
- Analysis run failures are recoverable; partial results are not surfaced

**Infrastructure isolation**
- Pattern analysis must not measurably impact retrieval query serving latency
- Analysis runs scheduled away from peak hours if shared compute is unavoidable

**Configuration externalization**
- All behavioral parameters externalized to environment variables with documented defaults
- Includes anonymization policy, retention period, sample size thresholds, analysis schedule, peak hours window, auto-trigger policy and gates, and failure mode list

**Operational observability**
- Health endpoint exposes rating ingestion rate, buffer depth, analysis run status and duration, recommendation counts by category and status, and auto-trigger count

**Privacy**
- Anonymization policy enforced at storage time; three modes cover the range from full traceability to no identity retention
- Pseudonymous mode uses a stable non-reversible identifier that enables per-user pattern analysis without individual attribution

**Audit and accountability**
- Every feedback-driven trigger recorded in the audit trail before dispatch
- Auto-trigger actions tagged as `automatic` in the audit log; human-reviewable from the Admin Console

---

## 8) Design Principles

| Principle | One-liner |
|-----------|-----------|
| **Non-blocking capture** | Rating submission must never add latency to the query response or block the user's next interaction. |
| **Context is the value** | Every rating must be stored with the full query context snapshot that makes it actionable for tuning. |
| **Minimum evidence before surfacing** | Patterns and recommendations must not be surfaced until a statistically meaningful sample size is reached. |
| **Operator in the loop** | Recommendations surface insights and suggest actions; they do not act automatically without operator approval (except where an explicit auto-trigger policy is configured). |
| **Graceful degradation** | Rating capture must succeed even when analysis infrastructure is unavailable; ratings are stored durably and analysis runs when infrastructure is available. |

---

## 9) Key Decisions

- **Asynchronous rating persistence** — The capture endpoint returns before the rating is written. Ratings are buffered durably to prevent loss during transient outages, decoupling capture reliability from store availability.
- **Mandatory context snapshot** — A rating without the accompanying retrieval context (parameters, chunk IDs, scores) has no diagnostic value. The context snapshot is a required component of every rating event, not an optional enrichment.
- **Separate storage for rating events** — Rating events are stored in a queryable datastore independent of the retrieval vector store. This prevents analysis query load from impacting retrieval serving latency.
- **Three-tier anonymization policy** — A single configurable policy covers the full range from full traceability (full identity) to per-user pattern analysis without attribution (pseudonymous) to maximum privacy (anonymous), satisfying different organizational requirements without code changes.
- **Minimum sample enforcement as a trust mechanism** — Patterns must meet configurable minimum evidence thresholds before becoming recommendations. This is the primary quality gate; without it, low-sample noise erodes operator trust in the recommendation system.
- **Three recommendation categories** — Indexing gap, parameter adjustment, and document quality map cleanly to distinct remediation actions. The category determines what the operator should do, so mixed-category recommendations without labeling would force operators to re-diagnose the pattern.
- **Operator approval before action** — Recommendations do not trigger changes automatically. The auto-trigger policy is an explicit opt-in at the operator level, not a default behavior, reflecting the principle that human oversight is required for system changes.
- **Pre-dispatch audit logging** — Audit records are written before ingestion triggers are dispatched, ensuring that every triggered action is traceable even if the dispatch itself fails.

---

## 10) Acceptance, Evaluation, and Feedback

The spec defines ten system-level acceptance criteria covering:

- Rating endpoint latency under concurrent load
- Zero rating event loss during store outages
- Cross-interface rating parity (CLI and console produce equivalent stored events)
- Anonymization policy enforcement across all three policy options
- Pattern minimum sample size enforcement (no recommendation below configured threshold)
- Analysis/serving compute isolation (retrieval latency within baseline during analysis)
- Recommendation record completeness (all seven fields present)
- Pre-dispatch audit trail for every ingestion trigger
- Auto-trigger disabled by default; enabled only via explicit configuration
- All behavioral parameters configurable via environment variable

The spec does not define an evaluation framework for ongoing monitoring of recommendation quality or acceptance rate — this is captured as an open question in the appendix. The `RAG_RETRIEVAL_PERFORMANCE_SPEC.md` covers complementary benchmark-based quality evaluation outside this system's scope.

---

## 11) External Dependencies

| Dependency | Type | Notes |
|------------|------|-------|
| Rating event datastore | Required | Queryable store separate from the vector store; specific technology unresolved (see OQ-1 in spec appendix) |
| Embedding model (retrieval) | Required | Same model used for query clustering in pattern analysis; must be accessible from analysis infrastructure |
| Analysis compute infrastructure | Required | Must be separate from retrieval query serving; off-peak scheduling fallback if dedicated compute unavailable |
| Central Contribution workflow | Required | Invoked by feedback-driven ingestion triggers; defined in `USER_CONTRIBUTION_SPEC.md` |
| Ingestion pipeline | Required (downstream) | Executes ingestion runs dispatched by approved triggers; defined in `INGESTION_PIPELINE_SPEC.md` |
| Admin Console | Required (surface) | Recommendations panel, on-demand analysis trigger, and auto-trigger log are hosted in Admin Console |
| User Console and CLI | Required (surface) | Rating capture surfaces in both; parity required |

---

## 12) Companion Documents

This summary is a digest of `FEEDBACK_LOOP_SPEC.md` (v1.0). It captures intent, scope, structure, and key decisions without reproducing requirement-level detail or acceptance criteria thresholds. For normative requirements, refer to the companion spec.

| Document | Relationship |
|----------|-------------|
| `FEEDBACK_LOOP_SPEC.md` | Companion spec — normative requirements, acceptance criteria, interface contracts, error taxonomy |
| `WEB_CONSOLE_SPEC.md` | Defines the UI surfaces where rating controls appear and where the recommendations panel is hosted |
| `CLI_SPEC.md` | Defines the `/rate` command integration in the CLI REPL |
| `USER_CONTRIBUTION_SPEC.md` | Defines the Central Contribution workflow invoked by feedback-driven ingestion triggers |
| `INGESTION_PIPELINE_SPEC.md` | Defines the ingestion pipeline that executes feedback-driven trigger runs |
| `RETRIEVAL_QUERY_SPEC.md` | Defines retrieval parameters subject to parameter adjustment recommendations |
| `RAG_RETRIEVAL_PERFORMANCE_SPEC.md` | Defines complementary benchmark-based quality evaluation (out of scope for this system) |

The spec also includes a requirements traceability matrix (31 requirements), a glossary (7 terms), and an open questions appendix (4 items covering datastore selection, default anonymization policy, compute availability, and failure mode list management approach).

---

## 13) Sync Status

| Field | Value |
|-------|-------|
| **Spec version aligned to** | 1.0 |
| **Summary written** | 2026-04-10 |
| **Summary status** | Current |
