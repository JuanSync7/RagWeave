# Embedding Pipeline — Specification Summary

**Companion document to:** `EMBEDDING_PIPELINE_SPEC.md` (v1.0.0)
**Purpose:** Concise digest combining the conceptual pipeline overview and project requirements summary for stakeholders, reviewers, and implementers.
**See also:** `DOCUMENT_PROCESSING_SPEC_SUMMARY.md`, `INGESTION_PLATFORM_SPEC.md`, `EMBEDDING_PIPELINE_IMPLEMENTATION.md`

---

## 1. Embedding Pipeline — Conceptual Overview

> **Scope:** This section describes what the Embedding Pipeline is and how it works in generic, platform-level terms. It contains no requirement IDs and no project-specific technology choices. It is the authoritative source for this pipeline's conceptual description and is designed to be aggregated with equivalent sections from other components into a top-down platform overview.

This phase is the second of two ingestion phases. It reads clean Markdown documents from the Clean Document Store produced by the Document Processing Pipeline and transforms them into indexed, searchable vector representations stored in a vector database, alongside a complementary knowledge graph that captures relationships between documents, concepts, entities, and specifications. Where the Document Processing Pipeline is document-centric — one source file in, one clean Markdown document persisted out — this phase is **chunk-centric**: one clean Markdown document in, many stored chunk records out.

Because the two phases are decoupled at the Clean Document Store boundary, the Embedding Pipeline can operate independently. Re-indexing the corpus with a different embedding model, chunking strategy, or knowledge graph configuration requires only re-running this phase against the already-produced clean documents — the Document Processing Pipeline does not need to re-run unless the source documents themselves have changed.

The pipeline processes each document through eight stages. Three of the eight nodes are conditional: cross-reference extraction and knowledge graph extraction are skippable via configuration, and knowledge graph storage only executes when the graph store is enabled. The mandatory baseline — chunking, enrichment, metadata generation, quality validation, and vector storage — is sufficient for standard retrieval use cases. The optional stages add relationship-aware retrieval capability when the infrastructure and use case justify it.

Six design principles govern this phase. The first four are shared with the Document Processing Pipeline:

- **Swappability over lock-in:** Every external dependency — embedding model, vector store, LLM, knowledge graph store — is behind a configuration interface. Changing providers requires configuration changes, not code changes.
- **Fail-safe over fail-fast:** When an LLM call fails, the pipeline falls back to deterministic alternatives rather than halting. A single flawed LLM response never stops a batch job.
- **Context preservation over compression:** Every numerical value, specification, and procedural step is preserved through chunking and enrichment. Metadata headers add context; they do not compress or replace content.
- **Configuration-driven behaviour:** Which stages are enabled, which models are used, chunk size and overlap, quality thresholds — all controlled by a single configuration system with per-run overrides.

Two principles are specific to this phase:

- **Idempotency by construction:** Every stage produces the same output given the same input. Identifiers are derived deterministically from content. Re-processing a document against an unchanged Clean Document Store produces an equivalent result to the original run.
- **Controlled access over restriction:** All documents — regardless of maturity or review status — are ingested and stored. A tiered review system controls visibility at retrieval time without restricting what enters the system.

The eight stages of this phase are:

```
    ┌─────────────────────────────────┐
    │     CLEAN DOCUMENT STORE        │
    │  (produced by Document          │
    │   Processing Pipeline)          │
    └─────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│ [6] CHUNKING                         │
│     Split into semantic chunks       │
│     with deterministic IDs           │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│ [7] CHUNK ENRICHMENT                 │
│     Add boundary context,            │
│     build metadata headers           │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│ [8] METADATA GENERATION              │
│     Generate keywords, entities,     │
│     summaries at doc & chunk level   │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│ [9] CROSS-REFERENCE EXTRACTION [opt] │
│     Detect inter-document refs       │
│     and standard citations           │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│ [10] KNOWLEDGE GRAPH EXTRACTION [opt]│
│      Extract structured triples      │
│      for relationship-aware retrieval│
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│ [11] QUALITY VALIDATION              │
│      Filter low-quality/duplicates,  │
│      assign quality scores           │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│ [12] EMBEDDING & STORAGE             │
│      Generate vectors, clean up      │
│      old data, store in vector DB    │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│ [13] KNOWLEDGE GRAPH STORAGE [opt]   │
│      Persist triples to graph store  │
└──────────────────────────────────────┘
               │
               ▼
    Vector Database + Knowledge Graph Store
```

