# User Contribution — Specification Summary

**Companion spec:** `USER_CONTRIBUTION_SPEC.md` v1.0
**Purpose:** Concise digest of the User Contribution spec — scope, structure, requirement domains, and key decisions. Not a replacement for the spec.
**See also:** `WEB_CONSOLE_SPEC.md`, `CLI_SPEC.md`, `INGESTION_PIPELINE_SPEC.md`, `FEEDBACK_LOOP_SPEC.md`

---

## 1) Generic System Overview

### Purpose

The User Contribution system solves a structural bottleneck in knowledge base maintenance: when subject-matter experts encounter gaps in the platform's knowledge, they cannot act on them directly. The system provides two parallel contribution paths — one for enriching the shared organizational index through a governed approval workflow, and one for uploading personal working documents that are relevant only to a user's current session. Without this system, knowledge gaps require operator mediation to close, and personal document workflows exist entirely outside the platform, fragmenting the user experience.

### How It Works

The system operates two independent contribution flows triggered by the same set of user interfaces.

In the **central contribution flow**, a user submits a document — either by uploading a file or providing a URL — along with a description and a category. The system validates the submission (checking reachability, file type, size, and non-emptiness), assigns a unique tracking reference, and places the submission in a pending queue. A visual indicator in the administration surface alerts authorized reviewers to pending submissions. Reviewers can accept, reject, or defer each submission and must provide a typed reason for any action. Accepted submissions trigger a run of the same ingestion pipeline used for scheduled indexing; the resulting document becomes available to all users in the shared index. A provenance record is stored alongside the indexed content, capturing the full chain of custody from submitter to reviewer to ingestion. The submitter is notified at each material state transition. An auto-approval path allows trusted submission sources to bypass manual review and proceed directly to ingestion.

In the **local contribution flow**, a user uploads a file directly to a personal partition of the vector store. The file is validated, ingested, and becomes immediately queryable in the user's active session. Personal documents appear with a distinct label in query results across all interfaces, differentiating them from authoritative central index content. Partitions are subject to a configurable lifetime policy — either session-scoped (cleared when the session ends) or duration-based (retained for a configurable period after last activity). A background cleanup process purges expired partitions on a scheduled basis. Users can remove individual documents or clear their entire partition at any time.

### Tunable Knobs

Operators can configure: the maximum file size for central submissions and personal uploads (independently); the allowed file types for each path; the lifetime policy for personal partitions and, for duration-based policies, the inactivity window before expiry; the review SLA threshold and the earlier warning threshold that triggers visual alerts; the priority level at which contribution-triggered ingestion runs are queued relative to other pipeline work; the notification delivery channel for submission status events; and the auto-approval rules that define which submission sources bypass manual review. All knobs are externalized to environment variables with documented defaults and take effect on server restart.

### Design Rationale

The central contribution path is intentionally structured as a human-gated workflow rather than an automated accept-all pipeline. Unreviewed content entering the shared organizational index degrades retrieval quality and creates governance accountability gaps. The personal contribution path requires no governance gate because its scope is intentionally bounded — content is invisible to other users and is discarded automatically.

Personal index isolation is enforced at the storage layer rather than the application layer because application-layer filtering can be bypassed by direct API calls or misconfiguration. The shared ingestion pipeline is reused for approved contributions to prevent behavioral divergence between scheduled and user-triggered indexing runs. Duplicate detection using content hashing prevents the retrieval quality degradation caused by duplicate chunks in the index.

### Boundary Semantics

**Central — entry:** A user submits a contribution request via the web console form or CLI command. **Central — exit:** The document is indexed in the central vector store and the submitter is notified of completion, OR the submission is rejected and the submitter receives the rejection reason with reviewer rationale.

**Local — entry:** A user uploads a file via the web console file picker, drag-and-drop zone, or CLI file path argument. **Local — exit:** The document is available for retrieval in the user's active session and appears in their personal document list.

The system does not own the ingestion pipeline internals, the notification delivery infrastructure, the authentication and role system, or the web console and CLI surfaces — those are defined in companion specifications and consumed as dependencies.

