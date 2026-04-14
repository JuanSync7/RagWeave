## 1) Generic System Overview

### Purpose

The ingestion platform layer exists to make a two-phase document processing and embedding system reliable, consistent, and governable at scale. The two pipeline phases — document processing and embedding — each do useful functional work, but without shared cross-cutting capabilities they would be fragile, inconsistent, and ungovernable: a single model failure could halt a batch job, the same abbreviation could be interpreted differently in different stages, a document update could leave contradictory old and new data coexisting in the store, and an informal personal note could silently contaminate a high-stakes design decision. This platform specification defines the layer that prevents all of these failures.

### How It Works

The platform layer does not process documents directly. Instead, it defines contracts and behaviours that both pipeline phases must implement.

**Change detection and re-ingestion** govern what happens when a document is processed again. Each phase maintains its own hash of the artefact it consumes: the first phase tracks whether the original source file has changed; the second phase tracks whether the cleaned intermediate representation has changed. This two-key design lets each phase be re-run independently. When a document changes, the system processes it fully before removing old data, then atomically replaces previous results. If processing fails to produce new results, old data is preserved rather than deleted — ensuring no document disappears from the system due to a transient failure.

**Review tiers** classify every ingested document into one of three trust levels based on the review it has received: fully reviewed with domain sign-off, peer-reviewed but not yet signed off, or self-certified by the author. At retrieval time, a query filter controls which tiers are visible. Default queries see only the highest tier; users can explicitly widen the search. Tier status can change without re-processing the document — it is an administrative property that propagates instantly to all stored representations. Content changes to a previously approved document automatically trigger demotion, preventing stale approvals from persisting.

**Domain vocabulary** provides a shared dictionary of domain-specific abbreviations, expansions, and context notes that is injected into every model call across both pipeline phases. Documents can also define their own abbreviations inline, and these are automatically detected and merged into the working vocabulary for that processing run. Compound multi-word terms are tracked so that they are not split across chunk boundaries.

**Error handling** ensures that a failure in any individual stage or model call does not halt the pipeline. Every stage that relies on a model call has a deterministic fallback that produces a lower-quality but usable result. Structured JSON responses from model calls pass through a defensive parser that handles common formatting artefacts. Failures are logged with full detail and the document continues through remaining stages with whatever state has accumulated so far.

**Configuration** is resolved from a three-layer hierarchy: defaults, a persistent configuration file, and runtime command-line arguments. All meaningful pipeline behaviours — which stages to enable or skip, what models and providers to use, how to tune chunking, how to handle re-ingestion — are configurable without code changes. Cross-validation runs at startup to catch contradictions and mismatches before any document is processed.

**Interfaces** expose both a command-line entry point (for single-file and batch directory processing) and a programmatic API (for integration with other systems). Tier management operations are available through the API without triggering pipeline re-processing.

**Storage schema** defines the properties that every stored chunk must carry, the index type and parameters for similarity search, support for combined vector and keyword search, and a versioning strategy that allows additive schema changes without re-ingestion and defines a structured migration path for breaking changes.

### Tunable Knobs

The platform layer exposes configuration dimensions across several categories. Re-ingestion strategy controls whether unchanged documents are skipped or unconditionally deleted and reprocessed — useful when the pipeline configuration itself changes. The default review tier for newly ingested documents can be raised or lowered for different team trust baselines. Vocabulary injection can be capped to limit prompt size. Each external dependency — model providers, vector store, graph store, observability — is independently configurable, allowing the system to run fully locally without any internet connectivity. Individual pipeline stages (multimodal processing, document refactoring, cross-reference extraction, knowledge graph extraction) can be toggled off independently. Dry-run mode executes all stages without writing to any external store.

### Design Rationale

The platform layer was factored out of the two pipeline specifications because all of its concerns are genuinely cross-cutting — they apply equally to document processing and embedding, and must behave consistently across both. Putting re-ingestion logic in one pipeline spec and not the other would create conflicting implementations.