### 1.1 Chunking and Enrichment (Stages 6–7)

These two stages convert the processed document text into the atomic units that will be stored and retrieved. **Stage 6 (Chunking)** splits the document into semantically coherent chunks. The splitting is structure-aware: the system respects the section tree detected during document processing, ensuring that chunks do not span heading boundaries unnecessarily. Compound domain terms from the vocabulary are also respected — the chunker avoids splitting multi-word terms that would lose meaning if divided across chunk boundaries. Each chunk is assigned a deterministic identifier derived from its content via cryptographic hashing, so the same text always produces the same chunk ID. Deterministic IDs are the mechanism that makes re-ingestion work correctly: when a document is updated and re-processed, the system can identify which chunks changed (different content → different hash) and which remained the same, enabling targeted updates to the vector store rather than full deletion and re-insertion.

**Stage 7 (Chunk Enrichment)** adds two types of context to each chunk that raw splitting removes. First, boundary context: a small window of text from the end of the preceding chunk and the beginning of the following chunk is attached to each chunk. This prevents the retrieval system from returning a chunk whose first or last sentence is incomplete — for example, a chunk beginning with "the same threshold as above" would be meaningless in isolation; the boundary context from the preceding chunk provides the referent. Second, a metadata header is prepended to the chunk text: the document title, section path, and any relevant figures or tables in the chunk are assembled into a header that gives the embedding model the structural context it needs to encode the chunk's meaning correctly. The metadata header is stored with the chunk but is not embedded — only the enriched chunk text (content plus boundary context) is passed to the embedding model.

Configurable aspects of these stages include:

- **Chunk size:** The target size of each chunk in tokens. Smaller chunks improve retrieval precision but reduce the context available for generation. Larger chunks provide more context but reduce precision and increase embedding cost.
- **Chunk overlap:** A sliding window of overlap between adjacent chunks ensures that sentences at chunk boundaries are not split from their context. Overlap increases storage size proportionally but significantly reduces boundary artefacts.
- **Splitting strategy:** Fixed-size, recursive (respecting paragraph and sentence boundaries), document-aware (splitting on section headings), or semantic (splitting when topic changes) — selectable per document type or globally.
- **Boundary context window:** The number of tokens from adjacent chunks attached as boundary context.
- **Metadata header fields:** Which fields appear in the metadata header (document title, section path, review tier, source filename, page number) is configurable.

### 1.2 Knowledge Enrichment (Stages 8–10)

These three stages generate structured metadata and relationship data that augment the raw chunk text, enabling richer retrieval and relationship-aware search beyond pure vector similarity. **Stage 8 (Metadata Generation)** is mandatory and calls a language model to generate keyword sets and named entity lists at both the document level and the chunk level. At the document level it also generates a concise summary. Keywords enable hybrid search; entities — component names, specification identifiers, standard references — enable filtering and faceting. If the LLM call for a specific chunk fails, the chunk receives an empty keyword set rather than failing the pipeline.

**Stage 9 (Cross-Reference Extraction)** is optional and detects references between documents. It identifies links to external specification standards, internal section references, and citations to other documents in the corpus. Detected cross-references are stored as edges in the knowledge graph, enabling the retrieval pipeline to follow relationship chains — for example, surfacing all documents that reference a specific standard, or finding which documents were cited by a given guide. This stage only fires when cross-reference extraction is enabled in configuration.

