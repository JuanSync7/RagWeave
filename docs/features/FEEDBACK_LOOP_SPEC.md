# Feedback Loop Specification

**AION Knowledge Management Platform**
Version: 1.0 | Status: Draft | Domain: Feedback Loop

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-03-18 | AI Assistant | Initial specification |

> **Document intent:** This is a normative requirements/specification document for the Feedback Loop feature.
> For the implementation plan, see `FEEDBACK_LOOP_IMPLEMENTATION.md`.
> For UI surface behavior, see `WEB_CONSOLE_SPEC.md` and `CLI_SPEC.md`.
> For the ingestion pipeline that executes feedback-driven ingestion triggers, see `INGESTION_PIPELINE_SPEC.md`.
> For the User Contribution feature that feedback-driven triggers invoke, see `USER_CONTRIBUTION_SPEC.md`.

---

## 1. Scope & Definitions

### 1.1 Problem Statement

The RAG system's retrieval and generation quality depends on parameter choices — chunk size, rerank top-k, alpha, retrieval depth, model temperature — that are set at deployment time based on benchmarks and developer intuition. Once the system is in production, there is no mechanism to learn from actual user outcomes. Low-quality answers are silently accepted or abandoned without generating any signal that reaches the system operators. Operators cannot distinguish high-performing parameter configurations from low-performing ones, cannot identify document coverage gaps that cause retrieval failures, and cannot prioritize which improvements would most improve user satisfaction. The Feedback Loop closes this gap: it captures structured quality signals directly from users at the point of interaction, stores them with the full query context needed to make them actionable, and surfaces them as prioritized tuning recommendations for operators.

### 1.2 Scope

This specification defines requirements for the **Feedback Loop** feature. The boundary is:

- **Entry point:** A user rates a query response via the rating UI or CLI command.
- **Exit point:** An operator views a prioritized tuning recommendation and optionally approves an action (parameter change or ingestion trigger) directly from the recommendations panel.

Everything between these points is in scope, including rating capture, context snapshot storage, query pattern analysis, recommendation generation, and feedback-driven ingestion triggers. The actual execution of ingestion triggered by a recommendation is out of scope (handled by the ingestion pipeline and User Contribution feature).

### 1.3 Terminology

| Term | Definition |
|------|-----------|
| **Rating** | A user's quality signal for a query response: a binary thumbs-up or thumbs-down, with optional structured failure mode and free-text comment |
| **Context Snapshot** | The complete record of a rated query interaction: query text, active parameters, retrieved chunk IDs and scores, generated answer, conversation ID, user identity, and timestamp |
| **Failure Mode** | A structured category of answer failure (e.g., "wrong sources retrieved", "answer hallucinated", "too vague", "off-topic") selectable from a configured list on a thumbs-down rating |
| **Rating Event** | The combination of a rating and its associated context snapshot, stored as a single record |
| **Query Cluster** | A group of semantically similar queries identified by embedding-based clustering of low-rated query texts |
| **Pattern** | A statistically significant correlation between query characteristics or system parameters and low rating scores, identified through aggregated rating analysis |
| **Recommendation** | A structured, actionable suggestion surfaced in the Admin Console, derived from pattern analysis, with a category (indexing gap, parameter adjustment, document quality), supporting evidence, and suggested action |
| **Indexing Gap** | A pattern where queries consistently retrieve zero or low-relevance chunks, indicating missing documents in the central index |
| **Recommendation Confidence** | A measure of statistical reliability for a recommendation, based on sample size and consistency of the underlying pattern |
| **Feedback-Driven Trigger** | An ingestion run initiated directly from a recommendation approval, creating a pre-approved Central Contribution submission that bypasses manual review |
| **Anonymization Policy** | The configured rule governing how user identity is stored with rating events (full identity, pseudonymous session ID, or fully anonymous) |

### 1.4 Requirement Priority Levels

This document uses RFC 2119 language:

- **MUST** — Absolute requirement. The system is non-conformant without it.
- **SHOULD** — Recommended. May be omitted only with documented justification.
- **MAY** — Optional. Included at the implementor's discretion.

### 1.5 Requirement Format

> **REQ-xxx** | Priority: MUST/SHOULD/MAY
>
> **Description:** What the system shall do.
>
> **Rationale:** Why this requirement exists.
>
> **Acceptance Criteria:** How to verify conformance.

| Section | ID Range | Component |
|---------|----------|-----------|
| 3 | REQ-1xx | Rating Capture |
| 4 | REQ-2xx | Context Snapshot Storage |
| 5 | REQ-3xx | Query Pattern Analysis |
| 6 | REQ-4xx | Tuning Recommendations |
| 7 | REQ-5xx | Feedback-Driven Ingestion Triggers |
| 8 | REQ-9xx | Non-Functional Requirements |

### 1.6 Assumptions & Constraints

| ID | Assumption / Constraint | Impact if Violated |
|----|------------------------|--------------------|
| A-1 | The embedding model used for retrieval is also available for query clustering in pattern analysis | A separate embedding model must be provisioned for analysis, risking semantic space mismatch |
| A-2 | Rating events and context snapshots are stored in a queryable datastore separate from the vector store | Analysis queries against the vector store would degrade retrieval serving performance |
| A-3 | The recommendation panel is surfaced in the Admin Console only, not the User Console | End-user exposure of tuning recommendations requires additional UX design and scope |
| A-4 | Feedback-driven ingestion triggers invoke the Central Contribution workflow defined in `USER_CONTRIBUTION_SPEC.md` | A separate ingestion path must be built if the contribution workflow is unavailable |
| A-5 | Pattern analysis runs do not execute on the query-serving infrastructure | Shared compute could cause retrieval latency spikes during analysis runs |

