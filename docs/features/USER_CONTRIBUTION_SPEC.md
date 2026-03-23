# User Contribution Specification

**AION Knowledge Management Platform**
Version: 1.0 | Status: Draft | Domain: User Contribution

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-03-18 | AI Assistant | Initial specification |

> **Document intent:** This is a normative requirements/specification document for the User Contribution feature.
> For the implementation plan, see `USER_CONTRIBUTION_IMPLEMENTATION.md`.
> For UI surface behavior, see `WEB_CONSOLE_SPEC.md` and `CLI_SPEC.md`.
> For ingestion pipeline internals, see `INGESTION_PIPELINE_SPEC.md`.

---

## 1. Scope & Definitions

### 1.1 Problem Statement

The RAG system's central knowledge base is curated at deployment time and updated only by operators with direct access to the ingestion pipeline. This creates a structural bottleneck: subject-matter experts who encounter gaps in the system's knowledge must route requests through the operations team, creating delays, lost institutional knowledge, and reduced user trust in the system's coverage. Additionally, users frequently need to query against personal working documents — drafts, meeting notes, project files — that are relevant to their current task but inappropriate for inclusion in the shared organizational index. Without a personal upload capability, these users must maintain a separate workflow outside the RAG system, defeating its purpose as a unified knowledge interface.

### 1.2 Scope

This specification defines requirements for the **User Contribution** feature. The boundary is:

- **Entry point (Central):** A user submits a document contribution request via the web console form or CLI command.
- **Exit point (Central):** The document is indexed in the central vector store and the submitter receives a completion notification, OR the submission is rejected and the submitter receives the rejection reason.
- **Entry point (Local):** A user uploads a document to their personal session index via the web console file picker or CLI file path argument.
- **Exit point (Local):** The document is available for retrieval in the user's active session and appears in their personal document list.

Everything between these points is in scope, including submission validation, the reviewer approval queue, ingestion triggering, personal index isolation, partition lifecycle management, and governance enforcement.

### 1.3 Terminology

| Term | Definition |
|------|-----------|
| **Central Contribution** | The workflow by which a user requests that a document be added to the shared organizational index, subject to reviewer approval |
| **Local Contribution** | The workflow by which a user uploads a document to their own session-scoped personal index, without affecting the central index or other users |
| **Submission** | A Central Contribution request containing a document source, description, category, and submitter identity |
| **Reviewer** | An operator with admin role who is authorized to accept or reject submissions in the approval queue |
| **Approval Queue** | The ordered list of pending submissions awaiting reviewer action, displayed in the Admin Console |
| **Personal Index** | A session-scoped partition of the vector store that holds documents uploaded by a single user and is invisible to all other users |
| **Partition Lifetime** | The duration for which a personal index partition and its documents are retained before automatic purge |
| **Provenance Record** | The metadata stored alongside an ingested document recording its submission origin, submitter identity, approval timestamp, and reviewer identity |
| **Content Hash** | A deterministic hash of a document's byte content used to detect duplicate submissions before ingestion |
| **Tracking Reference** | A unique identifier assigned to each Central Contribution submission, used by the submitter to check submission status |
| **Auto-Approval Rule** | A configurable rule that allows submissions from trusted sources to bypass manual reviewer approval |

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
| 3 | REQ-1xx | Submission & Validation |
| 4 | REQ-2xx | Central Approval Workflow |
| 5 | REQ-3xx | Central Ingestion Integration |
| 6 | REQ-4xx | Local Contribution & Session Index |
| 7 | REQ-5xx | Governance & Audit |
| 8 | REQ-9xx | Non-Functional Requirements |

### 1.6 Assumptions & Constraints

| ID | Assumption / Constraint | Impact if Violated |
|----|------------------------|--------------------|
| A-1 | The existing ingestion pipeline (`INGESTION_PIPELINE_SPEC.md`) is reused for Central Contribution ingestion runs | A separate ingestion implementation is required, risking behavioral divergence |
| A-2 | The vector store supports namespaced or tenant-scoped partitions for personal index isolation | Personal index isolation requires an alternative storage mechanism |
| A-3 | Both web consoles and the CLI share the same backend API endpoints for submission and personal upload | Separate backends fragment data and break cross-surface consistency |
| A-4 | Reviewer identity is established via the existing role-based auth system (admin role) | A separate reviewer authorization system must be built |
| A-5 | File content is available server-side after upload for hashing and validation | Client-side hash computation must substitute if server-side access is unavailable |
| A-6 | Notification delivery (email, Slack, in-app) is handled by an external notification service | An in-house notification system must be built if no external service is available |

### 1.7 Design Principles