**Stage 10 (Knowledge Graph Extraction)** is also optional and extracts structured subject-predicate-object triples from the document content. Triples capture relationships that vector similarity cannot encode directly — for example, "Component A depends on Specification B" or "Policy X requires Approval Y" — and are stored in a graph store alongside the vector database. At retrieval time, graph traversal can augment vector similarity search by following entity relationships, improving results for queries that require connecting information across multiple documents. This stage only fires when the knowledge graph store is configured.

Configurable aspects of these stages include:

- **LLM provider for metadata generation:** Independent of LLMs used in other stages. A smaller, faster model may be sufficient for keyword and entity extraction.
- **Keyword generation strategy:** Prompt constraints, maximum keywords per chunk, and whether to include domain vocabulary terms explicitly are all configurable.
- **Cross-reference detection patterns:** The schemas used to detect external standard references and internal section links are configurable per deployment domain.
- **Knowledge graph enablement:** The knowledge graph pipeline (Stages 9–10 and Stage 13) is enabled or disabled as a unit via a configuration flag. When disabled, no graph store connection is required.
- **Triple extraction schema:** The ontology of relationship types — which predicates are canonical, which entity types are tracked — is configurable per deployment domain.

### 1.3 Quality Validation and Storage (Stages 11–13)

These three stages form the exit point of the pipeline, filtering out low-value content and persisting the enriched chunks to storage. **Stage 11 (Quality Validation)** assigns a quality score to each chunk based on content completeness, coherence, keyword density, and the extraction confidence score from document processing. Chunks below a configurable quality threshold are discarded before embedding. Near-duplicate chunks — chunks whose content hash or semantic similarity exceeds a configurable threshold relative to another chunk already in the vector store — are also deduplicated at this stage. This prevents the search index from returning multiple near-identical chunks from the same source, which degrades retrieval diversity.

**Stage 12 (Embedding & Storage)** is the core persistence stage. It sends each chunk's enriched text through the configured embedding model to generate a dense vector representation. The vector, the original chunk text, and all associated metadata (keywords, entities, section path, review tier, source document ID, chunk ID, quality score) are stored as a single record in the vector database. When a document is being re-ingested, this stage first removes all previously stored chunks for that document before inserting the new chunks, ensuring the store never contains stale data from an older version. The embedding model is the most consequential configuration choice in this phase: it determines the geometry of the vector space and directly controls retrieval quality. A Bring Your Own Model (BYOM) mode allows pre-computed external embeddings to be submitted directly to the store without going through the pipeline's embedding step.

**Stage 13 (Knowledge Graph Storage)** is conditional and persists all triples extracted in Stage 10 to the graph store. Like Stage 12, it handles re-ingestion correctly by removing previously stored triples for the document before inserting new ones.

Configurable aspects of these stages include:

- **Embedding model selection:** The primary lever for retrieval quality. Switching models requires re-embedding the entire corpus from scratch.
- **Index algorithm:** HNSW (maximum query speed, higher RAM) or IVF-PQ (lower memory, slightly reduced accuracy), selectable per deployment based on available hardware.
- **Distance metric:** Cosine Similarity, Dot Product, or Euclidean Distance — must match the normalisation applied during embedding.
- **Hybrid search weight (alpha):** The balance between dense vector similarity and BM25 keyword search. Stored in pipeline configuration and applied at retrieval time.
- **Quality threshold:** The minimum quality score below which chunks are discarded before embedding.
- **Deduplication threshold:** The similarity threshold above which a chunk is considered a near-duplicate and discarded.

### 1.4 Document Review Tiers

All documents that enter the pipeline are ingested and stored regardless of their review status. Restricting ingestion to only formally approved documents would reproduce the knowledge fragmentation problem: much organisational knowledge exists only in informal notes, draft documents, and individual runbooks, all of which are valuable even before formal sign-off.

Instead, a three-tier trust classification controls visibility at retrieval time. Every stored document is assigned a review tier at ingestion: **Fully Reviewed** for formally approved documents that have passed a structured review process; **Partially Reviewed** for documents that have had some but not comprehensive review; and **Self Reviewed** for informal documents, personal notes, and draft content that have had no external review. When the retrieval pipeline receives a query, it applies a tier filter based on the query's configured minimum trust level. The tier assignment is stored as metadata alongside each chunk and is updatable — when a document's review status changes, the tier field can be updated without re-embedding.