### 1.7 Design Principles

| Principle | Description |
|-----------|-------------|
| **Non-blocking capture** | Rating submission must never add latency to the query response or block the user's next interaction. Ratings are captured asynchronously. |
| **Context is the value** | A rating without context is nearly useless. Every rating must be stored with the full query context snapshot — parameters, chunk IDs, scores — that makes it actionable for tuning. |
| **Minimum evidence before surfacing** | Patterns and recommendations must not be surfaced until a statistically meaningful sample size is reached. Premature recommendations based on small samples create noise and erode operator trust. |
| **Operator in the loop** | Recommendations surface insights and suggest actions; they do not take actions automatically without operator approval (except where an explicit auto-trigger policy is configured). |
| **Graceful degradation** | Rating capture must succeed even when analysis infrastructure is unavailable. Ratings are stored durably; analysis runs when infrastructure is available. |

### 1.8 Out of Scope

- Automatic parameter changes without operator approval (the system recommends, the operator decides)
- A/B testing infrastructure (referenced as a SHOULD-level enhancement, not a core requirement)
- Quality evaluation against ground-truth datasets — see `RAG_RETRIEVAL_PERFORMANCE_SPEC.md`
- Rating of ingestion quality or document processing — ratings apply to query responses only
- User-to-user feedback (ratings are operator-facing insights, not visible to other users)
- Real-time feedback integration into the live retrieval pipeline (recommendations inform manual tuning decisions)

---

## 2. System Overview

### 2.1 Architecture Diagram

```
User / Operator (Browser or CLI)
         │
         │ thumbs up/down + optional comment + failure mode
         ▼
┌─────────────────────────────────────────────────────┐
│ [1] RATING CAPTURE                                  │
│     Accepts rating + context snapshot               │
│     Non-blocking — returns immediately              │
│     Stores to rating event store                    │
└────────────────────────┬────────────────────────────┘
                         │ rating event (async)
                         ▼
┌─────────────────────────────────────────────────────┐
│ [2] CONTEXT SNAPSHOT STORE                          │
│     Durable, queryable storage                      │
│     Rating + query text + parameters +              │
│     chunk IDs + scores + answer + conversation ID   │
└────────────────────────┬────────────────────────────┘
                         │ scheduled / on-demand
                         ▼
┌─────────────────────────────────────────────────────┐
│ [3] QUERY PATTERN ANALYSIS                          │
│     Cluster low-rated queries by embedding          │
│     Correlate ratings with parameters               │
│     Identify low-quality source documents           │
│     Enforce minimum sample size                     │
└────────────────────────┬────────────────────────────┘
                         │ patterns
                         ▼
┌─────────────────────────────────────────────────────┐
│ [4] RECOMMENDATION ENGINE                           │
│     Categorize: indexing gap / parameter /          │
│     document quality                               │
│     Prioritize by estimated impact                  │
│     Surface in Admin Console                        │
└────────────────────────┬────────────────────────────┘
                         │ operator approves
                         ▼
┌─────────────────────────────────────────────────────┐
│ [5] FEEDBACK-DRIVEN INGESTION TRIGGER               │
│     Creates pre-approved contribution submission    │
│     Invokes ingestion pipeline                      │
│     Logs trigger in audit trail                     │
└─────────────────────────────────────────────────────┘
```

### 2.2 Data Flow Summary

| Flow | Entry | Processing | Exit |
|------|-------|------------|------|
| Rating submission | User rates response in console/CLI | Validate → store rating event + context snapshot (async) | Rating stored; no latency added to user |
| Pattern analysis | Scheduled trigger or on-demand | Cluster queries → correlate parameters → score patterns | Pattern records stored |
| Recommendation generation | Pattern analysis output | Categorize → prioritize → filter by minimum sample | Recommendations surfaced in Admin Console |
| Recommendation action | Operator dismisses or approves | Dismissed: marked inactive. Approved: trigger or parameter change initiated | Recommendation state updated; action logged |
| Feedback-driven trigger | Approved indexing-gap recommendation | Create pre-approved contribution → dispatch ingestion | Ingestion run initiated; audit log entry written |

---

## 3. Rating Capture (REQ-1xx)

> **REQ-101** | Priority: MUST
>
> **Description:** The system MUST accept binary ratings (thumbs-up or thumbs-down) for query responses from all three interfaces: the User Console, the Admin Console, and the CLI. All three interfaces MUST route to the same backend rating endpoint.
>
> **Rationale:** CLI/UI parity requires rating capability across all surfaces. Operators using the CLI for diagnostic queries must be able to rate responses without switching to a browser.
>
> **Acceptance Criteria:** A thumbs-down submitted via the CLI produces a rating event in the store. The same thumbs-down submitted via the User Console produces an equivalent event. Both are queryable via the admin analytics endpoint. The backend endpoint is identical regardless of interface.

---