| Principle | Description |
|-----------|-------------|
| **Low-friction submission** | The Central Contribution workflow must be lightweight enough that users are not discouraged from contributing. Every additional required field or step reduces participation. |
| **Hard isolation for personal indexes** | Personal index partitions must be isolated at the storage layer, not only at the application layer. Application-layer isolation can be bypassed by bugs or misconfiguration; storage-layer isolation cannot. |
| **Idempotent ingestion** | Approving a submission that has already been indexed must update the existing entry rather than create a duplicate. Duplicate chunks degrade retrieval quality. |
| **API-layer enforcement** | All access control — submission eligibility, reviewer authorization, personal index scoping — must be enforced at the API layer, not only in the UI. UI gating is a convenience, not a security boundary. |
| **Graceful degradation** | Submission capture and personal index operations must continue to function even when the ingestion pipeline is temporarily unavailable. Submissions should queue rather than fail. |

### 1.8 Out of Scope

- Ingestion pipeline internals (chunking, embedding, storage) — see `INGESTION_PIPELINE_SPEC.md`
- Web console UI layout and component design — see `WEB_CONSOLE_SPEC.md`
- CLI command system and REPL behavior — see `CLI_SPEC.md`
- Feedback and quality rating of query results — see `FEEDBACK_LOOP_SPEC.md`
- Bulk import tools for initial corpus loading — covered by Ingestion CLI
- Document versioning and change tracking within the central index

---

## 2. System Overview

### 2.1 Architecture Diagram

```
User / Operator (Browser or CLI)
         │
         ├─────────────────────────────────┐
         │                                 │
         ▼                                 ▼
┌─────────────────────┐         ┌──────────────────────┐
│ [1] CENTRAL         │         │ [2] LOCAL            │
│     CONTRIBUTION    │         │     CONTRIBUTION     │
│                     │         │                      │
│  Submission form    │         │  File upload / path  │
│  Status tracking    │         │  Personal doc list   │
│  Notification       │         │  Remove / clear      │
└────────┬────────────┘         └─────────┬────────────┘
         │                                │
         ▼                                ▼
┌─────────────────────────────────────────────────────┐
│ [3] CONTRIBUTION API                                │
│     POST /contributions/submit                      │
│     GET  /contributions/status/:ref                 │
│     POST /contributions/review (admin)              │
│     POST /personal/upload                           │
│     GET  /personal/documents                        │
│     DELETE /personal/documents/:id                  │
└───────────┬───────────────────┬─────────────────────┘
            │                   │
            ▼                   ▼
┌──────────────────┐  ┌──────────────────────────────┐
│ [4] APPROVAL     │  │ [5] INGESTION PIPELINE       │
│     QUEUE        │  │                              │
│     (Admin only) │  │  Central index (shared)      │
│                  │  │  Personal index (per-user)   │
│  Pending         │  │                              │
│  Review          │  │  Same pipeline as scheduled  │
│  Notify          │  │  ingestion runs              │
└──────────────────┘  └──────────────────────────────┘
```

### 2.2 Data Flow Summary

| Flow | Entry | Processing | Exit |
|------|-------|------------|------|
| Central Contribution (submit) | User submits form/command | Validate → assign tracking ref → enqueue | Submission stored, tracking ref returned to user |
| Central Contribution (review) | Reviewer accepts/rejects | Decision logged → notify submitter | If accepted: ingestion triggered |
| Central Contribution (ingest) | Approved submission | Dedup check → ingest pipeline → provenance stored | Submitter notified of completion |
| Local Contribution (upload) | User uploads file | Validate → ingest into personal partition | Document available in session index |
| Local Contribution (query) | User submits query | Retrieved chunks include personal partition | Citations labeled as personal documents |
| Local Contribution (purge) | Partition lifetime expires | Delete personal partition chunks | Personal index cleared |

---

## 3. Submission & Validation (REQ-1xx)

> **REQ-101** | Priority: MUST
>
> **Description:** The system MUST accept Central Contribution submissions through all three interfaces: the User Console submission form, the Admin Console submission form, and the CLI submit command. All three interfaces MUST route to the same backend submission endpoint.
>
> **Rationale:** CLI/UI parity requires that every capability is accessible from all surfaces. Users working in the CLI must not need to switch to a browser to submit a document.
>
> **Acceptance Criteria:** A document submitted via the CLI appears in the Admin Console reviewer queue. A document submitted via the User Console appears in the same queue with the same fields. The backend endpoint is identical in both cases.

---

> **REQ-102** | Priority: MUST
>
> **Description:** The submission payload MUST include: document source (file upload or URL), a submitter-provided description (free text, required), a suggested category (selection from a configured list, required), and the submitter's authenticated identity (derived from auth context, not a user-supplied field).
>
> **Rationale:** Description and category give reviewers the context needed to make an informed decision without opening the document. Deriving submitter identity from auth context prevents spoofing.
>
> **Acceptance Criteria:** Submissions without a description are rejected with a validation error. Submissions without a category are rejected with a validation error. Submitter identity in the stored record matches the authenticated principal, regardless of any identity field the user may have supplied.

---