Configurable aspects of this system include:

- **Default tier at ingestion:** The tier assigned to newly ingested documents when no explicit tier is provided. Defaults to Self Reviewed.
- **Per-query minimum tier:** Each query to the retrieval pipeline can specify a minimum tier via the console, preset system, or CLI flags.
- **Tier promotion workflow:** Part of the User Contribution system, which handles user-submitted documents and their associated approval workflow.

### 1.5 Re-ingestion and Idempotency

Because the two phases are decoupled at the Clean Document Store, each phase has its own independent change detection.

**Document Processing Pipeline change detection** compares the incoming source file's hash against the hash stored alongside the existing clean Markdown document for that source file. If they match, the source has not changed and that phase skips processing. If they differ, it re-processes the source file and overwrites the clean document.

**Embedding Pipeline change detection** compares the clean Markdown document's hash against the hash recorded at the time of the last successful embedding run for that document. If they match, the clean document has not changed and embedding is skipped. If they differ, the pipeline re-chunks and re-embeds: Stage 12 removes all previously stored chunks for that document and Stage 13 removes all previously stored triples, then inserts the new data.

This two-level change detection enables independent re-runs. When the embedding model is changed and the entire corpus must be re-indexed, the Embedding Pipeline can be forced to re-run against all clean documents without touching the Document Processing Pipeline. When source documents change, the Document Processing Pipeline updates the affected clean documents and the Embedding Pipeline picks them up on its next run.

Idempotency is enforced at the identifier level throughout. Document IDs are derived deterministically from the source file path; chunk IDs are derived deterministically from chunk content. Re-running either phase against unchanged inputs produces an equivalent result to the original run.

Configurable aspects of this behaviour include:

- **Force re-process:** Forces the Document Processing Pipeline to re-process all source files regardless of hash match. Useful when the document processing configuration has changed.
- **Force re-embed:** Forces the Embedding Pipeline to re-chunk and re-embed all clean documents regardless of hash match. The standard operation when switching embedding models.
- **Dry-run mode:** Both phases support dry-run mode that processes the full pipeline logic without writing any output, producing a report of what would change.
- **Batch processing:** The ingestion interface accepts a directory path and processes all supported documents, applying the configured file type exclusion list. Each phase can be run independently against the same directory.

### 1.6 Operational Interface

The two-phase ingestion system is operated through a shared service layer consumed by both the CLI and the web console. Neither interface contains pipeline logic — each is a thin adapter that translates its interaction model into service calls and formats the structured results for its medium.

This separation prevents duplication of business rules across interfaces, enables different interaction models without compromising the operational contract, and creates a stable contract for automation. The CLI calls the service layer directly as an in-process function call. The console and automation clients consume the same service operations via HTTP endpoints.

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│       CLI       │     │   Web Console   │     │   CI / Scripts  │
│  (terminal UX)  │     │   (browser UX)  │     │  (automation)   │
└────────┬────────┘     └────────┬────────┘     └────────┬────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 │
                                 ▼
                  ┌──────────────────────────────┐
                  │      Ingestion Service       │
                  │                              │
                  │  Shared: operations, phase   │
                  │  control, overrides, error   │
                  │  model, progress reporting,  │
                  │  configuration validation    │
                  └──────────────────────────────┘
                                 │
                                 ▼
                     Pipeline Execution (Phases 1–2)