> **REQ-102** | Priority: MUST
>
> **Description:** Rating submission MUST be non-blocking. The system MUST return control to the user immediately after rating submission without waiting for the rating event to be persisted. Rating persistence MUST occur asynchronously after the submission response is returned.
>
> **Rationale:** Ratings are captured at a moment of user momentum — immediately after reading an answer. Any perceptible delay at that moment trains users to skip rating. Rating capture must feel instantaneous.
>
> **Acceptance Criteria:** The rating submission endpoint returns within 100ms under normal load. A simulated persistence outage does not cause the rating endpoint to time out — it accepts the rating into a buffer and returns immediately. Ratings are durably persisted once the store is available.

---

> **REQ-103** | Priority: MUST
>
> **Description:** The system MUST associate each rating with the exact query response being rated. The association MUST use the query response identifier (or conversation turn identifier) provided at the time of rating submission, not inferred from session state.
>
> **Rationale:** Session-based inference of "which response was rated" is fragile — it breaks if the user rates a response after navigating away and back, or if multiple queries were submitted rapidly. An explicit identifier ensures the rating is attached to the correct response.
>
> **Acceptance Criteria:** A rating submitted with a specific query response ID is stored with that ID in the context snapshot. A rating submitted without a valid query response ID is rejected with a validation error. The rating cannot be re-associated to a different response after submission.

---

> **REQ-104** | Priority: SHOULD
>
> **Description:** On a thumbs-down rating, the system SHOULD present a structured failure mode selector allowing the user to categorize the failure. The failure mode list MUST be configurable and MUST include at minimum: "wrong sources retrieved", "answer hallucinated", "too vague", "off-topic", and "other". Selecting a failure mode MUST be optional — a thumbs-down without a failure mode is a valid rating.
>
> **Rationale:** Structured failure modes provide categorical signal that enables faster pattern detection than free-text analysis alone. "Wrong sources retrieved" and "answer hallucinated" point to different remediation paths, even for similar query types.
>
> **Acceptance Criteria:** After a thumbs-down in the User Console, a failure mode selector appears. The selector includes the configured options. Submitting without selecting a failure mode stores the rating with `failure_mode: null`. The failure mode is stored in the context snapshot. The failure mode list is configurable without code changes.

---

> **REQ-105** | Priority: SHOULD
>
> **Description:** The system SHOULD accept an optional free-text comment alongside a rating. Comments MUST be stored in the context snapshot. Comment capture MUST be presented as clearly optional and MUST NOT be required to complete a rating submission.
>
> **Rationale:** Structured selectors cannot capture nuanced feedback. A user who chooses "too vague" may have a specific observation ("the answer never mentioned the deadline") that would be lost without a comment field. Making it optional maximizes rating throughput.
>
> **Acceptance Criteria:** A comment field is visible but not required in the rating UI. Submitting a rating without a comment stores the rating with `comment: null`. Submitting with a comment stores the text in the context snapshot. Comments are displayed alongside the rating event in the admin analytics view.

---

> **REQ-106** | Priority: MUST
>
> **Description:** The system MUST NOT display rating controls (thumbs-up/down, failure mode selector, comment field) in a way that interrupts or blocks the user's ability to read the answer or ask a follow-up question. Rating controls MUST be visually subordinate to the answer content.
>
> **Rationale:** Rating capture must not degrade the primary user experience. Prominent or intrusive rating UI creates friction and trains users to dismiss it.
>
> **Acceptance Criteria:** Rating controls are positioned below the answer content and source citations, not above or overlaid. The rating controls do not trigger any modal, overlay, or navigation that obscures the answer. After submitting a rating, the answer remains visible and the input bar remains active.

---

## 4. Context Snapshot Storage (REQ-2xx)

> **REQ-201** | Priority: MUST
>
> **Description:** Every rating event MUST be stored with a complete context snapshot containing: query text, all active query parameters at the time of the query (preset name, source filter, alpha, search limit, rerank top-k, fast path flag), retrieved chunk IDs and their relevance scores and rerank scores, generated answer text, conversation ID, user identity (per the configured anonymization policy), rating value (thumbs-up/down), failure mode (if selected), comment (if provided), and timestamp.
>
> **Rationale:** The context snapshot is what makes a rating actionable. A thumbs-down without knowing which parameters were active and which chunks were retrieved tells an operator that something went wrong, but not what to fix. The complete context enables root cause analysis.
>
> **Acceptance Criteria:** A stored rating event is retrievable by rating ID. The retrieved record contains all fields listed above. `chunk_ids` includes all chunk IDs that were in the retrieval result, with their scores. `query_parameters` reflects the parameters active at query time, not the current system defaults.

---

> **REQ-202** | Priority: MUST
>
> **Description:** User identity in stored rating events MUST conform to the configured anonymization policy. The system MUST support three policy options: **full identity** (store the authenticated principal ID), **pseudonymous** (store a stable session-scoped hash of the principal ID that cannot be reversed to the original identity), and **anonymous** (store no identity information). The active policy MUST be configurable per deployment.
>
> **Rationale:** Different organizational contexts have different privacy requirements. Full identity enables individual follow-up; pseudonymous identity enables per-user pattern analysis without individual attribution; anonymous satisfies the most restrictive privacy requirements.
>
> **Acceptance Criteria:** With the full-identity policy, the stored `user_id` field matches the authenticated principal ID. With the pseudonymous policy, the stored `user_id` is a hash that is consistent across sessions for the same user but cannot be reversed. With the anonymous policy, the `user_id` field is null. The policy is set via environment variable and takes effect on server restart.