> **REQ-103** | Priority: MUST
>
> **Description:** The system MUST validate submitted documents before accepting the submission. Validation MUST check: for URL sources, that the URL is reachable and returns a non-empty document body; for file uploads, that the file is non-empty and the file type matches the configured allowlist. Validation failures MUST return a descriptive error message identifying the specific failure.
>
> **Rationale:** Accepting invalid submissions wastes reviewer time and creates ingestion failures downstream. Early validation surfaces the problem at the point where the submitter can fix it.
>
> **Acceptance Criteria:** Submitting a URL that returns HTTP 404 is rejected with an error identifying the URL as unreachable. Submitting a file type not on the allowlist is rejected with an error listing the allowed types. Submitting an empty file is rejected with a specific error. Valid submissions proceed to the queue.

---

> **REQ-104** | Priority: MUST
>
> **Description:** The system MUST assign a unique tracking reference to each accepted submission and return it to the submitter immediately. The submitter MUST be able to query submission status using this tracking reference via any interface.
>
> **Rationale:** Users need a way to check whether their submission was approved, rejected, or is still pending without requiring them to remember submission details or contact a reviewer directly.
>
> **Acceptance Criteria:** Every successful submission response includes a tracking reference. A status query using that reference returns the current state (pending, approved, rejected, ingested) and, where applicable, the reviewer's decision reason. Status is queryable via CLI and both consoles.

---

> **REQ-105** | Priority: MUST
>
> **Description:** The system MUST enforce configurable file size limits for Central Contribution uploads. Submissions exceeding the limit MUST be rejected at upload time with an error stating the limit and the actual file size.
>
> **Rationale:** Unbounded file sizes can exhaust storage, slow ingestion, and create denial-of-service conditions. Rejecting at upload time avoids wasting queue and reviewer resources on invalid submissions.
>
> **Acceptance Criteria:** Uploading a file larger than the configured limit returns an error before the submission is stored. The error message states the configured limit and the submitted file size. The limit is configurable via environment variable without code changes.

---

> **REQ-106** | Priority: SHOULD
>
> **Description:** The system SHOULD perform a content hash dedup check at submission time and notify the submitter if an identical document (by content hash) already exists in the submission queue or the central index. The system SHOULD allow the submission to proceed with a warning rather than blocking it outright.
>
> **Rationale:** Duplicate submissions waste reviewer time. Early notification lets submitters reconsider without hard-blocking contributions that may have legitimate reasons for re-submission (e.g., re-submitting a document to trigger re-chunking with different settings).
>
> **Acceptance Criteria:** Submitting a document whose content hash matches an existing indexed document produces a warning in the submission response indicating the document may already be indexed. The submission proceeds if the user confirms. A submission with no matching hash proceeds without a warning.

---

## 4. Central Approval Workflow (REQ-2xx)

> **REQ-201** | Priority: MUST
>
> **Description:** The system MUST provide a reviewer queue in the Admin Console displaying all pending submissions ordered by submission timestamp (oldest first). Each queue entry MUST display: tracking reference, submitter identity, submission timestamp, document source (URL or filename), description, and suggested category.
>
> **Rationale:** Reviewers need sufficient context to make an informed decision without navigating to each submission individually. Oldest-first ordering prioritizes submissions approaching the SLA limit.
>
> **Acceptance Criteria:** The reviewer queue is visible in the Admin Console to users with admin role. Users without admin role do not see the queue. Each entry displays all required fields. Entries are ordered oldest-first. The queue updates without a full page reload when a new submission arrives.

---

> **REQ-202** | Priority: MUST
>
> **Description:** A reviewer MUST be able to take one of three actions on a pending submission: **Accept** (triggers ingestion), **Reject** (notifies submitter with reason), or **Defer** (keeps submission in queue with an optional internal note). All three actions MUST require a typed reason. Accepted and rejected submissions MUST be removed from the active queue.
>
> **Rationale:** Defer allows a reviewer to note a pending question without taking a final decision. Requiring a reason for all actions creates an audit trail and forces reviewers to articulate their decision.
>
> **Acceptance Criteria:** Clicking Accept without a typed reason is blocked with a validation prompt. Clicking Reject without a typed reason is blocked. Accepted submissions trigger an ingestion run and move to an "accepted" state. Rejected submissions move to a "rejected" state and the submitter receives notification with the reason. Deferred submissions remain in the queue.

---

> **REQ-203** | Priority: MUST
>
> **Description:** The system MUST notify the submitter when a submission decision is made. The notification MUST include: the decision (accepted or rejected), the reviewer's reason, and — for acceptances — the expected ingestion timeline. The notification channel (in-app, email, or Slack) MUST be configurable.
>
> **Rationale:** Submitters have no visibility into queue state without notifications. A timely decision notification closes the feedback loop and encourages future contributions by demonstrating that submissions are acted on.
>
> **Acceptance Criteria:** When a reviewer accepts a submission, the submitter receives a notification within the configured delivery window. When a reviewer rejects a submission, the notification includes the rejection reason. Notification channel is set via environment variable and takes effect without code changes.