---

## 2) Header

| Field | Value |
|-------|-------|
| Companion spec | `USER_CONTRIBUTION_SPEC.md` |
| Spec version | 1.0 (Draft, 2026-03-18) |
| Domain | User Contribution |
| Requirement count | 33 total (27 MUST, 6 SHOULD, 0 MAY) |

---

## 3) Scope and Boundaries

### Entry Points

- **Central:** User submits a document contribution request via the web console form or CLI command
- **Local:** User uploads a document to their personal session index via the web console file picker or CLI file path argument

### Exit Points

- **Central:** Document indexed in the central vector store and submitter notified of completion, OR submission rejected with reason
- **Local:** Document available for retrieval in the user's active session and visible in their personal document list

### In Scope

- Submission validation (file type, size, URL reachability, non-empty content)
- Reviewer approval queue (pending, defer, accept, reject workflows)
- Ingestion triggering for approved submissions
- Provenance record storage for centrally contributed documents
- Personal index partition isolation, lifecycle management, and cleanup
- Governance: RBAC enforcement, audit logging, queue health metrics
- Auto-approval rules for trusted submission sources
- Submission status tracking via tracking reference
- Notification delivery for submission lifecycle events
- CLI/UI parity across all three surfaces (User Console, Admin Console, CLI)

### Out of Scope

- Ingestion pipeline internals (chunking, embedding, storage) — see `INGESTION_PIPELINE_SPEC.md`
- Web console UI layout and component design — see `WEB_CONSOLE_SPEC.md`
- CLI command system and REPL behavior — see `CLI_SPEC.md`
- Feedback and quality rating of query results — see `FEEDBACK_LOOP_SPEC.md`
- Bulk import tools for initial corpus loading
- Document versioning and change tracking within the central index

---

## 4) Architecture / Pipeline Overview

```
User / Operator (Browser or CLI)
         |
         +------------------------------+
         |                              |
         v                              v
[1] CENTRAL CONTRIBUTION        [2] LOCAL CONTRIBUTION
    Submission form                 File upload / path
    Status tracking                 Personal doc list
    Notification                    Remove / clear
         |                              |
         v                              v
         +------------------------------+
                       |
                       v
           [3] CONTRIBUTION API
               POST /contributions/submit
               GET  /contributions/status/:ref
               POST /contributions/review (admin)
               POST /personal/upload
               GET  /personal/documents
               DELETE /personal/documents/:id
                       |
           +-----------+-----------+
           |                       |
           v                       v
[4] APPROVAL QUEUE (admin)   [5] INGESTION PIPELINE
    Pending / Review              Central index (shared)
    SLA tracking                  Personal index (per-user)
    Notify submitter              Same pipeline as scheduled
```

**Data flows:**
- Central submit: Validate → assign tracking ref → enqueue → reviewer action → (if accepted) trigger ingestion → notify submitter
- Local upload: Validate → ingest into personal partition → available immediately in session
- Partition cleanup: Background process purges expired personal partitions on configured schedule

---

## 5) Requirement Framework

Requirements use RFC 2119 priority language: **MUST** (non-conformant without), **SHOULD** (recommended, omittable with justification), **MAY** (optional).

Each requirement carries: description, rationale, and acceptance criteria.

| Section | ID Range | Component |
|---------|----------|-----------|
| 3 | REQ-1xx | Submission & Validation |
| 4 | REQ-2xx | Central Approval Workflow |
| 5 | REQ-3xx | Central Ingestion Integration |
| 6 | REQ-4xx | Local Contribution & Session Index |
| 7 | REQ-5xx | Governance & Audit |
| 8 | REQ-9xx | Non-Functional Requirements |

---

## 6) Functional Requirement Domains

**REQ-1xx — Submission & Validation (6 requirements)**
Covers multi-surface submission acceptance (all three interfaces routing to the same endpoint), required payload fields (description, category, auth-derived identity), document validation (URL reachability, file type allowlist, non-empty content, size limits), tracking reference assignment and status queryability, and content hash dedup warning at submission time.

