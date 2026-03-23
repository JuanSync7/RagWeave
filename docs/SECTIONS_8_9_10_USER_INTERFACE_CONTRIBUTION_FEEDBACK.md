# Sections 8, 9, 10 — User Interface, User Contribution, Feedback Loop

**AION Knowledge Management Platform**
*Draft content for integration into the main system specification.*

---

## 8. User Interface

The User Interface layer is the primary means through which users interact with the RAG system in real time. Unlike the pipeline phases described in Section 7, the UI layer does not process documents — it translates user intent into pipeline requests and renders pipeline outputs in a form that is meaningful to the audience. The system exposes three equal-status surfaces: a User Console for end users, an Admin Console for operators and developers, and a CLI for engineers and automated workflows. All three are clients of the same backend infrastructure and are held to the same feature parity standard — a capability available in one surface must be available in all three, or explicitly documented as intentionally surface-specific. This parity principle means the choice of interface is a working style preference, not a capability constraint.

The eight components of this layer are:

### 8.1 User Console (Chat Interface)

This component is the browser-based interface served at `/console`. It presents a three-zone layout: a sidebar for conversation management on the left, a central message thread for the chat exchange, and an input bar at the bottom for query submission. When a user submits a query, the console streams generation tokens character-by-character as they arrive from the pipeline rather than waiting for the full answer, and then renders source citation cards below the answer so the user can inspect the retrieved documents that grounded the response. All diagnostic output — stage timings, raw scores, chunk metadata — is deliberately hidden from this surface. This separation is needed because end users require a clean, focused experience: exposing debug information to non-technical users creates confusion and erodes trust in the system.

We can adjust several aspects of this component to find the optimal performance and adoption, mainly:

- **Preset Selector:** A dropdown in the input bar allows the user to switch between named query presets (e.g., "fast", "quality", "detailed"). Presets encode combinations of retrieval depth, reranking settings, and generation parameters, so users can shift behavior with one click instead of manipulating hidden settings. Built-in presets are immutable; users may save custom presets that persist across sessions.

- **Source Filter Chip:** An optional chip in the input bar restricts retrieval to a named subset of the document corpus. This is the UX-level equivalent of metadata filtering in the retrieval pipeline — useful when a user knows the answer lies in a specific document collection and wants to avoid cross-domain noise.

- **Relevance Badge Thresholds:** The label attached to each source citation card ("High", "Medium", "Low") is driven by configurable percentage thresholds applied to the reranker score. Adjusting these thresholds changes how aggressively the UI signals confidence in each source to the user.

- **Theme and Responsive Layout:** The interface supports light and dark mode, persisted in browser local storage. The sidebar collapses to a hamburger menu on narrow viewports, keeping the interface usable on mobile and tablet screens.

### 8.2 Admin Console (Operator Dashboard)

This component is the browser-based interface served at `/console/admin`. It exposes the full operational surface of the RAG system through four mode tabs: **Query**, **Ingestion**, **Health**, and **Admin**. The Query tab provides every query parameter exposed by the API — source filters, heading filters, alpha, search limit, rerank top-k, fast path toggle, timeout, and stage budget overrides — and surfaces the diagnostic output that the User Console deliberately hides: stage timing breakdowns, raw chunk relevance scores, reranker scores, and source chunk previews. The Ingestion tab lets an operator trigger a pipeline run from the browser without constructing CLI commands, configuring target mode, path, update mode, and advanced pipeline options. The Health tab shows per-component readiness status with auto-refresh and optional log tailing. The Admin tab provides self-service API key and quota management with confirmation gates on destructive actions. This component exists because operators and developers need full diagnostic access to validate retrieval behavior, diagnose failures, and tune parameters — a purpose that cannot share the same interface as the clean end-user chat experience without compromising both.

We can adjust several aspects of this component to find the optimal performance, mainly:

- **Progressive Disclosure of Advanced Options:** Advanced query and ingestion parameters are collapsed by default in each panel, reducing visual noise for users performing standard operations. Expanding them reveals the full parameter surface. The degree of default collapse can be tuned per deployment based on the sophistication of the operator audience.

- **Health Panel Refresh Rate and Backoff:** The Health tab auto-refreshes component status at a configurable interval. When the API is unreachable, the interval increases exponentially to avoid overwhelming a struggling server. Tuning the base interval and backoff multiplier trades off status freshness against load on the API during degraded conditions.

- **Stage Timing Display Format:** Stage timings can be rendered as a flat table (each stage name and duration) or as a proportional timeline. The chosen format affects how quickly an operator can identify which pipeline stage is consuming the most budget.

- **Destructive Action Confirmation Depth:** Destructive admin operations (key revocation, quota deletion) require a confirmation dialog with a typed reason before execution. The reason is logged for audit. The required fields in this dialog can be tuned — fewer fields speed up operations; more fields improve the audit trail.

### 8.3 CLI Interface

This component exposes the same operational surface as the two consoles through three terminal entry points that share a common infrastructure layer. The **Local CLI** (`cli.py`) loads embedding, reranking, and generation models directly into the process and runs a full interactive REPL with two modes: query mode for asking questions and ingest mode for triggering document pipeline runs. The **Remote CLI** (`server/cli_client.py`) connects to a running API server over HTTP and SSE, providing the same REPL experience without loading any models locally — startup is near-instant, making it the preferred surface for day-to-day production querying. The **Ingestion CLI** (`ingest.py`) runs the document ingestion pipeline as a headless batch process suited for CI/CD pipelines and scheduled jobs. All three share the same command catalog, output formatting conventions, and preset system as the web consoles. The analogy to Claude Code is apt: just as Claude Code provides both a VS Code extension and a terminal CLI as equal-status surfaces for different working contexts, the AION system provides both browser consoles and a terminal CLI — the choice is a workflow preference, not a capability trade-off.

We can adjust several aspects of this component to find the optimal performance, mainly:

- **Entry Point Selection:** The Local CLI is best for development and experimentation where offline access or direct model inspection is needed. The Remote CLI is best for production querying against a running server without the overhead of loading models locally. The Ingestion CLI is best for automated batch processing. Choosing the right entry point for the workflow eliminates unnecessary startup latency and resource consumption.

- **Output Verbosity:** The default output shows the generated answer, retrieved sources, relevance scores, and timing summary. Verbose mode (via `/verbose on`) adds raw chunk content, full metadata, and debug traces. Quiet mode (via `/verbose off`) shows only the answer. Tuning verbosity reduces cognitive load for routine queries and maximizes diagnostic detail when troubleshooting.

- **Tab Completion and Live-Filtering Menu:** The Local CLI supports tab completion for commands and their arguments, derived from the shared command catalog. Typing `/` alone opens a live-filtering interactive menu that narrows available commands as the user types. Both features improve command discoverability and reduce input errors, particularly for users new to the system.

- **Configuration Externalization:** All CLI configuration — server URLs, model paths, default parameters, preset storage paths — is settable via environment variables, configuration files, or CLI flags. Precedence follows flag > environment variable > config file > default. This enables environment-specific configuration without code changes, making the CLI deployable across development, staging, and production environments without modification.

### 8.4 Shared Command and Preset System

This component maintains a single server-side catalog of slash commands and a named preset system available across all three surfaces. A user typing `/` in any input field — in either console or in the CLI — sees the same discoverable command list, including commands such as `/help`, `/new-chat`, `/history`, `/compact`, `/sources`, `/headings`, and `/preset`. Commands are dispatched to a unified server-side endpoint that receives the command name, arguments, source surface, and current state, and returns a normalized response that each surface renders independently. Presets are named collections of query parameters (model selection, source filters, heading filters, retrieval settings) that can be saved, loaded, and applied across all three surfaces. This component exists because without a single source of truth for commands and presets, the three surfaces drift: a new command added to the CLI might not appear in the console, or a preset saved in one surface cannot be loaded in another, creating a fragmented experience and a growing maintenance burden.