---

> **REQ-204** | Priority: MUST
>
> **Description:** The system MUST track the age of each submission in the approval queue and surface a visual indicator in the Admin Console when a submission approaches or exceeds the configured review SLA. Submissions exceeding the SLA MUST trigger an alert to the reviewer group.
>
> **Rationale:** Without SLA tracking, submissions can stagnate in the queue indefinitely. Users who submit documents and receive no response lose trust in the contribution system.
>
> **Acceptance Criteria:** Submissions older than the configured warning threshold display a visual warning badge in the queue. Submissions older than the SLA threshold display a critical badge. At the SLA threshold, an alert is dispatched to the reviewer group via the configured notification channel. The warning threshold and SLA are configurable.

---

> **REQ-205** | Priority: SHOULD
>
> **Description:** The system SHOULD support category-based routing of submissions to reviewer subgroups. Each document category SHOULD be configurable to route to a specific reviewer group, so submissions reach reviewers with the relevant domain expertise.
>
> **Rationale:** A single shared queue assigns all submissions to all reviewers regardless of domain knowledge. Category routing reduces the cognitive load on reviewers by ensuring they only see submissions in their area.
>
> **Acceptance Criteria:** A submission with category "Legal" routes to the "Legal Reviewers" group if that mapping is configured. A submission with an unmapped category routes to the default reviewer group. Category-to-group mappings are configurable without code changes.

---

> **REQ-206** | Priority: SHOULD
>
> **Description:** The system SHOULD support auto-approval rules that allow submissions from configured trusted sources (e.g., specific authenticated principals, specific source URL domains) to bypass manual review and proceed directly to ingestion.
>
> **Rationale:** High-volume, low-risk document sources (e.g., an internal document management system with its own governance) should not require manual review for every document. Auto-approval reduces operational load for trusted sources without eliminating review for untrusted ones.
>
> **Acceptance Criteria:** A submission from a principal on the auto-approval list proceeds to ingestion without appearing in the reviewer queue. The auto-approval action is logged with the same fields as a manual approval. Auto-approval rules are configurable via the admin settings without code changes. Submissions not matching any rule go through normal review.

---

## 5. Central Ingestion Integration (REQ-3xx)

> **REQ-301** | Priority: MUST
>
> **Description:** An accepted submission MUST trigger an ingestion pipeline run targeting the central vector store using the same pipeline as standard scheduled ingestion runs. The run MUST be traceable back to the submission via the tracking reference.
>
> **Rationale:** Using the same ingestion pipeline ensures consistent chunking, embedding, and storage behavior for contributed documents. A separate pipeline would create maintenance burden and behavioral divergence.
>
> **Acceptance Criteria:** After a reviewer accepts a submission, an ingestion run is initiated within the configured dispatch window. The run is tagged with the submission tracking reference. The resulting chunks in the central index are queryable by all users. The ingestion run appears in the ingestion history with the tracking reference visible.

---

> **REQ-302** | Priority: MUST
>
> **Description:** Before beginning ingestion, the system MUST compute a content hash of the submitted document and check for an existing entry in the central index with the same hash. If a match exists, the system MUST update the existing entry (re-chunk with current settings) rather than creating a duplicate entry.
>
> **Rationale:** Naive re-ingestion of a document that is already indexed creates duplicate chunks, which degrades retrieval quality by inflating the scores of the duplicated content.
>
> **Acceptance Criteria:** Ingesting a document whose content hash matches an existing indexed document updates the existing chunks rather than creating new ones. The chunk count before and after is not inflated. Ingesting a document with no matching hash creates a new entry. The dedup check does not block ingestion of documents with the same filename but different content.

---

> **REQ-303** | Priority: MUST
>
> **Description:** The system MUST store a provenance record alongside the ingested document metadata. The provenance record MUST include: submission tracking reference, submitter identity, submission timestamp, reviewer identity, review decision timestamp, and review reason.
>
> **Rationale:** Provenance records enable audits of which documents were contributed by whom and approved by whom. They also enable operators to trace a retrieved chunk back to its submission origin when evaluating document quality.
>
> **Acceptance Criteria:** Each centrally contributed document has a provenance record retrievable by tracking reference. The record contains all six required fields. The provenance record is stored durably alongside the document metadata in the index.

---

> **REQ-304** | Priority: MUST
>
> **Description:** The system MUST notify the submitter when ingestion of their accepted document completes. The notification MUST include the number of chunks indexed and the document's availability status (available for retrieval).
>
> **Rationale:** Without a completion notification, submitters do not know when their contribution takes effect. The chunk count gives a concrete signal of whether the document was processed as expected.
>
> **Acceptance Criteria:** When an ingestion run triggered by an accepted submission completes, the submitter receives a notification with the chunk count. If ingestion fails, the submitter receives an error notification with a summary of the failure. Notification is delivered via the configured channel.