**REQ-2xx — Central Approval Workflow (6 requirements)**
Covers the reviewer queue (display, ordering, field visibility, real-time updates), the three reviewer actions (accept, reject, defer — each requiring a typed reason), submitter notification on decision, SLA tracking with visual indicators and alert dispatch, optional category-based routing to reviewer subgroups, and optional auto-approval rules for trusted sources.

**REQ-3xx — Central Ingestion Integration (5 requirements)**
Covers triggering the shared ingestion pipeline for accepted submissions (with traceability to the tracking reference), content hash dedup at ingestion time (update-not-duplicate behavior), provenance record storage (six required fields), submitter notification on ingestion completion or failure, and optional configurable ingestion priority for contribution-triggered runs.

**REQ-4xx — Local Contribution & Session Index (7 requirements)**
Covers multi-surface file upload acceptance, storage-layer partition isolation (not application-layer only), distinct citation labeling for personal documents in all three interfaces, configurable partition lifetime policies (session-scoped and duration-based), individual document removal and full partition clear, file type and size limits for personal uploads, and background partition cleanup with audit logging.

**REQ-5xx — Governance & Audit (5 requirements)**
Covers API-layer enforcement of submission eligibility policy, API-layer enforcement of reviewer RBAC (admin role required, verified per-request), immutable write-ahead audit log for every lifecycle state change, queue health metrics exposed via the admin health endpoint, and optional submitter-initiated withdrawal of pending submissions.

**REQ-9xx — Non-Functional Requirements (4 requirements)**
Covers submission and personal upload endpoint response time SLOs (both asynchronous from ingestion), durable queuing of approved submissions during pipeline unavailability with automatic retry, full externalization of all configurable parameters to environment variables, and an optional admin view of personal index storage usage aggregated by pseudonymized partition.

---

## 7) Non-Functional and Security Themes

**Performance:** Submission and upload endpoints have defined response time targets under concurrent load. Ingestion is asynchronous and does not block submission responses.

**Durability:** Approved submissions that cannot be immediately ingested are queued durably and retried when the pipeline recovers. No approved submission is silently lost due to transient unavailability.

**Configuration externalization:** Every tunable behavioral parameter — file size limits, file type allowlists, partition lifetime, SLA thresholds, ingestion priority, notification channel, auto-approval rules — is controlled by environment variable with a documented default.

**Access control:** Submission eligibility, reviewer authorization, and personal index scoping are all enforced at the API layer. UI-layer restrictions are not the security boundary.

**Audit integrity:** The audit log is immutable via the application API and uses write-ahead ordering. Every lifecycle state change produces a log entry before the action takes effect.

**Personal data handling:** Personal index storage metrics exposed to admins use pseudonymized partition identifiers rather than real user identities.

**Isolation:** Personal index partitions are isolated at the storage layer (namespace, collection, or tenant mechanism) to prevent cross-user data access even under application bugs or direct API calls.

---

## 8) Design Principles

| Principle | Intent |
|-----------|--------|
| **Low-friction submission** | Every additional field or step in the central contribution workflow reduces participation. Minimize required inputs. |
| **Hard isolation for personal indexes** | Storage-layer isolation cannot be bypassed by application bugs or misconfiguration; application-layer isolation can. |
| **Idempotent ingestion** | Re-ingesting an already-indexed document must update the existing entry, not create duplicates that degrade retrieval quality. |
| **API-layer enforcement** | All access control must be enforced at the API, not only in the UI. The UI is a convenience, not a security boundary. |
| **Graceful degradation** | Submission capture and personal index operations must continue when the ingestion pipeline is temporarily unavailable. Submissions queue rather than fail. |

---

## 9) Key Decisions