---

> **REQ-203** | Priority: MUST
>
> **Description:** The rating event store MUST be queryable by: rating value (thumbs-up/down), time range, failure mode, conversation ID, and any active query parameter. Query results MUST support pagination. The store MUST NOT be the vector store used for retrieval.
>
> **Rationale:** Pattern analysis requires flexible querying across multiple dimensions. Using the retrieval vector store for rating events would couple analysis query load to retrieval serving performance, risking latency spikes during analysis runs.
>
> **Acceptance Criteria:** A query for all thumbs-down ratings with `failure_mode = "wrong sources retrieved"` in a specific time range returns the correct events. Results are paginated at a configurable page size. Rating event queries do not appear in the retrieval pipeline's performance metrics.

---

> **REQ-204** | Priority: MUST
>
> **Description:** The system MUST enforce a configurable retention period for rating events. Events older than the configured retention period MUST be purged by a background process. Purge MUST NOT affect recommendations derived from those events — recommendations persist independently of the underlying events.
>
> **Rationale:** Indefinite retention of rating events (including query text and answer text) may conflict with organizational data retention policies. Purging raw events while retaining derived recommendations preserves operational value without indefinite data accumulation.
>
> **Acceptance Criteria:** Events older than the configured retention period are not returned by store queries. The purge process runs on a configurable schedule. Existing recommendations are not affected when their underlying events are purged. Retention period is configurable via environment variable.

---

## 5. Query Pattern Analysis (REQ-3xx)

> **REQ-301** | Priority: MUST
>
> **Description:** The system MUST cluster low-rated query texts by semantic similarity using the same embedding model as the retrieval pipeline. Clusters MUST be identified by computing embeddings of low-rated query texts and grouping them by vector proximity. Each cluster MUST be summarized with a representative query and the cluster's average rating score.
>
> **Rationale:** Individual low-rated queries are noisy. Semantic clustering reveals that many superficially different queries are about the same topic and are consistently failing — a signal that is invisible at the individual query level.
>
> **Acceptance Criteria:** Given 50 low-rated queries about Project X and 30 low-rated queries about the HR policy, the clustering output contains two dominant clusters corresponding to these topics. Each cluster record includes a representative query text, cluster size, and average rating. Clusters are re-computed on each analysis run.

---

> **REQ-302** | Priority: MUST
>
> **Description:** The system MUST correlate rating scores with active query parameters to identify parameter combinations that are associated with systematically lower ratings. The correlation analysis MUST compute the average rating score for each distinct parameter value (or value range for continuous parameters) with sufficient sample size.
>
> **Rationale:** A rerank top-k of 3 may produce acceptable results for simple queries but consistently fail for complex multi-document queries. Correlation analysis surfaces these parameter-outcome relationships that are invisible without structured data.
>
> **Acceptance Criteria:** Given 200 ratings, the analysis produces a parameter correlation report showing average rating by rerank top-k value (e.g., top-k=3: avg 0.42, top-k=10: avg 0.78). Correlations are only reported for parameter values with at least the configured minimum sample size. The report is regenerated on each analysis run.

---

> **REQ-303** | Priority: MUST
>
> **Description:** The system MUST identify source documents that are disproportionately associated with low-rated responses. A document is flagged if it appears in the retrieval results of low-rated queries significantly more often than in high-rated queries, controlling for retrieval frequency.
>
> **Rationale:** A document that is frequently retrieved but consistently associated with low ratings may be low quality, poorly chunked, or semantically misleading — it attracts queries but does not help answer them. Identifying these documents enables targeted remediation.
>
> **Acceptance Criteria:** Given a document that appears in 80% of low-rated retrievals for a query cluster but only 10% of high-rated retrievals for similar queries, the analysis flags that document. The flag record includes the document ID, co-occurrence rates (low-rated vs high-rated), and the associated query cluster. Documents are only flagged when the sample sizes meet the configured minimum.

---

> **REQ-304** | Priority: MUST
>
> **Description:** The system MUST enforce a configurable minimum sample size for every pattern and recommendation. Patterns derived from fewer samples than the minimum MUST NOT be surfaced as recommendations. The minimum sample size MUST be independently configurable for clustering (minimum queries per cluster), parameter correlation (minimum ratings per parameter value), and document flagging (minimum retrievals per document).
>
> **Rationale:** Small sample sizes produce noisy, unreliable patterns. An operator who acts on a recommendation derived from 3 ratings and finds it was noise loses trust in the system. Minimum sample enforcement is the primary mechanism for recommendation quality control.
>
> **Acceptance Criteria:** A query cluster with 4 members is not surfaced as a recommendation when the configured minimum is 10. A parameter correlation with 5 samples is not reported when the configured minimum is 20. All three minimums are independently configurable via environment variables.

---

> **REQ-305** | Priority: MUST
>
> **Description:** Pattern analysis MUST run on a configurable schedule (e.g., nightly, weekly) as a background process. Analysis runs MUST NOT execute on the same compute resources as the retrieval query pipeline.
>
> **Rationale:** Analysis is computationally intensive (embedding clustering, aggregation queries). Running it on shared query-serving infrastructure risks latency spikes for active users.
>
> **Acceptance Criteria:** Analysis runs are triggered on the configured schedule without manual intervention. During an analysis run, retrieval query latency is not measurably impacted (p95 latency remains within 10% of baseline). The analysis schedule is configurable via environment variable.