We can adjust several aspects of this component to find the optimal performance, mainly:

- **Command Scoping:** Commands can be marked as available on all surfaces, or explicitly scoped to a single surface (e.g., a terminal-specific key binding command available only in the CLI, or a mouse-driven interaction available only in the consoles). Scoping decisions must be explicit and documented; undocumented surface-specific commands are treated as parity violations.

- **Preset Storage Layers:** Built-in presets (e.g., "fast", "quality", "debug") are immutable and served from the server catalog. Custom presets are persisted in browser local storage for console surfaces and on disk for the CLI. The storage key prefix and file path are configurable, enabling per-deployment isolation so different teams or projects can maintain separate preset libraries.

- **Command Autocomplete Depth:** In both consoles, the command picker filters results as the user types. In the CLI, tab completion provides the same discovery. The depth of argument-level completion — for example, offering preset names after `/preset load`, or available source names after `/sources` — can be extended independently for each surface to reduce input errors for complex commands.

### 8.5 Conversation Management

This component maintains multi-turn conversation state across all surfaces. When a user submits a query, the active conversation ID and a memory-enabled flag are passed to the retrieval pipeline alongside the query text. The pipeline can then incorporate a rolling summary of prior turns (memory context) into the prompt sent to the generation model, enabling coherent follow-up questions. Both consoles display the conversation list in a sidebar or panel and allow creating new conversations, selecting existing ones, and viewing history. The CLI maintains a conversation ID for the REPL session and passes it with each query. A conversation started in the User Console is accessible from the Admin Console and vice versa, because both surfaces share the same conversation backend. This component is needed because without persistent multi-turn state, every query is treated as independent — users cannot ask follow-up questions, and the system cannot use prior context to resolve ambiguous queries.

We can adjust several aspects of this component to find the optimal performance, mainly:

- **Memory Toggle:** Memory can be enabled or disabled per query. Disabling memory treats each query as stateless, which is useful for diagnostic queries where prior context might contaminate retrieval, or for users who prefer each query to be independent. The default state (on or off) is configurable per deployment.

- **Conversation Compaction Trigger:** Long conversations accumulate memory context that eventually consumes a significant portion of the LLM's context window. The `/compact` command triggers a server-side rolling summary that condenses prior turns into a shorter summary, freeing context budget for new queries. The compaction trigger can be manual-only (user-initiated) or automatic when usage exceeds a configurable threshold. See Section 8.6 for the token budget display that signals when compaction is advisable.

- **Conversation Title Generation:** Conversation entries in the sidebar are labeled with the first message preview by default. A fast LLM call can instead generate a descriptive title from the first exchange. Enabling this improves sidebar navigability at the cost of an additional LLM invocation per new conversation.

### 8.6 Token Budget Display

This component gives users real-time visibility into how much of the generation model's context window the current interaction is consuming. After each query, it estimates the total input token count by summing character-length heuristics across every prompt component — the system prompt, the memory context summary, the retrieved chunks, the user query, and template formatting overhead — and expresses it as a percentage of the effective context window (total context length minus the output token reservation). The result is displayed as a persistent status indicator: a fixed status bar at the bottom-right of either console, or a right-aligned summary line in the CLI. When usage approaches warning (≥70%) or critical (≥90%) thresholds, the indicator changes color — amber at warning, red at critical. This component is needed because context window exhaustion is silent without a budget display: the LLM may truncate input or degrade quality without any visible error, and users have no signal to prompt them to compact the conversation, reduce retrieval depth, or switch to a model with a larger context window.

We can adjust several aspects of this component to find the optimal performance, mainly:

- **Characters-per-Token Ratio:** The default estimation heuristic is 4 characters per token, which is accurate within ±20% for English text on common model families. This ratio is configurable via environment variable. Models used with code-heavy content or non-Latin scripts may warrant a lower ratio (e.g., 3 characters per token) for a tighter estimate.