The two-hash change detection design directly follows from the two-phase pipeline structure: each phase owns the hash of its own input, which lets each phase be re-run independently without perturbing the other. This was preferred over a single hash because it supports the common scenario of re-embedding with a new model against an unchanged document corpus.

The fail-safe error handling strategy was chosen over fail-fast because the primary workload is batch ingestion of hundreds of documents. A single failure halting the batch and requiring manual restart would be operationally unacceptable. Deterministic fallbacks ensure every document produces output even when model services are unavailable.

The review tier system was designed to store everything and filter at retrieval time, rather than selectively ingesting based on trust level. This keeps the ingestion path simple and consistent, and allows tier changes to take effect instantly without re-processing.

### Boundary Semantics

The platform layer's requirements take effect at the entry point of each pipeline phase (governing change detection, configuration resolution, and error containment) and persist through to the vector store and graph store (governing schema, identity, and schema versioning). The platform layer does not define what happens inside pipeline stages — that is the responsibility of the companion pipeline specifications. The platform layer ends at the stored chunk and triple: downstream retrieval, reranking, and answer generation are outside its scope.

---

## 2) Header

| Field | Value |
|-------|-------|
| Companion Spec | `INGESTION_PLATFORM_SPEC.md` v2.3.0 |
| Document Type | Specification Summary |
| Purpose | Concise digest of the platform spec — intent, scope, structure, and key decisions |
| See Also | `DOCUMENT_PROCESSING_SPEC_SUMMARY.md`, `EMBEDDING_PIPELINE_SPEC_SUMMARY.md` |
| Status | Draft |

---

## 3) Scope and Boundaries

**Entry point:** Both the Document Processing Pipeline and the Embedding Pipeline, from the moment a document is submitted for processing through to the point data is written to (or deleted from) the vector store and graph store.

**Exit point:** Stored chunks, embeddings, review tier metadata, and knowledge graph triples in the configured storage backend. Downstream retrieval, reranking, and answer generation are not in scope.

**In scope:**

- Re-ingestion strategy and two-phase change detection (`source_hash` and `clean_hash`)
- Review tier assignment, lifecycle (promotion and demotion), and retrieval-time filtering
- Domain vocabulary management: structured dictionary, abbreviation auto-detection, model prompt injection
- Error handling strategy: stage failure containment, model fallback matrix, defensive JSON parsing
- Configuration system: hierarchy, validation, configurable components, pipeline flags
- Command-line interface and programmatic API contracts
- Shared data model: entity definitions, enumerations, deterministic identity scheme
- Vector store schema: collection properties, index requirements, schema versioning
- Non-functional requirements: performance, scalability, reliability, maintainability, security, deployment
- Evaluation framework: metrics, dataset requirements, A/B comparison
- Feedback and continuous improvement: feedback capture, analysis, improvement triggers

**Out of scope:**

- Document Processing Pipeline stage requirements (FR-100–FR-589): see `DOCUMENT_PROCESSING_SPEC.md`
- Embedding Pipeline stage requirements (FR-591–FR-1399): see `EMBEDDING_PIPELINE_SPEC.md`
- Query processing, reranking, and answer generation (downstream retrieval layer)
- User authentication and access control
- Document authoring or editing
- Real-time document change detection (push-based ingestion)

---

## 4) Architecture / Pipeline Overview

The ingestion system is governed by three companion specifications. This platform spec applies horizontally across both pipeline phases; the two pipeline specs define stage-level functional requirements.