---

> **REQ-306** | Priority: SHOULD
>
> **Description:** The system SHOULD support on-demand analysis runs triggered by an operator from the Admin Console, independent of the scheduled run cycle.
>
> **Rationale:** After a significant parameter change or a new document ingestion, an operator may want to immediately assess whether ratings have improved rather than waiting for the next scheduled run.
>
> **Acceptance Criteria:** A "Run Analysis Now" action is available in the Admin Console. Triggering it initiates an analysis run and displays progress or completion status. The on-demand run produces the same output as a scheduled run. Triggering an on-demand run while a scheduled run is in progress either queues or rejects the request with a clear status message.

---

## 6. Tuning Recommendations (REQ-4xx)

> **REQ-401** | Priority: MUST
>
> **Description:** The system MUST surface tuning recommendations in the Admin Console in a dedicated recommendations panel. Recommendations MUST be visible only to users with admin role. The panel MUST be accessible without navigating away from other Admin Console tabs.
>
> **Rationale:** Recommendations must reach the people authorized to act on them (operators) without requiring a separate tool or login. Restricting to admin role prevents end users from seeing internal diagnostic information.
>
> **Acceptance Criteria:** The recommendations panel is accessible from the Admin Console. Users without admin role do not see the panel (enforced at the API layer, not only the UI). The panel displays the current recommendation list with their statuses.

---

> **REQ-402** | Priority: MUST
>
> **Description:** Each recommendation MUST be categorized as exactly one of three types: **Indexing Gap** (queries retrieving zero or low-relevance chunks, suggesting missing documents), **Parameter Adjustment** (a query parameter value correlated with lower ratings), or **Document Quality** (a source document disproportionately associated with low-rated responses).
>
> **Rationale:** The category determines what action an operator should take. Mixing categories without clear labeling forces operators to diagnose the recommendation type themselves, adding cognitive load.
>
> **Acceptance Criteria:** Every recommendation record contains a `category` field with one of the three values. The recommendations panel displays category as a visible label or filter. An operator can filter recommendations by category.

---

> **REQ-403** | Priority: MUST
>
> **Description:** Each recommendation MUST include: category, a human-readable description of the observed pattern, the hypothesized cause, the suggested action, the estimated impact (as a qualitative level: High/Medium/Low or as a projected rating improvement percentage if sufficient data is available), sample size (number of ratings underlying the recommendation), and confidence level (High/Medium/Low based on sample size and pattern consistency).
>
> **Rationale:** Without this information, an operator cannot evaluate whether to act on a recommendation. The sample size and confidence level are particularly critical — they distinguish high-confidence signals from noise.
>
> **Acceptance Criteria:** A recommendation record in the API response contains all seven fields. The recommendations panel displays all fields in a readable format. Operators can sort recommendations by estimated impact or confidence level.

---

> **REQ-404** | Priority: MUST
>
> **Description:** Recommendations MUST be ordered by estimated impact (highest first) in the default view. An operator MUST be able to dismiss a recommendation (marking it as "not applicable" with a required reason) or mark it as actioned. Dismissed and actioned recommendations MUST be hidden from the default view but accessible via a filter.
>
> **Rationale:** Operators need to see the highest-leverage opportunities first. Dismissed and actioned recommendations must be preserved for audit purposes but should not clutter the active view.
>
> **Acceptance Criteria:** The default recommendations panel shows active recommendations ordered by estimated impact. Dismissing a recommendation requires a typed reason. Dismissed recommendations are hidden from the default view and visible under a "Dismissed" filter. Marking as actioned removes the recommendation from the default view and is logged with the operator identity and timestamp.

---

> **REQ-405** | Priority: MUST
>
> **Description:** The system MUST prevent duplicate recommendations for the same underlying pattern. If a pattern that generated a previous recommendation (whether active, dismissed, or actioned) recurs in a subsequent analysis run, the system MUST update the existing recommendation record rather than creating a new one.
>
> **Rationale:** Duplicate recommendations for the same issue create noise and make operators feel the system is not tracking their actions. An operator who dismissed a recommendation should not see it reappear unchanged.
>
> **Acceptance Criteria:** Running analysis twice on the same rating data produces the same number of recommendations, not double. An updated recommendation shows the refreshed sample size and impact estimate. A dismissed recommendation that reappears with significantly changed evidence (e.g., sample size doubled, impact estimate changed) resurfaces with a "Updated" label rather than silently staying dismissed.

---

> **REQ-406** | Priority: SHOULD
>
> **Description:** For Parameter Adjustment recommendations, the system SHOULD offer the operator the option to initiate a time-boxed A/B test comparing the current parameter value against the recommended value. The A/B test MUST randomly split queries between the two parameter configurations for a configured duration and collect rating data from both groups.
>
> **Rationale:** Acting on a parameter change recommendation without validation risks degrading quality for a different query population. An A/B test provides empirical validation before committing to a change.
>
> **Acceptance Criteria:** A "Start A/B Test" action is available on parameter adjustment recommendations. Initiating the test records the test configuration (current value, recommended value, duration, split ratio). Rating events during the test period are tagged with their A/B group. After the configured duration, the system reports rating averages for each group and recommends whether to adopt the change.