```

The service layer defines five core operations: **single-file ingestion**, **batch ingestion** (async, returns a job ID), **job status** (current state of a running or completed batch), **job cancellation** (graceful shutdown without corrupting in-progress work), and **configuration validation** (startup checks without processing any documents).

**Phase control** applies to all operations: run full end-to-end, document processing only, or embedding only. **Per-run overrides** allow any operation to supersede configuration file settings for a single invocation: domain, tier, skip-refactoring, skip-KG, dry-run, force-reprocess, force-reembed, and log-level.

**Structured results** are the service layer's output contract — every operation returns a typed result object, not formatted text. Interface adapters format these results for their medium: CLI renders them as terminal output, the console renders them as UI components, automation clients consume them as structured data.

**Progress reporting** emits structured progress events as each document completes during batch operations. The CLI adapter streams them to stdout. The console adapter pushes them over a streaming connection. Automation clients can poll the job status endpoint instead.

The LLM fallback matrix for embedding-phase stages:

| Stage | Primary | Fallback |
|-------|---------|----------|
| Chunking | Semantic chunking via LLM | Recursive splitter on paragraph/sentence boundaries |
| Metadata Generation | LLM keyword/entity extraction | TF-IDF frequency-based keyword extraction |
| Cross-Reference Extraction | LLM implicit reference detection | Regex-only extraction |
| Knowledge Graph Extraction | LLM relationship extraction | Structural triples only (no LLM inferences) |

---

## 2. System Architecture

The pipeline is orchestrated as a LangGraph `StateGraph` (DAG). All eight nodes share a single `PipelineDocument` state object; each node reads from upstream-populated fields and writes only to its own designated output fields.

```
    ┌────────────────────────────────────┐
    │        CLEAN DOCUMENT STORE        │
    │  {source_key}.md + .meta.json      │
    │  (output of Document Processing)   │
    └────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────┐
│ [6] CHUNKING                                     │
│     Structure-aware splitting · domain-term      │
│     boundary respect · deterministic chunk IDs  │
└───────────────────────┬──────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────┐
│ [7] CHUNK ENRICHMENT                             │
│     Boundary context append · metadata header   │
│     (context_header stored, NOT embedded)        │
└───────────────────────┬──────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────┐
│ [8] METADATA GENERATION                          │
│     LLM keywords + entities · TF-IDF fallback    │
│     Doc-level summary                            │
└───────────────────────┬──────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────┐
│ [9] CROSS-REFERENCE EXTRACTION       [optional]  │
│     Inter-document links · citation detection    │
└───────────────────────┬──────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────┐
│ [10] KNOWLEDGE GRAPH EXTRACTION      [optional]  │
│      Subject-predicate-object triple extraction  │
└───────────────────────┬──────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────┐
│ [11] QUALITY VALIDATION                          │
│      Score-based filtering · near-dup detection  │
└───────────────────────┬──────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────┐
│ [12] EMBEDDING & STORAGE                         │
│      BYOM or on-pipeline embedding · delete old  │
│      data · store vectors + metadata             │
└───────────────────────┬──────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────┐
│ [13] KNOWLEDGE GRAPH STORAGE         [optional]  │
│      Persist triples · delete old triples        │
└──────────────────────────────────────────────────┘
                        │
                        ▼
         Vector Database + Knowledge Graph Store