```
┌──────────────────────────────────────────────────────────────────┐
│           INGESTION_PLATFORM_SPEC  (this document)               │
│   Cross-cutting requirements applied to both pipeline phases     │
│   Re-ingestion · Review Tiers · Domain Vocabulary               │
│   Error Handling · Config · Interface · Data Model              │
│   Storage Schema · NFR · Eval · Feedback                        │
└────────────────────┬─────────────────────┬───────────────────────┘
                     │ governs              │ governs
      ┌──────────────▼──────────┐  ┌───────▼──────────────────────┐
      │  DOCUMENT_PROCESSING    │  │    EMBEDDING_PIPELINE        │
      │  SPEC                   │  │    SPEC                      │
      │  FR-100 – FR-589        │  │    FR-591 – FR-1399          │
      │                         │  │                              │
      │  Stage 1 · Ingestion    │  │  Stage 1 · Chunking          │
      │  Stage 2 · Structure    │  │  Stage 2 · Chunk Enrichment  │
      │  Stage 3 · Multimodal   │  │  Stage 3 · Metadata Gen.     │
      │  Stage 4 · Text Clean   │  │  Stage 4 · Cross-Ref Extr.   │
      │  Stage 5 · Refactoring  │  │  Stage 5 · KG Extraction     │
      │  Stage 6 · Output       │  │  Stage 6 · Quality Valid.    │
      └─────────────┬───────────┘  │  Stage 7 · Embedding/Store   │
                    │ writes       │  Stage 8 · KG Storage        │
                    ▼             └──────────────┬───────────────┘
           ┌─────────────────┐                   │ reads / writes
           │  Clean Document │◄──────────────────┘
           │  Store          │
           │  {key}.md       │     ┌─────────────────────────────┐
           │  {key}.meta.json│     │  Vector Store               │
           └─────────────────┘     │  (chunks + embeddings)      │
                                   ├─────────────────────────────┤
                                   │  Graph Store (KG triples)   │
                                   └─────────────────────────────┘
```

**Platform spec section coverage:**

| Section | Governs | Applies To |
|---------|---------|------------|
| Re-ingestion | Two-phase change detection, skip/update strategy, atomic KG cleanup | Both pipelines |
| Review Tiers | Tier assignment, lifecycle (promotion/demotion), retrieval filtering | Embedding pipeline + retrieval layer |
| Domain Vocabulary | Dictionary loading, abbreviation auto-detection, prompt injection | Both pipelines |
| Error Handling | Stage failure containment, model fallback matrix, defensive JSON parsing | Both pipelines |
| Configuration | Config hierarchy, startup validation, configurable components | Both pipelines |
| Interface | CLI commands, programmatic API, tier management API | Both pipelines |
| Data Model | Shared entity definitions, enumerations, deterministic identity | Both pipelines |
| Storage Schema | Vector store collection schema, index type and parameters, schema versioning | Embedding pipeline + vector store |
| Non-Functional Requirements | Performance, scalability, reliability, maintainability, security, deployment | Entire ingestion system |
| Evaluation Framework | Retrieval quality metrics, evaluation dataset, A/B comparison | Both pipelines |
| Feedback | Feedback capture, storage, retrieval-time weighting, periodic analysis | Both pipelines + retrieval layer |

---

## 5) Requirement Framework

**Requirement ID prefixes:**

| Prefix | Meaning |
|--------|---------|
| **FR-** | Functional Requirement |
| **NFR-** | Non-Functional Requirement |
| **SC-** | Security / Compliance Requirement |

**Priority keywords:** RFC 2119 — `MUST`/`SHALL` (absolute), `SHOULD`/`RECOMMENDED` (conditional), `MAY`/`OPTIONAL` (optional). All 109 requirements in this specification are `MUST`.

**Requirement format:** Each requirement carries a structured ID, priority keyword, description, rationale, and one or more acceptance criteria with positive and negative test cases.

**ID range allocation:**