---

## 7. Feedback-Driven Ingestion Triggers (REQ-5xx)

> **REQ-501** | Priority: MUST
>
> **Description:** For Indexing Gap recommendations, the system MUST provide an operator action to approve an ingestion trigger directly from the recommendations panel. Approving the trigger MUST create a pre-approved Central Contribution submission (bypassing manual reviewer approval) and dispatch an ingestion run for the identified missing documents.
>
> **Rationale:** The full distance from "gap identified" to "gap filled" is the primary friction point in the feedback loop. Requiring the operator to separately navigate to the ingestion interface, identify the documents, and trigger a run creates enough friction that recommendations are noted but not acted on. Direct triggers compress this to a single approval action.
>
> **Acceptance Criteria:** An operator clicks "Approve Ingestion" on an indexing-gap recommendation. A pre-approved Central Contribution submission is created in the contribution store. An ingestion run is dispatched for the identified document source. The recommendation status updates to "actioned" with the ingestion run reference. The approval and ingestion trigger are logged in the audit trail.

---

> **REQ-502** | Priority: MUST
>
> **Description:** Every feedback-driven ingestion trigger MUST be recorded in the audit trail with: recommendation ID, operator identity, timestamp, document source, and ingestion run reference. The audit record MUST be written before the ingestion run is dispatched.
>
> **Rationale:** Feedback-driven triggers bypass the normal manual review step. The audit trail provides the accountability and traceability that the review step would otherwise provide.
>
> **Acceptance Criteria:** After approving a trigger, an audit log entry exists with all required fields. The log entry timestamp precedes the ingestion run dispatch timestamp. The audit log entry is queryable by recommendation ID. No trigger is dispatched without a corresponding audit log entry.

---

> **REQ-503** | Priority: MUST
>
> **Description:** The system MUST notify the operator when a feedback-driven ingestion run completes or fails. The notification MUST include the ingestion run status, chunk count (on success), and error summary (on failure).
>
> **Rationale:** An operator who approved a trigger has no visibility into ingestion progress without a notification. Silent completion or failure breaks the feedback loop — the operator cannot confirm that the gap has been filled.
>
> **Acceptance Criteria:** When a feedback-driven ingestion run completes, the operator who approved the trigger receives a notification with the chunk count. When the run fails, the operator receives a notification with a summary of the failure. The recommendation status is updated to reflect the ingestion outcome.

---

> **REQ-504** | Priority: SHOULD
>
> **Description:** The system SHOULD support a configurable auto-trigger policy that allows high-confidence Indexing Gap recommendations to initiate ingestion without explicit operator approval. Auto-triggers MUST be restricted to recommendations meeting configurable confidence and impact thresholds, and MUST be fully logged in the audit trail.
>
> **Rationale:** For high-volume, high-confidence gaps (e.g., a well-known internal document repository that is clearly missing from the index), manual approval for each recommendation adds operational overhead without adding meaningful safety. Auto-trigger with a confidence gate maintains safety while reducing friction.
>
> **Acceptance Criteria:** Auto-trigger is disabled by default. When enabled, only recommendations with confidence ≥ the configured threshold and impact ≥ the configured level trigger automatically. Each auto-trigger is logged in the audit trail with `trigger_type: automatic`. A human operator can review the auto-trigger log in the Admin Console. Disabling auto-trigger stops future auto-triggers without affecting in-progress ingestion runs.

---

## 8. Non-Functional Requirements (REQ-9xx)

> **REQ-901** | Priority: MUST
>
> **Description:** The rating capture endpoint MUST add no more than 100ms to the perceived response time for any interface. Rating persistence MUST be asynchronous — the endpoint MUST return before the rating is written to the store. The store write MUST complete within 5 seconds of the endpoint response under normal load.
>
> **Rationale:** User trust in the rating mechanism requires that submitting a rating never makes the interface feel slower. Any perceived latency at the moment of rating reduces submission rates.
>
> **Acceptance Criteria:** Measured p95 latency of the rating endpoint under 50 concurrent ratings is ≤100ms. A simulated store write delay of 10 seconds does not cause the rating endpoint to time out. Rating events submitted during a store write delay are durably persisted once the store recovers.

---

> **REQ-902** | Priority: MUST
>
> **Description:** If the rating event store is temporarily unavailable, the system MUST buffer incoming rating events in a durable in-process or queue-based buffer and persist them when the store recovers. The system MUST NOT lose rating events due to transient store unavailability.
>
> **Rationale:** Rating events accumulate slowly over time and each represents a real user interaction. Losing events during a store outage creates gaps in the pattern analysis data that cannot be reconstructed.
>
> **Acceptance Criteria:** With the rating store unavailable for 60 seconds, submitted ratings are buffered. After the store recovers, all buffered ratings are persisted. Rating submission continues to return within 100ms during the store outage. Zero rating events are lost.

---