---

> **REQ-305** | Priority: SHOULD
>
> **Description:** The system SHOULD support configurable ingestion priority for contribution-triggered runs. Contribution runs SHOULD default to a lower priority than scheduled maintenance ingestion to prevent user submissions from starving planned pipeline operations.
>
> **Rationale:** A burst of accepted contributions triggering simultaneous ingestion runs could delay scheduled re-indexing operations. Priority configuration allows operators to tune the trade-off between contribution latency and operational stability.
>
> **Acceptance Criteria:** Contribution-triggered ingestion runs are queued at the configured priority level. When the pipeline is under load, lower-priority runs yield to higher-priority ones. Priority is configurable via environment variable.

---

## 6. Local Contribution & Session Index (REQ-4xx)

> **REQ-401** | Priority: MUST
>
> **Description:** The system MUST accept file uploads from authenticated users for storage in a personal session-scoped index. File uploads MUST be accepted via a file picker or drag-and-drop zone in both web consoles, and via a file path argument in the CLI.
>
> **Rationale:** Users frequently need to query against personal working documents that are not appropriate for the shared organizational index. All three interfaces must support this to maintain CLI/UI parity.
>
> **Acceptance Criteria:** A file uploaded via the User Console appears in the user's personal document list and is queryable in the same session. The same file uploaded via the CLI produces the same result. Both consoles accept drag-and-drop. The CLI accepts `--local-file <path>` or equivalent.

---

> **REQ-402** | Priority: MUST
>
> **Description:** Personal index partitions MUST be isolated at the vector store level. A retrieval query from User A MUST NOT access chunks from User B's personal partition. The isolation boundary MUST be enforced by the storage layer, not only by application-layer filtering.
>
> **Rationale:** Application-layer filtering is vulnerable to bugs, misconfiguration, or direct API calls that bypass filtering logic. Storage-layer isolation (namespace, collection, or tenant) provides a hard boundary that cannot be bypassed without storage-level credentials.
>
> **Acceptance Criteria:** Given two users each with a personal document uploaded, a query from User A returns citations only from the central index and User A's personal partition — never User B's. This holds even when User A crafts a direct API query that omits application-layer filters. Verified by penetration test or integration test asserting cross-user isolation.

---

> **REQ-403** | Priority: MUST
>
> **Description:** Retrieved chunks sourced from a user's personal index MUST be labeled distinctly in query results across all three interfaces. The label MUST clearly differentiate personal documents from central index documents.
>
> **Rationale:** Users must be able to distinguish between authoritative organizational knowledge (from the central index) and their own personal uploads in citation results, since personal documents may be drafts or unverified content.
>
> **Acceptance Criteria:** In the User Console, citation cards for personal documents display a "Personal" badge or equivalent label. In the Admin Console, the source chunk metadata includes a `source_type: personal` field. In the CLI, personal document citations include a `[personal]` label. Central index citations have no such label.

---