- **Warning and Critical Thresholds:** The color-change thresholds (default: 70% for amber, 90% for red) are configurable via environment variables. Lowering the warning threshold gives users more lead time before context pressure becomes acute; raising it reduces alarm fatigue for workflows that routinely operate at high utilization.

- **Per-Component Breakdown:** The estimation can be extended to surface a breakdown of which prompt component (memory context, retrieved chunks, system prompt, etc.) is consuming the most budget. This breakdown helps users decide whether to compact the conversation (to reduce memory context tokens) or reduce retrieval depth (to reduce chunk tokens), rather than guessing at the cause.

- **Model Capability Refresh:** Context window size is fetched from the LLM backend at startup and cached. If an operator switches to a different model at runtime, a refresh mechanism updates the cached context length without requiring a server restart. Without this, the budget percentage would be calculated against the wrong denominator.

### 8.7 User Contribution (UI)

This component provides the in-interface workflows through which users can contribute documents to the knowledge base. Two distinct flows exist: a **Central Contribution** flow for requesting that a document be added to the shared organizational index, and a **Local Contribution** flow for uploading documents to a personal, session-scoped index that does not affect the central database or other users' sessions.

The Central Contribution UI presents a submission form accessible from both consoles and the CLI. The form captures the document source (URL or file upload), a description of the content, the suggested document category, and the submitter's contact information. Upon submission, the user receives a confirmation with a tracking reference and can check submission status via a status view in the console sidebar or via a CLI command. The form also surfaces feedback when a submission is accepted or rejected, including the reason for rejection where applicable.

The Local Contribution UI presents a file picker or drag-and-drop zone accessible from either console, or a file path argument in the CLI. Uploaded documents are processed through an isolated ingestion pipeline run scoped to the current user session and stored in a personal index partition that is invisible to other users and does not modify the central vector store. A session document list in the sidebar shows which personal documents are currently active, and a clear/remove action purges them from the session.

The backend ingestion pipeline, approval workflow, storage isolation mechanisms, and governance model for both flows are specified in **Section 9**.

### 8.8 Feedback Loop (UI)

This component provides the in-interface mechanisms through which users signal answer quality, enabling the system to capture real-world query patterns and failure modes for parameter tuning.

After each assistant response in the User Console, a lightweight rating row appears below the source citation cards: a thumbs-up and thumbs-down button, with an optional free-text comment field that expands on thumbs-down. In the Admin Console query panel, the same rating controls appear alongside the diagnostic output, with an additional structured failure-mode selector (e.g., "wrong sources retrieved", "answer hallucinated", "too vague"). In the CLI, a `/rate` command accepts a score and optional comment for the most recent response. All three surfaces route ratings through the same backend endpoint.

The rating capture is lightweight and non-blocking — submitting a rating does not interrupt the workflow or require the user to navigate away. Ratings are associated with the query text, retrieved chunk IDs, query parameters, and response metadata at the time of submission, giving the analytics layer full context to identify which parameter combinations correlate with low ratings.

The backend storage, aggregation pipeline, and tuning recommendation generation for this data are specified in **Section 10**.

---

## 9. User Contribution

The User Contribution feature enables users to extend the knowledge base through two mechanisms: requesting documents be added to the shared organizational index (Central Contribution), and uploading documents to a personal session-scoped index that does not affect other users (Local Contribution). Both mechanisms feed into the document ingestion pipeline described in Section 6, but with different scoping, approval, and isolation models.

The four components of this feature are:

### 9.1 Central Contribution — Submission and Approval Workflow

This step receives a document submission from a user, validates it, routes it through an approval queue, and — upon approval — triggers an ingestion run that adds the document to the central vector store. The approval step is needed because the central index is shared across all users: unapproved or low-quality documents would degrade retrieval quality for the entire organization. The workflow must be lightweight enough that submitters receive timely feedback and are not discouraged from contributing, while giving reviewers enough context to make an informed decision.