> **REQ-903** | Priority: MUST
>
> **Description:** Pattern analysis runs MUST NOT measurably impact retrieval query serving latency. Analysis MUST execute on separate compute resources from the retrieval pipeline. If separate compute is unavailable, analysis MUST be scheduled during off-peak hours and throttled to limit resource consumption.
>
> **Rationale:** Analysis runs involve embedding computation and large aggregation queries. Running these on shared infrastructure during peak usage would degrade the primary user experience.
>
> **Acceptance Criteria:** During a full pattern analysis run, retrieval query p95 latency remains within 10% of the pre-run baseline. Analysis runs are not scheduled during the configured peak hours window. The peak hours window is configurable.

---

> **REQ-904** | Priority: MUST
>
> **Description:** All configurable parameters for the Feedback Loop MUST be externalized to environment variables with documented defaults.
>
> **Rationale:** Hardcoded parameters prevent operational tuning without code changes.
>
> **Acceptance Criteria:** The following parameters are configurable via environment variable: anonymization policy, rating event retention period, minimum sample size (clustering), minimum sample size (parameter correlation), minimum sample size (document flagging), analysis schedule, peak hours window, auto-trigger policy (enabled/disabled), auto-trigger confidence threshold, auto-trigger impact threshold, failure mode list. Each has a documented default. Changes take effect on server restart (or next analysis run for analysis parameters).

---

> **REQ-905** | Priority: MUST
>
> **Description:** The system MUST expose operational metrics for the feedback loop infrastructure: rating event ingestion rate, buffer depth (when store is unavailable), analysis run duration and status, recommendation count by category and status, and auto-trigger count. These metrics MUST be accessible via the admin health endpoint.
>
> **Rationale:** Without operational metrics, operators cannot detect a failing rating capture pipeline, a stalled analysis run, or an unexpectedly high auto-trigger rate.
>
> **Acceptance Criteria:** The health endpoint includes all listed feedback loop metrics. Metrics are updated in real time (rating rate) or after each run (analysis duration, recommendation count). A stalled analysis run (running longer than twice the historical average) is reflected in the health status.

---

## 9. Interface Contracts

### Rating Submission API

| Field | Value |
|-------|-------|
| Protocol | HTTP REST |
| Path | `POST /feedback/rate` |
| Authentication | User-level auth (API key or bearer token) |

**Request Schema:**
```json
{
  "query_response_id": "string — required, ID of the query response being rated",
  "rating": "thumbs_up | thumbs_down",
  "failure_mode": "string | null — selected from configured list, only on thumbs_down",
  "comment": "string | null — optional free text"
}
```

**Response Schema:**
```json
{
  "ok": true,
  "request_id": "string",
  "data": {
    "rating_id": "string — assigned ID for the stored rating event"
  }
}
```

### Recommendations API

| Field | Value |
|-------|-------|
| Protocol | HTTP REST |
| Path | `GET /console/recommendations` |
| Authentication | Admin role required |

**Response Schema:**
```json
{
  "ok": true,
  "request_id": "string",
  "data": {
    "recommendations": [
      {
        "id": "string",
        "category": "indexing_gap | parameter_adjustment | document_quality",
        "status": "active | dismissed | actioned",
        "description": "string — human-readable pattern description",
        "hypothesized_cause": "string",
        "suggested_action": "string",
        "estimated_impact": "high | medium | low",
        "sample_size": "integer",
        "confidence": "high | medium | low",
        "created_at": "string — ISO 8601",
        "updated_at": "string — ISO 8601"
      }
    ],
    "last_analysis_run": "string | null — ISO 8601 timestamp of last completed analysis run"
  }
}
```

---

## 10. Error Taxonomy

| Category | Examples | Severity | Expected Behavior |
|----------|----------|----------|-------------------|
| Transient | Rating event store temporarily unavailable | Recoverable | Buffer rating event; return 200 to client; persist when store recovers |
| Transient | Analysis run fails partway through | Recoverable | Log failure; retry on next scheduled run; do not surface partial recommendations |
| Validation | Rating submitted with unknown `query_response_id` | Client error | Return HTTP 400 with descriptive error; do not store partial event |
| Validation | Rating submitted without required `rating` field | Client error | Return HTTP 400 |
| Permanent | Analysis infrastructure permanently unavailable | Non-recoverable | Recommendations panel shows "Analysis unavailable" status; rating capture continues |
| Partial | Analysis run produces no patterns above minimum sample size | Degraded | Recommendations panel shows "Insufficient data" with current rating count; no error state |

---

## 11. System-Level Acceptance Criteria

| Criterion | Threshold | Related Requirements |
|-----------|-----------|---------------------|
| Rating capture non-blocking | p95 rating endpoint latency ≤100ms under 50 concurrent ratings | REQ-102, REQ-901 |
| Rating event durability | Zero events lost during 60-second store outage | REQ-902 |
| Cross-interface rating parity | Rating submitted via CLI appears in admin analytics alongside console-submitted ratings | REQ-101 |
| Anonymization policy enforcement | User identity in stored events conforms to configured policy for all three policy options | REQ-202 |
| Pattern minimum sample enforcement | No recommendation surfaced with sample size below configured minimum | REQ-304 |
| Analysis/serving isolation | Retrieval p95 latency within 10% of baseline during full analysis run | REQ-903 |
| Recommendation completeness | Every recommendation record contains all seven required fields | REQ-403 |
| Audit trail for triggers | Every feedback-driven trigger has a pre-dispatch audit log entry | REQ-502 |
| Auto-trigger safety gate | Auto-trigger disabled by default; enabled only via explicit configuration | REQ-504 |
| Configuration externalization | All parameters listed in REQ-904 configurable via env var | REQ-904 |