| ID Range | Section |
|----------|---------|
| FR-1400–FR-1499 | Re-ingestion Requirements |
| FR-1500–FR-1599 | Review Tier Requirements |
| FR-1600–FR-1699 | Domain Vocabulary Requirements |
| FR-1700–FR-1799 | Error Handling Requirements |
| FR-1800–FR-1899 | Configuration Requirements |
| FR-1900–FR-1999 | Interface Requirements |
| FR-2200–FR-2299 | Data Model Requirements |
| FR-2300–FR-2399 | Storage Schema Requirements |
| NFR-100–NFR-109 | Performance |
| NFR-200–NFR-209 | Scalability |
| NFR-300–NFR-309 | Reliability |
| NFR-400–NFR-409 | Maintainability |
| SC-100–SC-199 | Security & Compliance |
| NFR-600–NFR-699 | Deployment |
| FR-2000–FR-2099 | Evaluation Framework |
| FR-2100–FR-2199 | Feedback & Continuous Improvement |

---

## 6) Functional Requirement Domains

**FR-1400 — Re-ingestion (9 requirements)**
Covers two-phase change detection using independent hashes for each pipeline phase, two re-ingestion strategies (skip unchanged / delete and reinsert), fail-safe cleanup ordering (process before delete, abort if no new output), idempotency for unchanged documents, and two-phase knowledge graph cleanup that preserves shared nodes referenced by other documents.

**FR-1500 — Review Tiers (11 requirements)**
Defines three trust levels and their visibility rules for retrieval. Covers tier promotion and demotion lifecycle, auto-demotion when a previously approved document is re-ingested with changed content, tier changes as lightweight property updates (no re-ingestion required), configurable default tier for new documents, and retrieval-time filtering with three search space widths (default, expanded, full).

**FR-1600 — Domain Vocabulary (6 requirements)**
Covers the structured vocabulary dictionary format, multi-expansion disambiguation by domain context, injection of vocabulary terms into all model prompts, configurable cap on injected term count, auto-detection of abbreviation definitions within documents, and compound term awareness for chunk boundary decisions.

**FR-1700 — Error Handling (6 requirements)**
Stage failure containment (no pipeline crash), deterministic fallback for every model-dependent stage, structured processing log with per-stage entries, graceful degradation to partial results, defensive parsing of structured model responses, and safe defaults on parse failure that activate the fallback path.

**FR-1800 — Configuration (10 requirements)**
Single hierarchical configuration system, three-layer precedence (defaults → file → CLI), persistent configuration file format, startup cross-validation (contradictions, dimension mismatches, embedding prefix checks, context window overflow), a model registry for automated validation, and clear separation between errors (halt) and warnings (log and continue).

**FR-1900 — Interface (6 requirements)**
CLI for single-file and batch directory processing with configurable extension filters, full set of per-run override options (domain, tier, skip flags, dry run, force re-ingest, log level), batch isolation (individual failures do not halt the batch), programmatic API for pipeline invocation, and a lightweight tier management API that operates without re-processing.

**FR-2200 — Data Model (5 requirements)**
Deterministic identity for all stored objects (documents, chunks, triples) derived via cryptographic hashing. Document IDs scoped to connector namespace and stable source identity (not filename alone). Chunk IDs incorporate document ID, position, and content hash. Triple IDs incorporate subject, predicate, and object. IDs do not survive content changes — intentional for clean delete-and-reinsert behaviour.

**FR-2300 — Storage Schema (8 requirements)**
Approximate nearest-neighbour vector index with configurable construction and search parameters. Hybrid search combining vector similarity and keyword matching. Selective keyword indexing — chunk content and chunk-level metadata are keyword-indexed; document-level metadata is filterable only. Additive schema changes require no re-ingestion. Breaking changes (type change, model change) require a new collection and structured migration sequence. Pipeline version stored on every chunk.

---

## 7) Non-Functional and Security Themes

**Performance (NFR-100 series)**
- Single-document throughput targets covering processing with and without document refactoring
- Batch throughput floor for initial corpus ingestion scenarios
- Per-operation latency caps for embedding generation, vector store upsert, re-ingestion cleanup, and pipeline startup
- Memory budget per document to prevent crowding co-located services

