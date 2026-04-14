> **Document type:** Specification Summary (Layer 2)
> **Companion spec:** DOCUMENT_MANAGEMENT_SPEC.md (Layer 3)
> **Downstream:** DOCUMENT_MANAGEMENT_DESIGN.md

# Document & Collection Management API — Specification Summary

---

## 1) Generic System Overview

### Purpose

The document and collection management subsystem fills an observability gap in the RAG platform: while ingestion pipelines can ingest content and the query layer can retrieve it, no mechanism previously existed for operators or downstream clients to inspect what has been ingested. This system introduces a read-only browsing surface that makes the contents of the document store and vector index introspectable without disrupting the existing ingestion or querying workflows.

### How It Works

The system exposes a set of read-only HTTP endpoints grouped into four functional areas. The first area handles document listing and retrieval: a paginated list endpoint enumerates ingested documents by consulting the document store for primary records and the vector index for chunk counts, merging the two sources into a unified result. A detail endpoint returns full content and metadata for a single document, and a URL endpoint issues a time-limited download link. The second area covers source aggregation: a sources endpoint collapses individual documents into distinct source groups and reports summary statistics per source. The third area exposes collection-level visibility: a stats endpoint runs aggregate queries against a named vector collection and returns document and chunk counts broken down by ingestion connector; a list endpoint enumerates all collections visible to the configured vector client. The fourth area is the backend layer: new functions are added to both the document store module and the vector store module to support listing and aggregation operations, and both backend abstraction interfaces are extended so all concrete implementations can fulfill the new contracts. Typed request/response schemas govern every endpoint's contract surface, and all new schemas have round-trip contract tests.

### Tunable Knobs

Operators can control pagination depth: listing endpoints accept page size and offset parameters, and the system enforces a maximum items-per-page ceiling to prevent runaway responses. Filtering is available on most listing endpoints by source substring or connector type, allowing callers to narrow results without retrieving the full corpus. When fetching a download URL, callers control how long the URL remains valid within a configurable floor-to-ceiling window. Collection targeting lets callers direct queries at a non-default collection when multiple collections are maintained.

### Design Rationale

The system is strictly read-only by design. Mutation operations — ingest, delete, recreate — already exist in separate pipelines and administrative routes; mixing them here would blur the browsing concern with lifecycle management. Aggregation is performed using the vector store's native aggregate query capability rather than full object iteration, keeping collection-stats responses fast and avoiding memory overhead proportional to corpus size. The backend abstraction interfaces are extended rather than bypassed so new concrete implementations pick up the listing and aggregation contract automatically. Backward compatibility is preserved by treating interface extension carefully: no existing public function signatures change, and new abstract methods are phased in alongside concrete implementations.

### Boundary Semantics

Entry point: an authenticated HTTP request carrying optional filter and pagination parameters. The system resolves the caller's tenant context before any query. Exit point: a JSON response envelope containing either a paginated result set or a detail record; on error, a structured error response. The system does not write to any store. It does not cache results. When the vector store is unreachable, listing endpoints degrade gracefully by returning document-store results with a null chunk count rather than failing entirely. Responsibility ends at the HTTP response boundary; downstream consumers own interpretation and display.

---

## 2) Document Header

| Field | Value |
|-------|-------|
| **Companion spec** | `DOCUMENT_MANAGEMENT_SPEC.md` v1.0.0 |
| **System** | RAG Server API — Document & Collection Management subsystem |
| **Status** | Draft |
| **Summary version** | aligned to spec v1.0.0 (2026-03-27) |
| **See also** | `SERVER_API_SPEC.md`, `PLATFORM_SERVICES_SPEC.md` |

---

## 3) Scope and Boundaries

**Entry point:** Authenticated HTTP GET requests to the document and collection management route group.

**Exit point:** Paginated JSON result sets, single-document detail responses, presigned download URLs, source summaries, and collection statistics objects.

### In Scope

- Read-only HTTP endpoints for browsing ingested documents and vector collections
- New backend functions in the document store and vector store subsystems to support listing and aggregation
- Typed request/response schemas for all new endpoints
- Contract tests for all new schemas

### Out of Scope

- Mutation endpoints (create, update, delete) — handled by existing ingestion and deletion pipelines
- Full-text search over document content — use the existing query endpoint
- Admin-only collection management (drop, recreate) — handled by existing admin routes

---

## 4) Architecture / Pipeline Overview

```
HTTP GET request
      |
      v
 [Auth + Tenant Resolution]
      |
      v
 [Documents Router]  (/api/v1/documents, /api/v1/sources, /api/v1/collections)
      |
      +---> [Document Store Backend]   list_documents(), get_document(), get_document_url()
      |           |
      |           v
      |     [Object Store]  (content .md + metadata sidecar per document)
      |
      +---> [Vector Store Backend]     aggregate_by_source(), get_collection_stats(), list_collections()
                  |
                  v
            [Vector Index]  (chunk objects with source_key, connector metadata)
      |
      v
 [Schema Validation + Response]
      |
      v
 JSON response envelope  (list / detail / stats / URL / error)
```

Optional path: when the vector store is unreachable, listing endpoints return document-store results with `chunk_count: null` rather than a hard failure.

---

## 5) Requirement Framework

- **ID convention:** `FR-3000` through `FR-3079` for functional requirements; `NFR-3000` through `NFR-3004` for non-functional requirements.
- **Priority keyword:** `SHALL` throughout — all requirements are mandatory for v1.0.0.
- **Acceptance criteria:** Every endpoint-level requirement carries explicitly enumerated AC clauses (`AC-{FR-ID}-{N}`). Backend and schema requirements also carry ACs. NFRs do not carry explicit ACs but define measurable targets inline.
- **Rationale:** Not stated per-requirement; design rationale is embedded in the NFR section.
- **Traceability matrix:** A full FR-to-endpoint, FR-to-schema, and FR-to-AC traceability matrix is included in the spec (Section 4).