---

## 12. Requirements Traceability Matrix

| REQ ID | Section | Priority | Component |
|--------|---------|----------|-----------|
| REQ-101 | 3 | MUST | Rating Capture |
| REQ-102 | 3 | MUST | Rating Capture |
| REQ-103 | 3 | MUST | Rating Capture |
| REQ-104 | 3 | SHOULD | Rating Capture |
| REQ-105 | 3 | SHOULD | Rating Capture |
| REQ-106 | 3 | MUST | Rating Capture |
| REQ-201 | 4 | MUST | Context Snapshot Storage |
| REQ-202 | 4 | MUST | Context Snapshot Storage |
| REQ-203 | 4 | MUST | Context Snapshot Storage |
| REQ-204 | 4 | MUST | Context Snapshot Storage |
| REQ-301 | 5 | MUST | Query Pattern Analysis |
| REQ-302 | 5 | MUST | Query Pattern Analysis |
| REQ-303 | 5 | MUST | Query Pattern Analysis |
| REQ-304 | 5 | MUST | Query Pattern Analysis |
| REQ-305 | 5 | MUST | Query Pattern Analysis |
| REQ-306 | 5 | SHOULD | Query Pattern Analysis |
| REQ-401 | 6 | MUST | Tuning Recommendations |
| REQ-402 | 6 | MUST | Tuning Recommendations |
| REQ-403 | 6 | MUST | Tuning Recommendations |
| REQ-404 | 6 | MUST | Tuning Recommendations |
| REQ-405 | 6 | MUST | Tuning Recommendations |
| REQ-406 | 6 | SHOULD | Tuning Recommendations |
| REQ-501 | 7 | MUST | Feedback-Driven Ingestion Triggers |
| REQ-502 | 7 | MUST | Feedback-Driven Ingestion Triggers |
| REQ-503 | 7 | MUST | Feedback-Driven Ingestion Triggers |
| REQ-504 | 7 | SHOULD | Feedback-Driven Ingestion Triggers |
| REQ-901 | 8 | MUST | Non-Functional |
| REQ-902 | 8 | MUST | Non-Functional |
| REQ-903 | 8 | MUST | Non-Functional |
| REQ-904 | 8 | MUST | Non-Functional |
| REQ-905 | 8 | MUST | Non-Functional |

**Total Requirements: 31**
- MUST: 26
- SHOULD: 5
- MAY: 0

---

## Appendix A. Glossary

| Term | Definition |
|------|-----------|
| A/B Test | A controlled experiment that splits query traffic between two parameter configurations and measures rating outcomes for each group |
| Clustering | Grouping of semantically similar items by computing their embeddings and identifying nearby vectors in the embedding space |
| Confidence Level | A qualitative measure (High/Medium/Low) of how reliable a pattern or recommendation is, based on sample size and consistency |
| Embedding | A dense numerical vector representation of text, computed by the embedding model, used for semantic similarity comparison |
| Pattern | A statistically significant and reproducible correlation between query characteristics, system parameters, or source documents and low rating scores |
| Pseudonymization | Replacing identifying information with a stable non-reversible identifier that enables per-user analysis without exposing individual identity |
| Sample Size | The number of rating events underlying a pattern or recommendation, used to enforce minimum evidence thresholds |

## Appendix B. Document References

| Document | Purpose |
|----------|---------|
| `WEB_CONSOLE_SPEC.md` | Defines web console UI requirements; feedback rating controls integrate into the chat thread and admin query panel |
| `CLI_SPEC.md` | Defines CLI requirements; `/rate` command integrates into the REPL loop |
| `USER_CONTRIBUTION_SPEC.md` | Defines the Central Contribution workflow invoked by feedback-driven ingestion triggers |
| `INGESTION_PIPELINE_SPEC.md` | Defines the ingestion pipeline executed by feedback-driven triggers |
| `RETRIEVAL_QUERY_SPEC.md` | Defines retrieval parameters (alpha, search limit, rerank top-k) that are subject to parameter adjustment recommendations |
| `RAG_RETRIEVAL_PERFORMANCE_SPEC.md` | Defines benchmark-based quality evaluation; feedback loop provides complementary production quality signal |

## Appendix C. Open Questions

| # | Question | Context | Status |
|---|----------|---------|--------|
| OQ-1 | What datastore will be used for rating event storage? | REQ-203 requires a queryable store separate from the vector store. Options include a relational DB, a document store, or a time-series store. The choice affects analysis query expressiveness. | Requires infrastructure input |
| OQ-2 | What is the default anonymization policy? | REQ-202 requires a configurable policy. The default should reflect the organization's privacy posture. Starting with pseudonymous is a reasonable default but requires stakeholder confirmation. | Requires stakeholder input |
| OQ-3 | What compute resources are available for pattern analysis? | REQ-903 requires analysis to run on separate compute. If dedicated analysis infrastructure is unavailable, the off-peak scheduling fallback applies, but this limits how frequently recommendations can be refreshed. | Requires infrastructure input |
| OQ-4 | Should the failure mode list be managed in the Admin Console (dynamic) or via environment variable (static)? | A dynamic list allows operators to refine failure modes over time without a deployment. A static list is simpler to implement and audit. | Requires product input |