- **Human-gated central index:** All submissions to the shared organizational index require reviewer approval (with an optional auto-approval escape hatch for trusted sources). Fully automated accept-all ingestion is not supported.
- **Shared ingestion pipeline reuse:** Approved contributions trigger the same ingestion pipeline used for scheduled runs, ensuring behavioral consistency and avoiding maintenance divergence.
- **Storage-layer personal index isolation:** The spec mandates isolation at the vector store level (namespace, collection, or tenant), not application-layer filtering, because application-layer filters can be bypassed.
- **Dual lifetime policies:** Personal partitions can be session-scoped or duration-based, giving operators a trade-off between storage efficiency and user convenience across multi-session workflows.
- **Write-ahead immutable audit log:** Every state change is logged before it takes effect, and log entries are not deletable via the application API.
- **Dedup by content hash (not filename):** Duplicate detection at both submission time and ingestion time uses a hash of the document's byte content. Same filename with different content is not treated as a duplicate.
- **Typed reason required for all reviewer actions:** Accept, reject, and defer all require a typed reason, creating an audit trail and forcing reviewers to articulate decisions.

---

## 10) Acceptance and Evaluation

The spec defines eight system-level acceptance criteria covering:

- End-to-end central contribution latency (submit → approve → ingest → queryable) under normal load
- Cross-user personal index isolation verified by integration or penetration test
- Personal document citation labeling coverage across all three interfaces
- Partition purge correctness (expired partitions cleared within one cleanup cycle without affecting the central index)
- Audit log completeness (every lifecycle event logged with all required fields)
- RBAC enforcement (non-admin direct API calls to review endpoints return the expected error code)
- Ingestion queue durability (approved submission with pipeline down processes after recovery)
- Configuration externalization (all parameters in the NFR section configurable via environment variable)

The spec does not define an evaluation or feedback framework beyond these acceptance criteria. No open evaluation questions are deferred — evaluation scope is bounded to the acceptance criteria table.

The spec includes three open questions deferred for stakeholder input: the target review SLA, the default submission eligibility policy, and the available notification channels and vector store partitioning mechanism.

---

## 11) External Dependencies

| Dependency | Type | Purpose |
|------------|------|---------|
| Ingestion pipeline | Required | Reused for all contribution-triggered central index runs |
| Auth / RBAC system | Required | Establishes submitter identity, reviewer admin role; enforced per-request |
| Vector store (with partition support) | Required | Central index storage; personal index isolation via namespace/collection/tenant |
| Notification service | Required | Delivers submission lifecycle notifications (in-app, email, or Slack) |
| Web console (User + Admin surfaces) | Downstream contract | Renders submission form, reviewer queue, personal document list |
| CLI | Downstream contract | Exposes submit and personal upload commands |

**Assumption dependencies (may force scope change if violated):**
- Vector store must support namespaced or tenant-scoped partitions for personal index isolation
- Both console surfaces and CLI share the same backend API endpoints
- File content is available server-side after upload for hashing and validation
- Notification delivery is handled by an existing external service

---

## 12) Companion Documents

This summary digests `USER_CONTRIBUTION_SPEC.md` v1.0. It is designed to be readable without the full spec but is not a substitute for it — individual requirement descriptions, acceptance criteria values, and the full traceability matrix live in the spec.

**Companion specifications consumed by this feature:**

| Document | Relationship |
|----------|-------------|
| `INGESTION_PIPELINE_SPEC.md` | Defines the pipeline reused for contribution-triggered ingestion runs |
| `WEB_CONSOLE_SPEC.md` | Defines web console UI requirements for the submission form and personal document list |
| `CLI_SPEC.md` | Defines CLI requirements for submission and personal upload commands |
| `PLATFORM_SERVICES_SPEC.md` | Defines auth, RBAC, and API key management consumed for access control |
| `FEEDBACK_LOOP_SPEC.md` | Adjacent feature: user quality ratings; out of scope for this spec |

The spec also includes Appendix A (Glossary), Appendix B (Document References), and Appendix C (Open Questions with three items requiring stakeholder and infrastructure input).

---

## 13) Sync Status

| Field | Value |
|-------|-------|
| Spec version | 1.0 (Draft) |
| Spec date | 2026-03-18 |
| Summary written | 2026-04-10 |
| Aligned to | `USER_CONTRIBUTION_SPEC.md` v1.0 — full spec read, all sections covered |