**Scalability (NFR-200 series)**
- Sequential processing by default; parallel processing deferred
- Maximum supported document size with advisory for larger documents
- Vector store scale target (millions of chunks); graph store scale target (billions of triples)

**Reliability (NFR-300 series)**
- Zero unhandled pipeline crashes — all errors caught and logged
- 100% deterministic fallback coverage for model-dependent stages
- Lazy initialisation of all external services to support dry-run and test scenarios

**Maintainability (NFR-400 series)**
- Uniform abstract stage interface with standardised error handling and logging
- Stage replacement via interface implementation only — no changes to orchestration or other stages
- Routing decisions derived from the processing log (auditable), not inferred from configuration state

**Security & Compliance (SC-100 series)**
- Timestamped audit trail for all ingestion, deletion, and tier change operations
- Data sovereignty — all processing within the configured deployment boundary unless an external provider is explicitly configured
- Prohibition on transmitting document content to undeclared services
- Configurable data retention and expiry-based cleanup
- Credential management via environment variables or secrets manager references (plain-text credentials produce a warning)
- No generation or inference of personally identifiable information beyond what exists in source documents

**Deployment (NFR-600 series)**
- Defined minimum hardware baseline
- GPU optional — CPU-only mode fully supported
- Containerised deployment with compose support
- Support for VPC-isolated and air-gapped environments using local model providers
- Linux server deployment without containerisation

---

## 8) Design Principles

The following six principles govern all design and implementation decisions in this specification:

| Principle | Description |
|-----------|-------------|
| **Swappability over lock-in** | Every external dependency is behind a configuration interface. Provider changes require configuration changes, not code changes. |
| **Fail-safe over fail-fast** | Model failures activate deterministic fallbacks rather than halting the pipeline. Partial state (old and new data coexisting) is never permitted. |
| **Context preservation over compression** | Every numerical value, specification, and procedural step is preserved. Content restructuring does not summarise or remove information. |
| **Configuration-driven behaviour** | All pipeline behaviour is controlled via a single configuration system with runtime overrides. No stage behaviour is hard-coded. |
| **Idempotency by construction** | Every stage produces the same output given the same input. Identifiers are derived deterministically from content. Re-running against unchanged input produces an equivalent result. |
| **Controlled access over restriction** | All knowledge at all maturity levels is ingested and searchable. A tiered review system controls visibility at retrieval time without restricting what enters the system. |

---

## 9) Key Decisions

- **Two-hash change detection:** Each pipeline phase maintains an independent hash of its own input (source file vs. cleaned intermediate). This allows either phase to be re-run without triggering the other, supporting scenarios like model upgrades applied to an unchanged document corpus.
- **Fail-safe re-ingestion ordering:** New data is produced before old data is deleted. If no new data is produced, old data is preserved. If cleanup fails, new data is not inserted. This ordering prevents the store from ever reaching a state with zero representations of a document.
- **Store everything, filter at retrieval:** All documents are ingested regardless of review tier. Tier filtering is applied at query time via metadata filters. This enables tier changes to take effect immediately without re-processing and keeps ingestion logic consistent.
- **Deterministic identifiers:** All document, chunk, and triple identifiers are derived from content via cryptographic hashing. No random components. This enables idempotent re-ingestion and clean duplicate detection.
- **Single configuration hierarchy with startup validation:** All configuration resolves through one layered system, and cross-validation runs before any document is processed. Configuration errors halt startup; warnings log and continue.
- **Uniform stage interface:** All pipeline stages implement a common abstract interface. Replacing a stage requires only implementing the interface — no changes to orchestration or other stages.
- **FR-2200/FR-2300 range reservation:** Data Model and Storage Schema requirements were renumbered from their original ranges to avoid collision with the Embedding Pipeline spec's FR-1000–FR-1199 range.

---

## 10) Acceptance, Evaluation, and Feedback