---

## 6) Functional Requirement Domains

The spec covers eight requirement domains across FR-3000 to FR-3079:

- **Document Listing (FR-3000–FR-3009):** Paginated endpoint enumerating ingested documents with filtering by source and connector; aggregation logic joining document store and vector index results.
- **Document Detail (FR-3010–FR-3019):** Single-document retrieval by stable ID returning full content and metadata; presigned download URL generation with configurable expiry.
- **Source Listing (FR-3020–FR-3029):** Aggregated source-level summary endpoint grouping documents by distinct source with document and chunk counts.
- **Collection Statistics (FR-3030–FR-3039):** Per-collection stats endpoint using vector index aggregate queries; collection enumeration endpoint.
- **Document Store Backend (FR-3040–FR-3049):** New `list_documents()` function on the document store module; extension of the document backend abstraction interface and its public API facade.
- **Vector Store Aggregation (FR-3050–FR-3059):** Three new functions on the vector store module (`aggregate_by_source`, `get_collection_stats`, `list_collections`); extension of the vector backend abstraction interface and its public API facade.
- **Pydantic Schemas (FR-3060–FR-3069):** Eight typed request/response models covering all endpoint contracts; round-trip contract tests for every model.
- **Route Module (FR-3070–FR-3079):** New router module following the existing router factory pattern; authentication and tenant-isolation enforcement on all handlers; structured error responses for 404, 503, and 422 conditions.

---

## 7) Non-Functional and Security Themes

- **Latency:** The spec defines response time targets for listing and collection-stats endpoints.
- **Pagination safety:** All listing endpoints enforce a maximum page size ceiling; no unbounded result sets are permitted.
- **Backward compatibility:** Existing public API signatures in both the document store and vector store facades must remain unchanged; new abstract methods must not break existing concrete implementations during rollout.
- **Observability:** All new backend functions must emit distributed tracing spans consistent with existing store modules; errors must be logged with structured context.
- **Tenant isolation:** All endpoints resolve tenant context before querying; vector queries must include a tenant filter when the resolved tenant is not the system default.

---

## 8) Design Principles

- **Read-only surface:** Browsing and mutation are separate concerns; this subsystem makes no writes.
- **Aggregate, don't iterate:** Vector index statistics use native aggregate queries to avoid full-corpus object scans.
- **Graceful degradation:** When the vector index is unreachable, listing endpoints return partial results rather than failing entirely.
- **Thin route handlers:** Business logic lives in backend functions; route handlers only map requests to backends and format responses.
- **Stable public API:** Backend abstraction interfaces and public facades remain backward-compatible across the rollout of new concrete implementations.

---

## 9) Key Decisions

- **Strictly read-only scope.** Mutation operations are explicitly out of scope. This keeps the browsing surface narrow and independent of ingestion pipeline changes.
- **Dual-source aggregation for document listings.** The document listing endpoint joins the document store (authoritative source of record) with the vector index (chunk counts) rather than treating either as the single source of truth.
- **Backend interface extension over bypass.** New listing and aggregation capabilities are added to the existing backend abstraction interfaces rather than implemented as standalone utilities, ensuring all current and future concrete backends inherit the contract.
- **Factory function router pattern.** The new route module follows the existing `create_*_router()` factory convention, keeping application assembly consistent.
- **Contract tests co-located with server tests.** Schema contract tests live alongside existing server tests, not in a separate validation module.

---

## 10) Acceptance and Evaluation

The spec provides acceptance criteria at the requirement level for all endpoint-level and most backend-level requirements. Schema requirements additionally specify round-trip serialization tests and required-field validation behavior. NFRs state measurable targets inline (latency ceilings, pagination size limits).

No separate evaluation framework or feedback loop is defined — this is a synchronous API subsystem, not a machine-learning pipeline.

---

## 11) External Dependencies

| Dependency | Role | Failure behavior |
|------------|------|-----------------|
| Document object store | Primary document listing source; presigned URL generation | Hard failure on detail/URL endpoints; listing degrades to partial results |
| Vector index | Chunk count aggregation; collection enumeration and stats | Listing degrades (null chunk counts); stats/collections endpoints return 503 |
| Authentication layer | Request principal resolution | All endpoints fail if auth is unavailable |
| Tenant resolver | Tenant context for query scoping | All endpoints fail if tenant resolution fails |
| Distributed tracing provider | Span emission for observability | Non-blocking; tracing failure does not affect response |

---

## 12) Companion Documents

This summary is a **Layer 2** digest of the **Layer 3** authoritative specification (`DOCUMENT_MANAGEMENT_SPEC.md`). It captures intent, scope, and structure but does not restate individual requirement text or acceptance-criteria values.

Related documents:

- `SERVER_API_SPEC.md` — existing server API requirements; this spec extends that surface
- `PLATFORM_SERVICES_SPEC.md` — platform-level service contracts

Downstream documents to be produced:

- `DOCUMENT_MANAGEMENT_DESIGN.md` — technical design with task decomposition and code contracts
- `DOCUMENT_MANAGEMENT_ENGINEERING_GUIDE.md` — post-implementation engineering guide

---

## 13) Sync Status

| Field | Value |
|-------|-------|
| Spec version | 1.0.0 |
| Spec date | 2026-03-27 |
| Summary written | 2026-04-10 |
| Alignment | Full — all sections of v1.0.0 are reflected |