The submission payload includes: the document source (file upload or URL), a submitter-provided description and suggested category, and the submitter's identity. Upon receipt, the system validates that the document is reachable or non-empty, generates a tracking reference, and places the submission in a reviewer queue. Reviewers (a designated group with admin role) see the queue in the Admin Console and can accept, reject, or defer submissions with a typed reason. Accepted submissions automatically trigger an ingestion pipeline run targeting the central index. Rejected submissions notify the submitter with the reviewer's reason.

We can adjust several aspects of this step to find the optimal performance, mainly:

- **Reviewer Assignment:** Submissions can be assigned to a specific reviewer or placed in a shared queue. A shared queue is simpler to operate but can create bottlenecks; per-category routing (based on the submitter's suggested category) distributes review load and brings domain expertise to each submission.

- **Auto-Approval Rules:** Submissions from trusted sources (e.g., internal document management systems, specific authenticated principals) can be configured for automatic approval, bypassing the manual review queue. This trades review oversight for throughput and is appropriate for high-volume, low-risk source types.

- **Notification Channel:** Submitters and reviewers receive status notifications. The notification channel (email, Slack, in-app only) and trigger events (submission received, review assigned, decision made) are configurable per deployment.

### 9.2 Central Contribution — Ingestion Integration

This step takes an approved document submission and executes the standard ingestion pipeline (loading, chunking, embedding, storing) targeting the central vector store. Because the central index is shared, this step must be idempotent — re-ingesting a document that already exists should update its chunks rather than create duplicates — and must operate without disrupting active user queries.

The ingestion run triggered by an approval is identical in behavior to a manually triggered admin ingestion run, with two additions: the submission metadata (submitter identity, approval timestamp, reviewer identity) is stored alongside the document metadata, providing a full provenance chain; and the submitter is notified when the ingestion run completes, including a summary of how many chunks were indexed.

We can adjust several aspects of this step to find the optimal performance, mainly:

- **Ingestion Priority:** Approved submissions can be queued at normal or elevated priority relative to scheduled ingestion runs. Elevated priority ensures timely availability of approved documents; normal priority prevents user submissions from starving scheduled maintenance runs.

- **Duplicate Detection:** Before ingestion, the system can check whether the document's content hash already exists in the central index. If it does, the system can skip re-ingestion, notify the reviewer that the document is already indexed, and close the submission without consuming pipeline resources.

### 9.3 Local Contribution — Session-Scoped Ingestion

This step receives a file upload from a user and runs a scoped ingestion pipeline that stores chunks in a personal index partition associated with the user's current session. The personal partition is invisible to other users and is not merged into the central vector store. When the user submits a query, the retrieval pipeline searches both the central index and the personal partition, with personal documents clearly labeled in the citation output so the user knows which sources came from their own uploads. This step is needed because users often have internal working documents, draft materials, or domain-specific files that are relevant to their queries but not appropriate for the shared organizational index.

We can adjust several aspects of this step to find the optimal performance, mainly:

- **Partition Lifetime:** Personal index partitions can be scoped to the browser session (cleared on tab close), to the conversation (cleared when a new conversation is started), or to a configurable duration (e.g., 24 hours). Shorter lifetimes reduce storage accumulation; longer lifetimes let users return to a session across multiple working periods.

- **Storage Isolation Enforcement:** Personal partitions must be isolated at the vector store level — a query from one user must never retrieve chunks from another user's personal partition. The isolation boundary (namespace, collection, or tenant) is determined by the vector store implementation and must be validated as part of deployment verification.

- **File Type and Size Limits:** Accepted file types and maximum file sizes for personal uploads are configurable per deployment. Restricting to common document types (PDF, DOCX, TXT, MD) and capping file size (e.g., 10MB) reduces pipeline load and prevents abuse.

### 9.4 Central Contribution — Governance and Policy

This component defines the organizational rules that govern the Central Contribution workflow. It exists outside the software system but must be reflected in the system's configuration and reviewer tooling.

At minimum, the governance model must define: who is authorized to submit documents (all authenticated users, specific roles, or specific teams); who is authorized to approve submissions (reviewer group membership and rotation policy); what the target review turnaround time is (e.g., 5 business days); what rejection reasons are permissible (e.g., duplicate, out of scope, quality below threshold, licensing concern); and what recourse submitters have when a submission is rejected (appeal process, resubmission with revisions).

The system enforces the governance model by: restricting submission endpoints to authorized principals; restricting approval endpoints to reviewer-role principals; logging all decisions with timestamps and reasons; and reporting queue age metrics to surface submissions approaching the turnaround SLA.

We can adjust several aspects of this component over time, mainly:

- **Submission Eligibility:** Initially restricting submissions to a pilot group and expanding eligibility as the review workflow matures reduces early operational load and allows the governance model to be refined before scaling.

- **Review SLA Alerting:** Configuring alerts when submissions exceed the target review turnaround time (e.g., notifying the reviewer group lead after 3 business days) prevents queue stagnation without requiring manual monitoring.

---

## 10. Feedback Loop

The Feedback Loop feature captures real-world query patterns, user ratings, and failure modes from production usage and surfaces them as actionable recommendations for parameter tuning. It closes the gap between pipeline configuration decisions made at deployment time and the actual retrieval and generation quality experienced by users in the field. Without this loop, parameter tuning is driven by synthetic benchmarks and developer intuition; with it, tuning is driven by observed user outcomes at scale.

The four components of this feature are:

### 10.1 Rating Capture

This step receives a user rating event — a thumbs-up, thumbs-down, or structured failure-mode selection — and stores it alongside a full snapshot of the query context at the time of the rating. The context snapshot includes: the query text, the active query parameters (preset, source filter, alpha, search limit, rerank top-k), the retrieved chunk IDs and their scores, the generated answer text, the conversation ID, the user identity (anonymized or pseudonymized per deployment policy), and the timestamp. Capturing the full context alongside the rating is critical: a thumbs-down on its own tells you something went wrong; the context snapshot tells you *which parameters and retrieved sources were active when it went wrong*, making the rating actionable for tuning.

We can adjust several aspects of this step to find the optimal performance, mainly:

- **Rating Granularity:** A binary thumbs-up/down is the lowest-friction rating mechanism and maximizes submission rate. Adding a structured failure-mode selector (wrong sources, hallucinated answer, too vague, off-topic) increases diagnostic value at the cost of slightly higher friction. The right balance depends on the user population — technical users in the Admin Console can be offered more structure; end users in the User Console should see only the simplest rating UI.

- **Comment Capture:** An optional free-text comment field on thumbs-down provides qualitative signal that structured selectors cannot capture. Comments should be surfaced in the analytics dashboard alongside the structured ratings. Comments should not be required — making them optional maximizes the number of ratings submitted.

- **Rating Anonymization:** Depending on organizational policy, ratings can be stored with full user identity (for accountability and follow-up), with a pseudonymous session ID (for pattern analysis without individual attribution), or fully anonymized. The anonymization policy is configurable per deployment.

### 10.2 Query Pattern Analysis

This step aggregates captured ratings and query metadata to identify patterns that correlate with poor outcomes. Rather than examining individual ratings, it looks at the distribution: which query types consistently produce low ratings, which parameter combinations correlate with high ratings, which source documents are frequently retrieved for low-rated queries, and which failure modes appear most frequently. This step transforms raw rating events into structured insights that a system operator can act on.

Key analyses include:

- **Low-Rating Query Clusters:** Grouping low-rated queries by semantic similarity (using the same embedding model as the retrieval pipeline) to identify topic areas where the system consistently underperforms. A cluster of low-rated queries about a specific domain suggests either missing documents in the index or a retrieval parameter mismatch for that domain.

- **Parameter Correlation Analysis:** Correlating rating scores with the active query parameters at the time of the query. If queries run with a low rerank top-k consistently receive lower ratings than queries with a higher top-k, this is a signal to raise the default.

- **Source Document Quality Signals:** Identifying source documents that are frequently retrieved for low-rated queries but rarely for high-rated queries. These documents may be low quality, poorly chunked, or semantically misleading — candidates for review or re-ingestion.

We can adjust several aspects of this step to find the optimal performance, mainly:

- **Analysis Cadence:** Pattern analysis can run on a scheduled basis (e.g., weekly), on demand from the Admin Console, or continuously as a background process. Scheduled analysis is lowest overhead; continuous analysis provides the fastest feedback but requires dedicated compute.

- **Minimum Rating Volume:** Pattern analysis should require a minimum number of ratings per cluster or parameter combination before surfacing a recommendation, to prevent false signals from small samples. The minimum threshold is configurable and should be tuned based on query volume.

### 10.3 Tuning Recommendations

This step takes the output of query pattern analysis and formats it as human-readable tuning recommendations surfaced in the Admin Console. Each recommendation includes: the observed pattern (e.g., "queries about Project X receive low ratings 68% of the time"), the hypothesized cause (e.g., "Project X documents are not indexed; 0 chunks retrieved for these queries"), the suggested action (e.g., "ingest the Project X document library via the Central Contribution workflow"), and the expected impact (e.g., "based on similar patterns, ingesting missing documents reduced low-rating rate by ~40%"). Recommendations are presented as a prioritized list, ordered by estimated impact, and each can be dismissed or marked as actioned.

Recommendations fall into three categories:

- **Indexing Gaps:** Queries for which no relevant sources were retrieved, suggesting missing documents. The recommended action is to add documents via the Central Contribution workflow (Section 9).

- **Parameter Adjustments:** Parameter combinations that correlate with low ratings. The recommended action is a specific configuration change (e.g., "increase rerank top-k from 5 to 10 for queries matching this pattern") with a link to the relevant Admin Console parameter control.

- **Document Quality Issues:** Source documents that are frequently retrieved for low-rated queries. The recommended action is to review, improve, and re-ingest the flagged documents.

We can adjust several aspects of this step to find the optimal performance, mainly:

- **Recommendation Confidence Display:** Each recommendation should display the sample size and confidence level behind the observed pattern, so operators can distinguish high-confidence recommendations (based on hundreds of ratings) from low-confidence ones (based on a handful). This prevents operators from acting on noise.

- **A/B Testing Integration:** For parameter adjustment recommendations, the system can offer to run a time-boxed A/B test comparing the current parameter value against the recommended value, with the rating data from the test period used to validate the recommendation before committing the change.

### 10.4 Feedback-Driven Ingestion Triggers

This step closes the loop between the Feedback Loop and the ingestion pipeline by enabling recommendations to trigger ingestion actions directly. When the query pattern analysis identifies an indexing gap, the operator can approve the recommended ingestion action from the Admin Console without navigating to the Ingestion tab or constructing CLI commands. The approved action creates a Central Contribution submission (see Section 9.1) in a pre-approved state, bypassing the manual review queue, and triggers an ingestion run for the identified missing documents.

This integration is needed because the distance between "the system identifies a gap" and "the gap is filled" is the primary friction point in the feedback loop. Requiring an operator to manually identify the relevant documents, navigate to the ingestion interface, and trigger a run creates enough friction that recommendations are often noted but not acted on. Direct ingestion triggers from recommendations reduce this friction to a single approval action.

We can adjust several aspects of this step to find the optimal performance, mainly:

- **Auto-Trigger Policy:** For high-confidence recommendations where the missing documents are already known to the system (e.g., documents in the repository that have not yet been indexed), auto-triggering ingestion without manual approval can be enabled. This should be restricted to low-risk document types and require an audit log entry.

- **Re-Ingestion Scheduling:** When a document quality issue is identified, the recommended re-ingestion can be scheduled for an off-peak window rather than triggered immediately, to avoid competing with active user query load during business hours.