**System-level acceptance criteria (§12)** cover re-ingestion cleanup completeness (zero orphaned chunks), pipeline crash rate (zero unhandled exceptions), model fallback coverage (100% of model-dependent stages), abbreviation resolution rate, cross-reference detection rate, chunk quality score distribution, and chunk count per document. Concrete thresholds are defined in the spec.

**Evaluation framework (FR-2000 to FR-2008)** defines a ground-truth dataset structure with queries, associated chunk IDs, relevance levels (primary vs. supporting), and intent classification (specification lookup, procedural how-to, conceptual explanation, troubleshooting, comparison). Required dataset size and domain coverage minimums are specified. Five retrieval quality metrics are mandated: Recall@5, Recall@10, Precision@10, Mean Reciprocal Rank, and Abbreviation Hit Rate, each with a defined target threshold. The framework supports isolated BM25 enrichment measurement and A/B comparison of pipeline configurations. Evaluation can be triggered via CLI or automatically after batch ingestion.

**Feedback and continuous improvement (FR-2100 to FR-2104)** defines storage of per-chunk user ratings as mutable properties on stored chunk objects, a feedback ingestion API linking ratings to chunk IDs and query context, retrieval-time weighting of chunks based on accumulated feedback scores, and periodic feedback analysis that flags consistently low-rated chunks as candidates for re-processing, tier demotion, or manual review.

---

## 11) External Dependencies

**Required:**

| Service | Purpose |
|---------|---------|
| Vector database | Vector storage, approximate nearest-neighbour search, hybrid search, metadata filtering |
| LLM provider | Semantic chunking, refactoring, metadata generation, cross-reference extraction, KG extraction |

**Optional:**

| Service | Purpose |
|---------|---------|
| VLM provider | Figure-to-text conversion for multimodal processing |
| Graph database | Dedicated knowledge graph storage (alternative to vector store cross-references) |
| Observability platform | Pipeline tracing and monitoring |

**Downstream contracts (outside this system):**

| Service | Interface Contract |
|---------|-------------------|
| Reranker model | Consumes chunk content and query text; the pipeline must produce chunks with sufficient standalone context for effective reranking |
| Answer generation model | Consumes ranked chunks with metadata; the pipeline stores both raw content (for display) and enriched content (for embedding) to support flexible downstream formatting |

---

## 12) Companion Documents

This summary is a digest of `INGESTION_PLATFORM_SPEC.md`. It captures intent, scope, structure, and key decisions. For requirement-level detail, acceptance criteria, and the full requirements traceability matrix, see the companion spec.

The platform spec governs cross-cutting requirements that apply to both pipeline phases. Functional stage requirements for each phase are defined in separate companion specifications. The spec also has a glossary (Appendix A) and an open questions appendix (Appendix B) not reproduced here.

| Document | Purpose |
|----------|---------|
| `INGESTION_PLATFORM_SPEC.md` | Source — platform-level cross-cutting requirements (this summary) |
| `DOCUMENT_PROCESSING_SPEC.md` | Document Processing Pipeline stage requirements (FR-100–FR-589) |
| `EMBEDDING_PIPELINE_SPEC.md` | Embedding Pipeline stage requirements (FR-591–FR-1399) |
| `DOCUMENT_PROCESSING_SPEC_SUMMARY.md` | Summary of the Document Processing spec |
| `EMBEDDING_PIPELINE_SPEC_SUMMARY.md` | Summary of the Embedding Pipeline spec |
| `DOCUMENT_PROCESSING_IMPLEMENTATION.md` | Implementation reference for Phase 1 |
| `EMBEDDING_PIPELINE_IMPLEMENTATION.md` | Implementation reference for Phase 2 |

---

## 13) Sync Status

| Field | Value |
|-------|-------|
| Companion spec version | 2.3.0 |
| Summary last updated | 2026-04-10 |
| Status | In sync |