```

Stages marked `[optional]` are conditional and skippable via configuration. Cross-cutting platform requirements (re-ingestion logic, review tier management, domain vocabulary, error handling framework, CLI/API interfaces, NFRs) are defined in `INGESTION_PLATFORM_SPEC.md`.

---

## 3. Requirements Digest

The spec covers **57 requirements**: 56 MUST, 1 SHOULD, 0 MAY.

### Clean Document Store Input Contract (`FR-591` to `FR-595` — 5 requirements)

Defines what the Embedding Pipeline reads from the Clean Document Store: the `.md` and `.meta.json` file pair per document, the `clean_hash` field for change detection, and the input validation behaviour on missing or malformed files.

### Chunking (`FR-601` to `FR-611` — 11 requirements)

Covers structure-aware splitting (respects section tree and heading boundaries), domain vocabulary compound-term boundary respect, deterministic chunk IDs from content hashing, configurable chunk size and overlap, configurable splitting strategy, maximum chunk count limit, fallback to recursive splitter when LLM chunking fails, and BYOM pre-chunked input mode.

### Chunk Enrichment (`FR-701` to `FR-705` — 5 requirements)

Covers boundary context attachment (configurable window), metadata header construction (document title, section path, review tier), separation of enriched text (embedded) from context header (stored, not embedded), configurable header fields, and enrichment failure fallback to unenriched chunk.

### Metadata Generation (`FR-801` to `FR-806` — 6 requirements)

Covers LLM-based keyword extraction at document and chunk level, named entity extraction, document-level summary generation, keyword validation gate (LLM keywords validated before use), TF-IDF fallback when LLM call fails, and configurable maximum keyword count.

### Cross-Reference Extraction (`FR-901` to `FR-905` — 5 requirements)

Covers detection of inter-document references and standard citations, configurable enablement, storage as knowledge graph edges, configurable detection patterns, and regex fallback when LLM detection fails.

### Knowledge Graph Extraction (`FR-1001` to `FR-1009` — 9 requirements)

Covers subject-predicate-object triple extraction, configurable enablement (skips Stages 10 and 13 when disabled), configurable triple extraction schema, domain vocabulary injection into extraction prompts, structural triple fallback when LLM extraction fails, confidence score per triple, configurable confidence threshold, deduplication of triples against existing graph data, and ontology versioning.

### Quality Validation (`FR-1101` to `FR-1105` — 5 requirements)

Covers quality score assignment based on content completeness and coherence, configurable discard threshold, near-duplicate detection against stored chunks, configurable deduplication threshold, and mandatory passage of review-tier metadata regardless of quality score.

### Embedding & Storage (`FR-1201` to `FR-1209` — 9 requirements)

Covers embedding model selection (BYOM mode supported), vector storage with full metadata envelope, delete-and-reinsert re-ingestion strategy, HNSW and IVF-PQ index algorithm support, configurable distance metric, hybrid search alpha storage, atomic storage (no partial writes on failure), configurable embedding model via registry, and vector dimensionality validation against model output.

### Knowledge Graph Storage (`FR-1301` to `FR-1304` — 4 requirements)

Covers graph store persistence of extracted triples, conditional execution when KG is enabled, delete-and-reinsert re-ingestion for triples, and configurable graph store provider.

---

## 4. Key Design Decisions

- **Chunk-centric, not document-centric:** The fundamental shift in this phase. One document produces many independently retrievable chunks, each with its own embedding, metadata, and quality score. The retrieval unit is the chunk, not the document.
- **Deterministic chunk IDs from content hash:** Chunk identifiers are derived from chunk content. The same text always produces the same ID, enabling targeted re-ingestion updates (changed chunks get new IDs; unchanged chunks retain the same ID and are not re-embedded).
- **`clean_hash` as the re-ingestion signal:** The Embedding Pipeline detects changes at the clean-document level, not the source-file level. This enables the two phases to re-run independently — swapping embedding models triggers only Phase 2; changing source documents triggers Phase 1 followed by Phase 2.
- **`enriched_content` embedded, `context_header` stored but not embedded:** Boundary context is concatenated into the chunk text before embedding (improving semantic encoding). The metadata header (title, section path, tier) is stored as a separate field — visible to the retrieval layer for display and filtering but not encoded into the vector.
- **Default embedding model: BAAI/bge-large-en-v1.5 (1024 dimensions):** Chosen for strong multilingual semantic coverage and benchmark performance on technical text. The chunk target size of 450 tokens is derived from the model's 512-token maximum minus 60 tokens reserved for boundary context overhead.
- **BM25 enrichment: validated LLM keywords with TF-IDF fallback:** Keywords are LLM-generated but validated before use. If the LLM produces nonsensical or hallucinated keywords, TF-IDF extraction provides a lower-quality but reliable fallback that maintains hybrid search capability.
- **KG storage v1: Weaviate cross-references:** The knowledge graph in v1 is implemented as Weaviate cross-reference properties between chunk objects, avoiding a separate graph database dependency. A Neo4j upgrade path is planned for v2 when graph traversal complexity justifies the additional infrastructure.
- **Delete-and-reinsert for re-ingestion:** When a document changes, all previously stored chunks and triples for that document are deleted before inserting the new data. The alternative (differential update of changed chunks only) was rejected because chunk boundary positions shift when content changes, making chunk-level diffing unreliable.
- **BYOM mode for embeddings:** Teams can submit pre-computed embeddings from their own fine-tuned models without running the pipeline's embedding step. This supports specialised domain models without requiring pipeline code changes.
- **LangGraph `StateGraph` for orchestration:** Enables conditional stage routing (skip KG, skip cross-refs) and future parallel branch execution without restructuring the orchestration layer.

---

## 5. Glossary of Key Abstractions

| Term | Definition |
|------|-----------|
| `Chunk` | The atomic unit of the retrieval system. A segment of document text individually embedded, stored, and returned in search results. |
| `enriched_content` | The chunk text plus boundary context from adjacent chunks. This is the field that is passed to the embedding model — not the raw chunk text. |
| `context_header` | A metadata string prepended to a chunk record containing document title, section path, and review tier. Stored with the chunk but **not** embedded. |
| `clean_hash` | The cryptographic hash of the clean Markdown file, stored in the metadata envelope. The Embedding Pipeline uses this as its change-detection signal. |
| `source_key` | The stable deterministic identifier derived from the source file path, used to locate all artefacts for a given document across both pipelines and the vector store. |
| `KGTriple` | A subject-predicate-object relationship extracted from document content and stored in the knowledge graph. |
| `ReviewTier` | The trust classification assigned to each document at ingestion (`FULLY_REVIEWED`, `PARTIALLY_REVIEWED`, `SELF_REVIEWED`), stored as chunk metadata and used as a filter at retrieval time. |
| `PipelineDocument` | The shared state object that flows through all pipeline stages. Each stage reads from upstream-populated fields and writes to its own designated fields. |
| `PipelineConfig` | The master configuration object. Resolved from the configuration file plus per-run overrides before pipeline execution begins. |
| `BaseNode` | The abstract base class that all pipeline stage implementations extend. Enforces the stage contract: shared state input, stage-scoped output, independent error handling. |
| `BYOM` | Bring Your Own Model — mode where embeddings are computed externally and passed as pre-computed vectors to the vector store, allowing custom fine-tuned models without pipeline code changes. |
| `deterministic_id()` | The SHA-256-based UUID generator used to derive chunk IDs from content and document IDs from file paths. Same input always produces the same output. |

---

## 6. Companion Documents

| Document | Role |
|----------|------|
| `EMBEDDING_PIPELINE_SPEC.md` | Authoritative requirements baseline — FR-591 through FR-1304 |
| `DOCUMENT_PROCESSING_SPEC.md` | Phase 1 functional requirements — document ingestion, cleaning, refactoring |
| `INGESTION_PLATFORM_SPEC.md` | Cross-cutting platform requirements — re-ingestion logic, review tier management, domain vocabulary, error handling, CLI/API, NFRs |
| `EMBEDDING_PIPELINE_IMPLEMENTATION.md` | Phased implementation plan for Embedding Pipeline phase (FR-591–FR-1304) |
| `DOCUMENT_PROCESSING_IMPLEMENTATION.md` | Phased implementation plan for Document Processing phase (FR-101–FR-587) |
| `INGESTION_PIPELINE_ENGINEERING_GUIDE.md` | Practical developer guide — architecture, extension steps, troubleshooting |
| `INGESTION_NEW_ENGINEER_ONBOARDING_CHECKLIST.md` | Quick-start checklist for new engineers |
| `EMBEDDING_PIPELINE_SPEC_SUMMARY.md` (this document) | Concise requirements digest combining conceptual overview and project-specific summary |

---

## 7. Sync Status

Aligned to `EMBEDDING_PIPELINE_SPEC.md` v1.0.0 as of 2026-03-20.

Supersedes: `RAG_embedding_pipeline_spec_summary.md` (Embedding Pipeline sections only).