> **REQ-404** | Priority: MUST
>
> **Description:** Personal index partitions MUST support configurable lifetime policies. The system MUST support at minimum two lifetime options: **session-scoped** (partition purged when the user's session ends or the browser tab closes) and **duration-based** (partition retained for a configured number of hours after last activity). The active policy MUST be configurable per deployment.
>
> **Rationale:** Session-scoped lifetime minimizes storage accumulation but forces users to re-upload if they return to the system later. Duration-based lifetime accommodates multi-session workflows at the cost of longer-lived storage.
>
> **Acceptance Criteria:** With session-scoped policy, a user's personal documents are no longer queryable after their session expires. With a 24-hour duration policy, personal documents remain queryable up to 24 hours after last activity. Policy is set via environment variable. Expired partitions are purged by the background cleanup process.

---

> **REQ-405** | Priority: MUST
>
> **Description:** The system MUST allow users to remove individual personal documents or clear their entire personal index partition at any time via all three interfaces. Removal MUST take effect immediately for subsequent queries.
>
> **Rationale:** Users must be able to retract a personal document that was uploaded in error or is no longer relevant. Immediate effect prevents the document from appearing in subsequent query results.
>
> **Acceptance Criteria:** A user removes a personal document via the console sidebar or CLI command. The next query in the same session does not retrieve chunks from the removed document. Clearing the full partition removes all personal documents. Both individual removal and full-clear are available in all three interfaces.

---

> **REQ-406** | Priority: MUST
>
> **Description:** The system MUST enforce configurable file type and file size limits for personal uploads. Uploads exceeding the configured size limit or of a disallowed type MUST be rejected with a descriptive error before storage.
>
> **Rationale:** Personal upload endpoints exposed to all authenticated users require limits to prevent storage exhaustion and pipeline overload from large or unexpected file types.
>
> **Acceptance Criteria:** Uploading a file larger than the configured personal upload size limit returns an error before the file is stored. Uploading a disallowed file type returns an error listing the allowed types. Both limits are independently configurable via environment variables.

---

> **REQ-407** | Priority: MUST
>
> **Description:** The system MUST run a background cleanup process that purges personal index partitions whose lifetime has expired. The cleanup process MUST run on a configurable schedule and MUST log each partition it purges with the user identity (pseudonymized per policy) and document count.
>
> **Rationale:** Without active cleanup, expired personal partitions accumulate indefinitely, consuming vector store capacity and potentially leaking stale data across sessions.
>
> **Acceptance Criteria:** After the configured partition lifetime, personal chunks are no longer retrievable by the owning user. The cleanup log records each purged partition. The cleanup schedule is configurable without code changes. Cleanup does not affect the central index.

---

## 7. Governance & Audit (REQ-5xx)

> **REQ-501** | Priority: MUST
>
> **Description:** Central Contribution submission endpoints MUST be restricted to authenticated principals. The system MUST enforce the configured submission eligibility policy (all authenticated users, specific roles, or specific principals) at the API layer.
>
> **Rationale:** Unauthenticated or unauthorized submissions bypass the governance model and create an uncontrolled ingestion path into the shared organizational index.
>
> **Acceptance Criteria:** An unauthenticated request to the submission endpoint returns HTTP 401. A request from a principal not meeting the eligibility policy returns HTTP 403. Eligibility policy is configurable without code changes. Frontend UI restrictions do not substitute for API-layer enforcement.

---

> **REQ-502** | Priority: MUST
>
> **Description:** Approval queue access and review actions (accept, reject, defer) MUST be restricted to principals with admin role, enforced at the API layer. Non-admin principals MUST NOT be able to take review actions regardless of UI state.
>
> **Rationale:** The approval queue is the governance gate for the central index. If non-admin principals can approve submissions — even by bypassing the UI — the governance model is broken.
>
> **Acceptance Criteria:** A non-admin principal who calls the review action endpoint directly receives HTTP 403. The reviewer queue endpoint returns HTTP 403 for non-admin principals. Admin role is verified against the auth context on every request, not cached.

---

> **REQ-503** | Priority: MUST
>
> **Description:** The system MUST create an immutable audit log entry for every state change in the Central Contribution lifecycle: submission received, validation failure, review decision (accept/reject/defer), ingestion started, ingestion completed, and ingestion failed. Each entry MUST record: event type, tracking reference, actor identity, timestamp, and event-specific details (e.g., rejection reason).
>
> **Rationale:** Audit logs are required for governance accountability and for post-incident investigation. Immutability prevents retroactive modification of the decision record.
>
> **Acceptance Criteria:** Every lifecycle event produces a log entry with all required fields. Log entries cannot be deleted via the application API. The audit log is queryable by tracking reference. Log entries are written before the action they record takes effect (write-ahead).

---

> **REQ-504** | Priority: MUST
>
> **Description:** The system MUST expose queue health metrics for operational monitoring: current queue depth (total pending submissions), submissions by age bucket (e.g., 0–1 day, 1–3 days, >SLA), and review throughput (decisions per day). These metrics MUST be accessible via the admin health endpoint.
>
> **Rationale:** Without queue metrics, the operations team cannot detect stagnation until individual submitters escalate. Proactive monitoring enables intervention before the SLA is breached.
>
> **Acceptance Criteria:** The health endpoint includes contribution queue depth and age distribution. Metrics update in real time as submissions are added or reviewed. The SLA threshold used in age buckets is the configured review SLA.

---

> **REQ-505** | Priority: SHOULD
>
> **Description:** The system SHOULD provide a mechanism for submitters to withdraw a pending submission before a review decision is made. Withdrawal MUST be logged in the audit trail with the submitter's identity and timestamp.
>
> **Rationale:** A submitter may realize their document was submitted in error, is already indexed, or is no longer relevant. Allowing withdrawal reduces reviewer time spent on stale submissions.
>
> **Acceptance Criteria:** A submitter can withdraw their own pending submission via all three interfaces. Withdrawn submissions are removed from the reviewer queue. The withdrawal is recorded in the audit log. Submissions in accepted or rejected state cannot be withdrawn.

---

## 8. Non-Functional Requirements (REQ-9xx)

> **REQ-901** | Priority: MUST
>
> **Description:** The submission endpoint MUST respond within 2 seconds for valid payloads under normal load. The personal upload endpoint MUST respond within 5 seconds for files up to the configured size limit under normal load. These SLOs exclude ingestion processing time, which is asynchronous.
>
> **Rationale:** Slow submission responses create uncertainty about whether the submission was received, leading to duplicate submissions.
>
> **Acceptance Criteria:** Under a load of 10 concurrent submissions, the submission endpoint p95 response time is ≤2 seconds. The personal upload endpoint p95 response time is ≤5 seconds for files at the size limit. Ingestion runs execute asynchronously and do not block the submission response.

---

> **REQ-902** | Priority: MUST
>
> **Description:** If the ingestion pipeline is temporarily unavailable when a submission is approved, the system MUST queue the ingestion trigger and retry it when the pipeline becomes available. The system MUST NOT lose an approved submission due to transient pipeline unavailability.
>
> **Rationale:** Ingestion pipeline outages are expected maintenance events. Losing an approved submission because the pipeline happened to be down at approval time is unacceptable — the reviewer's work and the submitter's contribution would be silently lost.
>
> **Acceptance Criteria:** An approved submission while the ingestion pipeline is unavailable is stored in a durable pending-ingestion queue. When the pipeline becomes available, the queued submission is processed within the configured retry window. The submitter is notified when ingestion completes, not when the submission is accepted.

---

> **REQ-903** | Priority: MUST
>
> **Description:** All configurable parameters for both Central and Local Contribution MUST be externalized to environment variables with documented defaults.
>
> **Rationale:** Hardcoded parameters prevent deployment-specific tuning and force code changes for operational adjustments.
>
> **Acceptance Criteria:** The following parameters are configurable via environment variable: maximum file size (central), maximum file size (local), allowed file types (central), allowed file types (local), partition lifetime policy, partition lifetime duration, review SLA threshold, SLA warning threshold, ingestion priority for contribution runs, notification channel, auto-approval rules. Each has a documented default. Changes take effect on server restart.

---

> **REQ-904** | Priority: SHOULD
>
> **Description:** The system SHOULD provide an admin view showing the personal index storage usage aggregated by partition (pseudonymized), including total chunk count and storage size, to enable operators to monitor and manage personal index growth.
>
> **Rationale:** Without visibility into personal index growth, operators cannot anticipate storage capacity issues or identify abnormal usage patterns.
>
> **Acceptance Criteria:** The Admin Console health or admin panel includes a personal index storage summary. The summary shows total partitions, total chunks, and aggregate storage used. Individual partition data is shown with a pseudonymous identifier, not the user's real identity.

---

## 9. Interface Contracts

### Submission API

| Field | Value |
|-------|-------|
| Protocol | HTTP REST |
| Path | `POST /contributions/submit` |
| Authentication | User-level auth (API key or bearer token) |

**Request Schema:**
```json
{
  "source_type": "file | url",
  "source_url": "string | null — required if source_type is url",
  "description": "string — required, submitter's description of the document",
  "category": "string — required, from configured category list",
  "file": "binary — required if source_type is file"
}
```

**Response Schema:**
```json
{
  "ok": true,
  "request_id": "string",
  "data": {
    "tracking_reference": "string — unique ID for this submission",
    "status": "pending",
    "duplicate_warning": "boolean — true if content hash matches existing document"
  }
}
```

### Personal Upload API

| Field | Value |
|-------|-------|
| Protocol | HTTP REST (multipart) |
| Path | `POST /personal/upload` |
| Authentication | User-level auth |

**Response Schema:**
```json
{
  "ok": true,
  "request_id": "string",
  "data": {
    "document_id": "string — ID within the personal partition",
    "filename": "string",
    "chunk_count": "integer — chunks indexed",
    "partition_expires_at": "string | null — ISO 8601 timestamp if duration-based policy"
  }
}
```

---

## 10. State & Lifecycle

### Central Contribution States

| State | Description | Valid Next States |
|-------|-------------|-------------------|
| `pending` | Submission received and validated, awaiting reviewer action | `accepted`, `rejected`, `deferred`, `withdrawn` |
| `deferred` | Reviewer has noted the submission but not made a final decision | `accepted`, `rejected`, `withdrawn` |
| `accepted` | Reviewer approved; ingestion trigger dispatched | `ingesting`, `ingestion_failed` |
| `rejected` | Reviewer declined; submitter notified with reason | (terminal) |
| `withdrawn` | Submitter cancelled before review decision | (terminal) |
| `ingesting` | Ingestion pipeline run in progress | `ingested`, `ingestion_failed` |
| `ingested` | Document successfully indexed; submitter notified | (terminal) |
| `ingestion_failed` | Pipeline run failed; submitter notified | `ingesting` (via retry) |

---

## 11. System-Level Acceptance Criteria

| Criterion | Threshold | Related Requirements |
|-----------|-----------|---------------------|
| End-to-end Central Contribution | Submit → approve → ingest → query in <15 minutes under normal load | REQ-101, REQ-301, REQ-304 |
| Personal index isolation | Cross-user retrieval test returns zero personal chunks from other users | REQ-402 |
| Personal document citation labeling | 100% of personal chunk citations labeled distinctly in all three interfaces | REQ-403 |
| Partition purge correctness | Expired partitions purged within 1 cleanup cycle; central index unaffected | REQ-407 |
| Audit log completeness | Every lifecycle event has a corresponding log entry with all required fields | REQ-503 |
| RBAC enforcement | Non-admin direct API calls to review endpoints return HTTP 403 | REQ-502 |
| Ingestion queue durability | Approved submission with pipeline down processes after pipeline restores | REQ-902 |
| Configuration externalization | All parameters listed in REQ-903 configurable via env var | REQ-903 |

---

## 12. Requirements Traceability Matrix

| REQ ID | Section | Priority | Component |
|--------|---------|----------|-----------|
| REQ-101 | 3 | MUST | Submission & Validation |
| REQ-102 | 3 | MUST | Submission & Validation |
| REQ-103 | 3 | MUST | Submission & Validation |
| REQ-104 | 3 | MUST | Submission & Validation |
| REQ-105 | 3 | MUST | Submission & Validation |
| REQ-106 | 3 | SHOULD | Submission & Validation |
| REQ-201 | 4 | MUST | Central Approval Workflow |
| REQ-202 | 4 | MUST | Central Approval Workflow |
| REQ-203 | 4 | MUST | Central Approval Workflow |
| REQ-204 | 4 | MUST | Central Approval Workflow |
| REQ-205 | 4 | SHOULD | Central Approval Workflow |
| REQ-206 | 4 | SHOULD | Central Approval Workflow |
| REQ-301 | 5 | MUST | Central Ingestion Integration |
| REQ-302 | 5 | MUST | Central Ingestion Integration |
| REQ-303 | 5 | MUST | Central Ingestion Integration |
| REQ-304 | 5 | MUST | Central Ingestion Integration |
| REQ-305 | 5 | SHOULD | Central Ingestion Integration |
| REQ-401 | 6 | MUST | Local Contribution & Session Index |
| REQ-402 | 6 | MUST | Local Contribution & Session Index |
| REQ-403 | 6 | MUST | Local Contribution & Session Index |
| REQ-404 | 6 | MUST | Local Contribution & Session Index |
| REQ-405 | 6 | MUST | Local Contribution & Session Index |
| REQ-406 | 6 | MUST | Local Contribution & Session Index |
| REQ-407 | 6 | MUST | Local Contribution & Session Index |
| REQ-501 | 7 | MUST | Governance & Audit |
| REQ-502 | 7 | MUST | Governance & Audit |
| REQ-503 | 7 | MUST | Governance & Audit |
| REQ-504 | 7 | MUST | Governance & Audit |
| REQ-505 | 7 | SHOULD | Governance & Audit |
| REQ-901 | 8 | MUST | Non-Functional |
| REQ-902 | 8 | MUST | Non-Functional |
| REQ-903 | 8 | MUST | Non-Functional |
| REQ-904 | 8 | SHOULD | Non-Functional |

**Total Requirements: 33**
- MUST: 27
- SHOULD: 6
- MAY: 0

---

## Appendix A. Glossary

| Term | Definition |
|------|-----------|
| Content Hash | A SHA-256 or equivalent deterministic hash of a document's byte content, used for duplicate detection |
| Idempotent Ingestion | The property that ingesting a document that is already indexed updates the existing entry rather than creating duplicates |
| Partition | A logically isolated segment of the vector store scoped to a single user's personal index |
| Provenance | The traceable chain of origin for an indexed document: who submitted it, who approved it, and when |
| Storage-Layer Isolation | Enforcement of data boundaries at the vector store level (e.g., namespace, collection, tenant) rather than at the application query layer |

## Appendix B. Document References

| Document | Purpose |
|----------|---------|
| `INGESTION_PIPELINE_SPEC.md` | Defines the ingestion pipeline reused for contribution-triggered runs |
| `WEB_CONSOLE_SPEC.md` | Defines web console UI requirements for submission form and personal document list |
| `CLI_SPEC.md` | Defines CLI requirements for submission commands and personal upload |
| `PLATFORM_SERVICES_SPEC.md` | Defines auth, RBAC, and API key management used for access control |
| `FEEDBACK_LOOP_SPEC.md` | Related feature: captures user ratings and drives tuning recommendations |

## Appendix C. Open Questions

| # | Question | Context | Status |
|---|----------|---------|--------|
| OQ-1 | What is the target review SLA for Central Contributions? | This drives the SLA alerting thresholds in REQ-204. A common starting point is 5 business days. | Requires stakeholder input |
| OQ-2 | Should the submission eligibility policy default to all authenticated users or a specific role? | Opening to all users maximizes participation; restricting to a role enables a phased rollout. | Requires stakeholder input |
| OQ-3 | What notification channels are available in the deployment environment? | REQ-203 and REQ-204 require a configurable notification channel. Available options depend on the organization's tooling. | Requires infrastructure input |
| OQ-4 | What vector store partitioning mechanism is available for personal index isolation? | REQ-402 requires storage-layer isolation. The mechanism (namespace, collection, tenant) depends on the deployed vector store. | Requires infrastructure input |
