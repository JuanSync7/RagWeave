# RAG Document Embedding Pipeline — Platform Specification (v2.1.0)

## Document Information

> **Document intent:** This is a formal specification for **cross-cutting platform requirements** of the ingestion pipeline — re-ingestion, review tiers, domain vocabulary, error handling, configuration, interfaces, data model, storage schema, non-functional requirements, evaluation, and feedback.
> For the 13-node pipeline functional requirements (FR-100 through FR-1304), see `INGESTION_PIPELINE_SPEC.md`.
> For current implementation details, use:
>
> - `INGESTION_PIPELINE_ENGINEERING_GUIDE.md`
> - `INGESTION_NEW_ENGINEER_ONBOARDING_CHECKLIST.md`
> - `src/ingest/README.md`

| Field | Value |
|-------|-------|
| System | AION RAG Document Embedding Pipeline |
| Document Type | Platform Specification (Cross-Cutting Requirements) |
| Companion Documents | INGESTION_PIPELINE_SPEC.md (Pipeline Functional Requirements), RAG_embedding_pipeline_spec_summary.md (Summary), INGESTION_PIPELINE_IMPLEMENTATION.md (Implementation Guide) |
| Version | 2.1.0 |
| Status | Draft |

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0.0 | — | — | Initial specification (part of monolithic spec) |
| 2.0.0 | 2026-03-10 | — | Restructured to align with write-spec skill |
| 2.1.0 | 2026-03-17 | AI Assistant | Split from monolithic RAG_embedding_pipeline_spec.md. This file contains sections 4-16 (cross-cutting requirements FR-1400+, NFR, SC) and appendices. |

---

## 4. Re-ingestion Requirements (FR-1400)

> **FR-1401** | Priority: MUST
> **Description:** The system MUST detect prior ingestion using persisted ingestion state keyed by stable source identity (for example, manifest keyed by `source_key`), with vector-store verification optional.
> **Rationale:** Manifest-based identity lookup is deterministic and fast for incremental ingestion, and avoids mandatory pre-query overhead against vector storage for every source.
> **Acceptance Criteria:** Given a source whose `source_key` exists in ingestion state, the source is flagged as previously ingested and participates in hash/version comparison. Given a source with no matching identity in ingestion state, it is flagged as new. Implementations MAY additionally verify vector-store presence for reconciliation.

> **FR-1402** | Priority: MUST
> **Description:** The system MUST compare content hashes to determine whether the document has changed since last ingestion.
> **Rationale:** Supports idempotency-by-construction. Content hash comparison provides a reliable, fast mechanism to determine whether re-processing is needed, avoiding unnecessary LLM calls and compute costs for unchanged documents while ensuring changed documents are always re-processed.
> **Acceptance Criteria:** Given a previously ingested document whose stored content hash is "abc123" and the current file's computed hash is "abc123", the system determines the document is unchanged. If the current hash is "def456", the system determines the document has changed. The hash algorithm is deterministic: the same file content always produces the same hash.

> **FR-1403** | Priority: MUST
> **Description:** If the document is unchanged and the strategy is "skip unchanged", the system MUST skip processing entirely (no-op).
> **Rationale:** Supports idempotency-by-construction. Re-processing an unchanged document wastes compute, incurs LLM costs, and risks introducing non-determinism. Skipping unchanged documents is essential for efficient batch re-ingestion of document directories where most documents have not changed.
> **Acceptance Criteria:** Given a batch of 100 documents where 95 are unchanged and the strategy is `reingestion.strategy: "skip_unchanged"`, the system processes only 5 documents. The 95 unchanged documents produce zero LLM calls, zero new chunks, and zero vector store writes. The pipeline log records each skipped document with reason "unchanged (hash match)".

> **FR-1404** | Priority: MUST
> **Description:** If the document has changed, the system MUST process it through the full pipeline and then clean up all previous data (chunks, embeddings, KG triples) before inserting new data.
> **Rationale:** Stale data from a previous version of a document must be removed to prevent contradictory information from coexisting in the vector store (e.g., old timing constraints alongside new ones). Processing before cleanup ensures new data is ready before old data is removed, minimising the window of data unavailability.
> **Acceptance Criteria:** Given document "SPEC-CLK-001 v2" (changed from v1, which had 45 chunks), the system: (1) processes v2 through the full pipeline producing 50 new chunks, (2) deletes all 45 old chunks and their embeddings from the vector store, (3) deletes all KG triples owned by the old version, (4) inserts the 50 new chunks. After completion, the vector store contains exactly 50 chunks for "SPEC-CLK-001", all from v2.

> **FR-1405** | Priority: MUST
> **Description:** Re-ingestion cleanup MUST be fail-safe: if cleanup of old data fails, the system MUST halt and NOT insert new data on top of stale data. Partial state (stale + new data coexisting) MUST NOT occur.
> **Rationale:** Supports fail-safe-over-fail-fast. Partial state (old and new chunks coexisting for the same document) would cause the retrieval layer to return contradictory results — e.g., both the old 0.9V supply voltage and the new 0.75V supply voltage for the same design block — which could propagate into design errors.
> **Acceptance Criteria:** Given a re-ingestion where cleanup of old chunks fails (e.g., vector store connection timeout during deletion), the system halts and does not insert the new chunks. The vector store retains only the old 45 chunks (consistent state). The pipeline log records the failure with the error detail. A subsequent retry re-attempts the full cleanup-then-insert sequence.

> **FR-1406** | Priority: MUST
> **Description:** If re-ingestion processing fails upstream (zero new chunks produced due to errors), the system MUST abort cleanup and preserve existing data. Data loss (deleting old data with nothing to replace it) MUST NOT occur.
> **Rationale:** Supports fail-safe-over-fail-fast. If the pipeline fails to produce new chunks (e.g., due to a parsing error in the updated document), deleting the old data would leave the document with zero searchable content — a worse outcome than retaining the stale but functional previous version.
> **Acceptance Criteria:** Given a re-ingestion of "SPEC-CLK-001 v2" where structure detection fails and produces zero chunks, the system does not delete the existing 45 chunks from v1. The pipeline log records "re-ingestion aborted: zero new chunks produced, preserving existing data". The vector store retains the 45 v1 chunks unchanged.

> **FR-1407** | Priority: MUST
> **Description:** Re-ingesting an unchanged document MUST produce no new data and no side effects (idempotent).
> **Rationale:** Supports idempotency-by-construction. Running the pipeline twice on the same unchanged document must be indistinguishable from running it once, ensuring that batch re-ingestion scripts can be safely re-run without corrupting or duplicating data.
> **Acceptance Criteria:** Given document "SPEC-CLK-001" ingested at time T1, re-ingesting the same unchanged file at T2 produces: zero new chunks, zero deleted chunks, zero new KG triples, zero deleted KG triples, zero LLM calls (beyond the initial hash check). The vector store state at T2 is byte-identical to T1. The pipeline log records "skipped: unchanged".

> **FR-1408** | Priority: MUST
> **Description:** The system MUST support two re-ingestion strategies: "skip unchanged" and "delete and reinsert".
> **Rationale:** Supports configuration-driven-behaviour. "Skip unchanged" is optimal for routine batch updates where most documents are stable. "Delete and reinsert" is needed when the pipeline configuration has changed (e.g., new chunking strategy or embedding model) and all documents must be reprocessed regardless of content changes.
> **Acceptance Criteria:** Given `reingestion.strategy: "skip_unchanged"`, an unchanged document is skipped. Given `reingestion.strategy: "delete_and_reinsert"`, the same unchanged document is fully reprocessed: old chunks are deleted and new chunks (produced by the current pipeline configuration) are inserted. Both strategies are selectable via configuration without code changes.

> **FR-1409** | Priority: MUST
> **Description:** KG cleanup for shared graph nodes MUST use a two-phase approach: delete edges owned by the document first, then garbage-collect nodes only referenced by that document. Shared nodes referenced by other documents MUST be preserved.
> **Rationale:** Knowledge graph nodes may be shared across documents (e.g., the entity "TSMC N5" appears in many specifications). Naively deleting all nodes associated with a re-ingested document would destroy shared entities and break triples from other documents, corrupting the knowledge graph.
> **Acceptance Criteria:** Given documents A and B that both reference entity "TSMC N5", re-ingesting document A: (1) deletes all edges owned by document A (e.g., ("SPEC-A", "targets", "TSMC N5")), (2) checks whether "TSMC N5" is referenced by any other document, (3) finds that document B still references "TSMC N5" and preserves the node. If document B is subsequently deleted and "TSMC N5" has no remaining references, the garbage collector removes the orphaned node. The node reference count is verified before and after cleanup.
>
## 5. Review Tier Requirements (FR-1500)

### 5.1 Tier Definitions

> **FR-1501** | Priority: MUST
> **Description:** The system MUST implement a three-tier review system: Fully Reviewed (Tier 1), Partially Reviewed (Tier 2), and Self-Reviewed (Tier 3).
> **Rationale:** Engineering knowledge exists at varying maturity levels (controlled-access-over-restriction). A tiered system prevents conflating an approved specification with an engineer's personal notes, directly addressing the problem of indistinguishable authority levels.
> **Acceptance Criteria:** Given the system is initialised, when the review tier enumeration is inspected, then exactly three tiers exist: Fully Reviewed (Tier 1), Partially Reviewed (Tier 2), and Self-Reviewed (Tier 3). Negative: attempting to assign a tier value outside these three (e.g., "Tier 0" or "Unreviewed") is rejected.

> **FR-1502** | Priority: MUST
> **Description:** **Tier 1 — Fully Reviewed:** Formally reviewed documents with domain lead sign-off. MUST always be included in default search results. Represents authoritative, design-decision-grade content.
> **Rationale:** In ASIC design, relying on unverified content for design decisions (e.g., voltage specifications, timing constraints) can propagate errors into silicon. Tier 1 ensures default search surfaces only sign-off-grade content (controlled-access-over-restriction).
> **Acceptance Criteria:** Given a Tier 1 document (e.g., a signed-off 7nm PDK specification), when a user performs a default search, then Tier 1 results appear. Given a Tier 2 or Tier 3 document, when a user performs a default search, then those results do not appear.

> **FR-1503** | Priority: MUST
> **Description:** **Tier 2 — Partially Reviewed:** Documents with at least one peer review but not yet signed off. MUST be included in expanded search results with a visual indicator. Represents informational content.
> **Rationale:** Peer-reviewed but unsigned content (e.g., a DFT methodology guide reviewed by a colleague) has value but must be visually distinguished from authoritative sources to prevent accidental reliance on non-final content (controlled-access-over-restriction).
> **Acceptance Criteria:** Given a Tier 2 document (e.g., a peer-reviewed clock domain crossing guide), when a user performs an expanded search, then the document appears with a visual indicator distinguishing it from Tier 1 results. Negative: Tier 2 results do not appear in default (Tier 1-only) searches.

> **FR-1504** | Priority: MUST
> **Description:** **Tier 3 — Self-Reviewed:** Documents where the author self-certifies. MUST only be included when the user explicitly expands the search space. Represents community/informal knowledge.
> **Rationale:** Informal knowledge (e.g., an engineer's personal runbook for analog simulation setup) should be searchable but never surfaced alongside authoritative specs unless explicitly requested (controlled-access-over-restriction).
> **Acceptance Criteria:** Given a Tier 3 document (e.g., a self-certified personal simulation script guide), when a user performs a full search, then the document appears. Negative: Tier 3 results do not appear in default or expanded searches.

### 5.2 Tier Lifecycle

> **FR-1510** | Priority: MUST
> **Description:** The system MUST support tier promotion: Self-Reviewed → Partially Reviewed (via peer review) → Fully Reviewed (via domain lead sign-off).
> **Rationale:** Documents mature over time; a personal runbook may be peer-reviewed and eventually formally approved. The system must support this natural lifecycle (controlled-access-over-restriction).
> **Acceptance Criteria:** Given a Tier 3 document, when a peer review is recorded, then the document is promoted to Tier 2. Given a Tier 2 document, when a domain lead sign-off is recorded, then the document is promoted to Tier 1. Negative: attempting to promote directly from Tier 3 to Tier 1 (skipping peer review) is rejected.

> **FR-1511** | Priority: MUST
> **Description:** The system MUST support tier demotion: Fully Reviewed → Partially Reviewed (via major revision or re-ingestion with changes).
> **Rationale:** A previously approved document that undergoes major revision is no longer verified as authoritative until re-reviewed. Failing to demote risks surfacing stale-approved content (fail-safe-over-fail-fast).
> **Acceptance Criteria:** Given a Tier 1 document, when a major revision triggers demotion, then the document becomes Tier 2. Negative: demotion below Tier 2 (e.g., directly to Tier 3) does not occur via this mechanism.

> **FR-1512** | Priority: MUST
> **Description:** When a Fully Reviewed document is re-ingested with content changes, the system MUST auto-demote it to Partially Reviewed and flag the demotion as automatic.
> **Rationale:** If a signed-off ASIC power specification is re-ingested with changed voltage values, it is no longer the same approved document. Auto-demotion prevents stale approvals from persisting (fail-safe-over-fail-fast, idempotency-by-construction).
> **Acceptance Criteria:** Given a Tier 1 document with content hash H1, when re-ingested with a different content hash H2, then the document is demoted to Tier 2 and the demotion is flagged as "automatic". Given a Tier 1 document re-ingested with unchanged content, then no demotion occurs.

> **FR-1513** | Priority: MUST
> **Description:** Review tier changes MUST NOT require re-ingestion. Tier updates MUST be property updates on existing stored objects.
> **Rationale:** Re-ingesting a document just to change its review status would be wasteful and could alter chunk boundaries. Tier is an administrative property, not a content property (configuration-driven-behaviour).
> **Acceptance Criteria:** Given a stored document with 15 chunks at Tier 3, when the tier is promoted to Tier 2, then all 15 chunks reflect the new tier without re-running the pipeline. The chunk content, IDs, and embeddings remain unchanged.

> **FR-1514** | Priority: MUST
> **Description:** The default review tier for new documents MUST be configurable (default: Self-Reviewed).
> **Rationale:** Different organisations may have different trust baselines. A team that pre-reviews all documents before ingestion may want Tier 2 as default (configuration-driven-behaviour).
> **Acceptance Criteria:** Given default configuration, when a new document is ingested without specifying a tier, then it is assigned Tier 3 (Self-Reviewed). Given configuration overriding default tier to Tier 2, when a new document is ingested, then it is assigned Tier 2.

### 5.3 Retrieval-Time Filtering

> **FR-1520** | Priority: MUST
> **Description:** The system MUST support three search spaces at retrieval time: Default (Tier 1 only), Expanded (Tier 1 + Tier 2), and Full (all tiers).
> **Rationale:** Engineers need the ability to widen or narrow their search depending on context — design-critical decisions use Default, exploratory research uses Full (controlled-access-over-restriction).
> **Acceptance Criteria:** Given documents across all three tiers, when a Default search is executed, then only Tier 1 results are returned. When an Expanded search is executed, then Tier 1 and Tier 2 results are returned. When a Full search is executed, then all tiers are returned.

> **FR-1521** | Priority: MUST
> **Description:** Review tier filtering MUST be applied at query time, not at ingestion time. All documents MUST be stored regardless of tier.
> **Rationale:** Filtering at ingestion time would require re-ingestion to change visibility. Storing everything and filtering at query time supports tier promotion without re-processing (controlled-access-over-restriction, idempotency-by-construction).
> **Acceptance Criteria:** Given a Tier 3 document is ingested, when the vector store is inspected, then all chunks from that document are present. When a Default search is executed, then those chunks are excluded by the query filter, not by absence from the store.

---

## 6. Domain Vocabulary Requirements (FR-1600)

> **FR-1601** | Priority: MUST
> **Description:** The system MUST support a domain vocabulary dictionary in a structured format (e.g., YAML) containing abbreviations, expansions, domains, context notes, related terms, and compound terms.
> **Rationale:** ASIC/semiconductor engineering uses dense abbreviations (DFT, CDC, PVT, LVS) where meaning depends on context. A structured vocabulary is the foundation for consistent term handling across the pipeline (context-preservation).
> **Acceptance Criteria:** Given a YAML vocabulary file containing an entry for "DFT" with expansion "Design for Testability", domain "verification", and related terms ["scan", "ATPG"], when loaded, then all fields are accessible to downstream stages. Negative: a vocabulary file missing the required schema fields (e.g., no "expansion" key) is rejected with a validation error.

> **FR-1602** | Priority: MUST
> **Description:** The vocabulary MUST support ambiguous abbreviations with multiple expansions disambiguated by domain context (e.g., "CDR" = "Critical Design Review" in general context, "Clock Data Recovery" in analog context).
> **Rationale:** Term ambiguity is a core problem (problem statement item 1). "CDR" in a project management document means something entirely different from "CDR" in a SerDes design guide. Domain-aware disambiguation prevents incorrect expansion (context-preservation).
> **Acceptance Criteria:** Given a vocabulary entry for "CDR" with two expansions — "Critical Design Review" (domain: project_management) and "Clock Data Recovery" (domain: analog) — when processing a document classified as "analog", then "CDR" resolves to "Clock Data Recovery". When processing a document classified as "project_management", then "CDR" resolves to "Critical Design Review".

> **FR-1603** | Priority: MUST
> **Description:** The vocabulary MUST be injectable into all LLM prompts across the pipeline to ensure consistent abbreviation handling.
> **Rationale:** Without vocabulary injection, each LLM call independently interprets domain abbreviations, leading to inconsistent expansions across stages (context-preservation, configuration-driven-behaviour).
> **Acceptance Criteria:** Given a vocabulary with 50 terms, when the chunking stage constructs its LLM prompt, then the relevant vocabulary terms are included. When the metadata generation stage constructs its prompt, then vocabulary terms are also included. Negative: no LLM-calling stage omits vocabulary injection.

> **FR-1604** | Priority: MUST
> **Description:** The number of vocabulary terms injected into prompts MUST be configurable to manage prompt size.
> **Rationale:** Injecting the full vocabulary (potentially hundreds of terms) into every prompt wastes tokens and may exceed context windows. Configurability balances coverage against cost (configuration-driven-behaviour).
> **Acceptance Criteria:** Given a vocabulary with 200 terms and max_prompt_terms configured to 50, when an LLM prompt is constructed, then at most 50 vocabulary terms are included. Given max_prompt_terms set to 0, then no terms are injected.

> **FR-1605** | Priority: MUST
> **Description:** The system MUST auto-detect abbreviation definitions within documents (e.g., "Design for Testability (DFT)", abbreviation tables) and merge them with the domain vocabulary for the current processing run.
> **Rationale:** Documents often define their own abbreviations inline or in glossary tables. Auto-detection captures document-specific terms that may not exist in the master vocabulary, improving downstream expansion accuracy (context-preservation).
> **Acceptance Criteria:** Given a document containing the text "Phase-Locked Loop (PLL)" where "PLL" is not in the domain vocabulary, when structure detection completes, then "PLL" → "Phase-Locked Loop" is available in the merged vocabulary for subsequent stages. Given an abbreviation table in the document listing "ESD" → "Electrostatic Discharge", then this mapping is also merged.

> **FR-1606** | Priority: MUST
> **Description:** The compound terms list MUST inform chunking to avoid splitting multi-word domain terms across chunk boundaries.
> **Rationale:** Splitting "clock domain crossing" across two chunks degrades both chunks — one has "clock domain" without "crossing", the other has "crossing" without context. Compound term awareness preserves term integrity (context-preservation).
> **Acceptance Criteria:** Given a compound term "clock domain crossing" in the vocabulary, when chunking a document, then this three-word term is never split across chunk boundaries. Negative: if "clock domain crossing" is not in the compound terms list, the chunker is not obligated to keep it together.

---

## 7. Error Handling Requirements (FR-1700)

> **FR-1701** | Priority: MUST
> **Description:** Processing stage failures MUST NOT crash the pipeline. Errors MUST be captured, logged, and the document MUST continue to the next stage with whatever state it had before the failure.
> **Rationale:** In batch processing of hundreds of engineering documents, a single parsing failure (e.g., a corrupted PDF table) must not halt the entire job. The pipeline must be resilient (fail-safe-over-fail-fast).
> **Acceptance Criteria:** Given a document where the metadata generation stage throws an exception, when the pipeline continues, then the document proceeds to the next stage with metadata fields empty/default. The error is logged with stage name, document ID, and exception details. Negative: the pipeline does not terminate or skip the entire document.

> **FR-1702** | Priority: MUST
> **Description:** Every stage that makes LLM calls MUST have a deterministic fallback that produces a usable (if lower quality) result.
> **Rationale:** LLM services are inherently unreliable (rate limits, timeouts, malformed responses). A deterministic fallback ensures the pipeline always produces output, even if degraded (fail-safe-over-fail-fast).
> **Acceptance Criteria:** Given that the LLM service is unavailable, when the chunking stage executes, then it falls back to the recursive character splitter and produces valid chunks. This applies to all six LLM-dependent stages (see 7.1 LLM Fallback Matrix). Negative: no LLM-dependent stage exists without a corresponding fallback implementation.

> **FR-1703** | Priority: MUST
> **Description:** The system MUST record a processing log with timestamped entries for every stage (started, completed, skipped, failed) with relevant metrics.
> **Rationale:** Without a processing log, diagnosing why a particular document produced poor-quality chunks requires re-running the pipeline with debug logging. Structured logs enable post-hoc analysis and auditing (fail-safe-over-fail-fast).
> **Acceptance Criteria:** Given a document processed through the full pipeline, when the processing log is inspected, then it contains one entry per stage with: stage name, status (started/completed/skipped/failed), timestamp, and stage-specific metrics (e.g., chunk count for chunking, triple count for KG extraction). Negative: no stage completes without writing a log entry.

> **FR-1704** | Priority: MUST
> **Description:** A document MUST be able to complete the pipeline with partial results. Missing data from failed stages MUST cause downstream stages to skip gracefully via input validation.
> **Rationale:** If cross-reference extraction fails, the document should still be chunked, embedded, and stored — just without cross-reference metadata. Partial results are better than no results (fail-safe-over-fail-fast).
> **Acceptance Criteria:** Given a document where the refactoring stage fails and returns original text, when chunking executes, then it operates on the original text and produces valid chunks. Given a document where KG extraction fails, when embedding and storage executes, then chunks are stored successfully without KG triples.

> **FR-1705** | Priority: MUST
> **Description:** LLM responses expected to be structured (JSON) MUST be parsed through a defensive parser that handles common LLM response formatting issues (code fences, leading/trailing text).
> **Rationale:** LLMs frequently wrap JSON in markdown code fences (```json ...```) or prepend conversational text. A rigid JSON parser would fail on valid content due to formatting artifacts (fail-safe-over-fail-fast).
> **Acceptance Criteria:** Given an LLM response containing `"```json\n{\"keywords\": [\"PVT\", \"corner\"]}\n```"`, when parsed, then the JSON object is extracted successfully. Given an LLM response containing `"Here is the result: {\"keywords\": [\"LVS\"]}"`, when parsed, then the JSON object is extracted. Negative: given a response containing no valid JSON, then the parser returns a parse failure (not a crash).

> **FR-1706** | Priority: MUST
> **Description:** On JSON parse failure, the system MUST use stage-specific safe defaults that trigger the deterministic fallback path.
> **Rationale:** When the LLM returns unparseable output (e.g., truncated JSON from a timeout), the stage must not crash or produce corrupt data. Safe defaults activate the fallback, ensuring continuity (fail-safe-over-fail-fast).
> **Acceptance Criteria:** Given a chunking stage where the LLM returns invalid JSON, when the parse fails, then the stage returns a safe default that triggers the recursive character splitter fallback. Given a metadata stage where the LLM returns invalid JSON, then the stage falls back to TF-IDF keyword extraction.

### 7.1 LLM Fallback Matrix

| Stage | Primary (LLM) | Fallback (Deterministic) |
|-------|---------------|--------------------------|
| Chunking | Semantic chunking via LLM | Recursive character splitter on paragraph/sentence boundaries |
| Refactoring | Multi-pass agentic refactoring | Return original text unchanged |
| Metadata Generation | LLM keyword/entity extraction | TF-IDF frequency-based keyword extraction |
| Cross-Reference Extraction | LLM implicit reference detection | Regex-only extraction |
| Multimodal Processing | VLM image-to-text | Figure recorded without description |
| Knowledge Graph Extraction | LLM relationship extraction | Structural triples only |

---

## 8. Configuration Requirements (FR-1800)

### 8.1 General Configuration

> **FR-1801** | Priority: MUST
> **Description:** All pipeline behaviour MUST be driven by a single hierarchical configuration system.
> **Rationale:** Scattering configuration across environment variables, code constants, and config files creates inconsistency and makes reproducibility impossible. A single system ensures one source of truth (configuration-driven-behaviour).
> **Acceptance Criteria:** Given the pipeline is started, when configuration is loaded, then all configurable parameters (LLM provider, chunk sizes, skip flags, etc.) are resolved from the same configuration hierarchy. Negative: no pipeline behaviour is controlled by hard-coded constants that cannot be overridden via configuration.

> **FR-1802** | Priority: MUST
> **Description:** Configuration MUST support three-layer precedence: defaults → configuration file → command-line arguments. Command-line arguments MUST always take priority.
> **Rationale:** Defaults provide sensible baselines, config files capture team/project settings, and CLI arguments enable per-run overrides (e.g., `--dry-run` or `--skip-refactoring` for a quick test). This layered approach is standard practice (configuration-driven-behaviour).
> **Acceptance Criteria:** Given a default chunk size of 512, a config file setting chunk size to 768, and a CLI argument `--chunk-size 1024`, when the pipeline resolves configuration, then chunk size is 1024. Given only the config file (no CLI override), then chunk size is 768. Given no config file and no CLI override, then chunk size is 512.

> **FR-1803** | Priority: MUST
> **Description:** The system MUST support a configuration file format (e.g., JSON) for persistent configuration.
> **Rationale:** Persistent configuration files enable version-controlled, reproducible pipeline settings shared across team members (configuration-driven-behaviour).
> **Acceptance Criteria:** Given a JSON configuration file specifying LLM provider, embedding model, and chunking parameters, when the pipeline is started with `--config path/to/config.json`, then all specified parameters are loaded. Negative: a malformed JSON file produces a clear validation error at startup, not a runtime crash.

### 8.2 Configurable Components

The following components MUST be configurable:

| Category | Configurable Aspects |
|----------|---------------------|
| LLM Provider | Provider (OpenAI, Anthropic, Ollama, etc.), model name, temperature, API key, base URL, max tokens, timeout |
| VLM Provider | Provider, model name, base URL, timeout |
| Embedding Model | Provider (HuggingFace, OpenAI, Cohere, etc.), model name, dimension, query/document prefixes, batch size, normalisation, device |
| Vector Store | URL, collection name, BYOM mode, index parameters, distance metric |
| Structure Detector | Provider, OCR enablement, table/figure extraction, quality check threshold |
| Chunking | Strategy, target/min/max chunk size, overlap, section path prepending, table atomicity, boundary context sentences |
| Quality | Minimum chunk tokens, duplicate similarity threshold, deduplication enablement, boilerplate patterns |
| Refactoring | Maximum iterations, fact-check enablement, completeness-check enablement, confidence threshold |
| Review | Default tier, auto-demotion on re-ingestion, approval requirement for promotion |
| Knowledge Graph | Enablement, provider (vector store cross-refs or graph database), spec value extraction, relationship extraction, max triples per chunk |
| Vocabulary | Dictionary path, auto-detection, prompt injection, max prompt terms |
| Re-ingestion | Strategy (skip unchanged / delete and reinsert), hash algorithm, vector/KG cleanup flags |
| Observability | Tracing enablement, log level |
| Evaluation | Enablement, dataset path, auto-run after batch, metrics list, alert thresholds |

### 8.3 Pipeline-Level Flags

| Flag | Purpose |
|------|---------|
| Skip multimodal | Bypass VLM processing |
| Skip refactoring | Bypass document refactoring |
| Skip cross-references | Bypass cross-reference extraction |
| Skip knowledge graph | Bypass KG extraction and storage |
| Dry run | Execute full pipeline without writing to external stores |

### 8.4 Configuration Validation

> **FR-1840** | Priority: MUST
> **Description:** The system MUST cross-validate configuration at startup before processing any documents.
> **Rationale:** Detecting invalid configuration after processing 50 documents wastes compute and time. Fail-fast at startup prevents wasted work (configuration-driven-behaviour).
> **Acceptance Criteria:** Given a configuration with embedding dimension set to 384 but the model registry declares the configured model outputs 768 dimensions, when the pipeline starts, then a validation error is raised before any document is processed. Negative: no document processing begins if configuration validation fails.

> **FR-1841** | Priority: MUST
> **Description:** The system MUST validate that embedding dimension matches the configured model's known dimension.
> **Rationale:** A dimension mismatch (e.g., configuring 384 dimensions for a model that outputs 768) would produce embeddings that fail at storage or return nonsensical search results (fail-safe-over-fail-fast).
> **Acceptance Criteria:** Given configuration specifying `all-MiniLM-L6-v2` with dimension 768, when the model registry declares this model outputs 384 dimensions, then a validation error is raised: "Configured dimension 768 does not match model dimension 384". Given a correct dimension of 384, then validation passes.

> **FR-1842** | Priority: MUST
> **Description:** The system MUST validate that embedding prefixes match the configured model's requirements.
> **Rationale:** Some embedding models (e.g., E5, BGE) require specific prefixes like "query:" and "passage:" for asymmetric retrieval. Missing prefixes silently degrade search quality (fail-safe-over-fail-fast).
> **Acceptance Criteria:** Given a model that requires prefixes "query:" and "passage:" but configuration specifies no prefixes, when validation runs, then a warning is raised. Given a model that requires no prefixes but configuration specifies them, then a warning is raised.

> **FR-1843** | Priority: MUST
> **Description:** The system MUST validate that target chunk size plus boundary context overhead does not exceed the embedding model's maximum input tokens.
> **Rationale:** If enriched chunks exceed the embedding model's context window (e.g., 512 tokens), they will be silently truncated, losing critical tail content like concluding specifications (context-preservation).
> **Acceptance Criteria:** Given target chunk size of 480 tokens, boundary context of 3 sentences (~50 tokens), and embedding model max input of 512 tokens, when validation runs, then a warning is raised: total estimated input (530) exceeds model limit (512). Given target chunk size of 400 with the same overhead, then validation passes.

> **FR-1844** | Priority: MUST
> **Description:** Contradictory configuration (e.g., KG enabled but KG skipped; demote on re-ingestion but preserve review tier) MUST be detected and reported as errors.
> **Rationale:** Contradictory settings create ambiguous behaviour — does KG run or not? Detecting contradictions at startup eliminates this class of bugs (configuration-driven-behaviour).
> **Acceptance Criteria:** Given configuration with `knowledge_graph.enabled = true` and `skip_knowledge_graph = true`, when validation runs, then an error is raised: "Contradictory configuration: KG enabled but KG skip flag set". Given non-contradictory configuration, then validation passes.

> **FR-1845** | Priority: MUST
> **Description:** The system MUST support a model registry that declares known model configurations (dimensions, max tokens, required prefixes) for automated validation.
> **Rationale:** Without a registry, validation requires manual lookup of each model's specifications. A registry automates this and prevents misconfiguration when switching models (swappability-over-lock-in).
> **Acceptance Criteria:** Given a model registry containing entries for "all-MiniLM-L6-v2" (dimension: 384, max_tokens: 256) and "text-embedding-3-small" (dimension: 1536, max_tokens: 8191), when the configured model is "all-MiniLM-L6-v2", then validation uses dimension 384 and max_tokens 256. Given a model not in the registry, then validation logs a warning and skips model-specific checks.

> **FR-1846** | Priority: MUST
> **Description:** Configuration errors MUST halt pipeline startup. Configuration warnings MUST be logged but not block processing.
> **Rationale:** Errors (dimension mismatch, contradictions) would cause failures or corrupt data downstream — halting is the safe choice. Warnings (suboptimal settings) inform the operator without blocking legitimate runs (fail-safe-over-fail-fast).
> **Acceptance Criteria:** Given a configuration error (e.g., dimension mismatch), when the pipeline starts, then it exits with a non-zero status and an error message. Given a configuration warning (e.g., unknown model not in registry), when the pipeline starts, then it logs the warning and proceeds to process documents.

---

## 9. Interface Requirements

### 9.1 Command-Line Interface (FR-1900)

> **FR-1901** | Priority: MUST
> **Description:** The system MUST provide a CLI for single-file processing.
> **Rationale:** Single-file processing is the fundamental operation — engineers need to ingest individual documents during authoring and review cycles (configuration-driven-behaviour).
> **Acceptance Criteria:** Given a single PDF file `power_spec_7nm.pdf`, when the CLI is invoked with `pipeline ingest power_spec_7nm.pdf`, then the document is processed through the full pipeline and stored. The CLI returns exit code 0 on success. Negative: invoking the CLI without a file path produces a usage error.

> **FR-1902** | Priority: MUST
> **Description:** The system MUST provide a CLI for batch processing (recursive directory scan) with configurable file extension filters.
> **Rationale:** Initial corpus ingestion requires processing hundreds of documents across nested directory structures. Manual single-file invocation is impractical at scale (configuration-driven-behaviour).
> **Acceptance Criteria:** Given a directory `/docs/project_alpha/` containing 50 files (.pdf, .docx, .md, .log), when the CLI is invoked with `pipeline ingest-dir /docs/project_alpha/ --extensions .pdf,.docx,.md`, then all matching files are processed recursively and .log files are excluded. The CLI reports a summary of processed/skipped/failed counts.

> **FR-1903** | Priority: MUST
> **Description:** The CLI MUST support the following options: config file path, domain override, document type override, review tier override, skip flags (multimodal, refactoring, cross-refs, KG), dry run, force re-ingestion, vocabulary path, and log level.
> **Rationale:** CLI options provide per-run overrides that take precedence over configuration file settings, enabling quick experimentation without editing config files (configuration-driven-behaviour).
> **Acceptance Criteria:** Given the CLI invoked with `pipeline ingest spec.pdf --domain analog --tier partially_reviewed --skip-refactoring --dry-run --log-level DEBUG`, then the domain is set to "analog", tier is set to Tier 2, refactoring is skipped, no writes to external stores occur, and log level is DEBUG. Each flag is independent and combinable.

> **FR-1904** | Priority: MUST
> **Description:** Individual file failures in batch mode MUST NOT halt the batch. The system MUST report a summary of successes, failures, skips, and flags.
> **Rationale:** A corrupted PDF in a batch of 200 documents should not prevent the remaining 199 from being processed. The summary enables operators to address failures without re-running the full batch (fail-safe-over-fail-fast).
> **Acceptance Criteria:** Given a batch of 10 documents where document 3 fails (corrupted PDF) and document 7 is skipped (unchanged), when the batch completes, then the summary reports: 8 succeeded, 1 failed (document 3 with error detail), 1 skipped (document 7, reason: unchanged). Exit code is non-zero if any failures occurred.

### 9.2 Programmatic API (FR-1950)

> **FR-1951** | Priority: MUST
> **Description:** The system MUST provide a programmatic API for pipeline configuration, document creation, and pipeline invocation.
> **Rationale:** Downstream systems (e.g., a web dashboard, CI/CD integration, or automated ingestion service) need to invoke the pipeline programmatically without shelling out to CLI commands (swappability-over-lock-in).
> **Acceptance Criteria:** Given a Python script, when using the API to create a PipelineConfig, construct a PipelineDocument from a file path, and invoke the pipeline, then the document is processed identically to a CLI invocation. The API returns a result object with processing status, chunk count, and any errors.

> **FR-1952** | Priority: MUST
> **Description:** The system MUST provide a non-pipeline API for review tier management (promote/demote without re-ingestion).
> **Rationale:** Tier changes are administrative operations that should not require re-processing the document through the pipeline. A dedicated API enables lightweight tier management (controlled-access-over-restriction).
> **Acceptance Criteria:** Given a stored document at Tier 3, when the API call `promote_tier(doc_id, new_tier=PARTIALLY_REVIEWED, reviewer="john.doe")` is invoked, then all chunks for that document are updated to Tier 2 without re-ingestion. The review metadata records the reviewer and timestamp. Negative: attempting to promote to an invalid tier value raises a validation error.

---

## 10. Data Model Requirements

### 10.1 Key Entities

The system MUST define the following key data entities:

| Entity | Description |
|--------|-------------|
| **PipelineDocument** | The shared state object flowing through all processing stages. Accumulates data from each stage. |
| **DocumentMetadata** | Document identity (ID, path), filesystem metadata (authors, dates), domain classification, generated metadata (summary, keywords), processing tracking, and content integrity hash. |
| **StructureAnalysis** | Section tree, figure list, table list, page count, and routing flags. |
| **Chunk** | The atom of the retrieval system — the unit that gets embedded and stored. Carries content, positional context, adjacency links, metadata, quality metrics, and deterministic identity. |
| **KGTriple** | A single subject-predicate-object relationship with typed nodes/edges, provenance (source chunk/document), and confidence score. |
| **CrossReference** | A detected link between documents/sections with reference type, confidence, and optional resolved target. |
| **ReviewMetadata** | Review tier, review status, reviewers, review date, notes, and auto-demotion flag. |
| **AbbreviationEntry** | Abbreviation, expansion, domain, context, related terms, and source (dictionary or auto-detected). |

### 10.2 Enumerations

| Enumeration | Values |
|-------------|--------|
| **DocumentFormat** | PDF, DOCX, HTML, MARKDOWN, PLAIN_TEXT, RST, PPTX, XLSX, UNKNOWN (Phase 2: VISIO, IMAGE, SYSTEMVERILOG) |
| **ProcessingStatus** | PENDING, IN_PROGRESS, COMPLETED, FAILED, SKIPPED |
| **ContentType** | TEXT, TABLE, FIGURE, CODE, EQUATION, LIST, HEADING |
| **ReviewTier** | FULLY_REVIEWED, PARTIALLY_REVIEWED, SELF_REVIEWED |
| **ReviewStatus** | DRAFT, SUBMITTED, IN_REVIEW, APPROVED, REJECTED |
| **KGNodeType** | DOCUMENT, CHUNK, CONCEPT, ENTITY, DOMAIN, PERSON, ABBREVIATION, SPEC_VALUE |
| **KGEdgeType** | CONTAINS, REFERENCES, DEPENDS_ON, MENTIONS, BELONGS_TO, RELATED_TO, ABBREVIATION_OF, SPECIFIES, AUTHORED_BY, SUPERSEDES, NEXT_CHUNK |

### 10.3 Deterministic Identity

> **FR-1030** | Priority: MUST
> **Description:** All identifiers (document, chunk, triple) MUST be deterministic, derived from content via cryptographic hashing.
> **Rationale:** Deterministic IDs are the foundation of idempotent re-ingestion. If the same input always produces the same IDs, the system can detect duplicates and unchanged content without external state (idempotency-by-construction).
> **Acceptance Criteria:** Given the same document file processed twice, when chunk IDs are compared, then they are identical. Given two different documents, when their document IDs are compared, then they are different. Negative: no identifier contains random components (e.g., UUIDs, timestamps).

> **FR-1031** | Priority: MUST
> **Description:** Document IDs MUST be derived from stable source identity (`source_id`) and connector namespace, not filename alone.
> **Rationale:** Filename/path-only identity fails for rename/move and multi-connector ingestion. Connector-scoped stable identity enables reliable re-ingestion cleanup and duplicate avoidance across directories/systems.
> **Acceptance Criteria:** Given the same connector document identity ingested twice, the document ID is identical both times. Given two different source identities with the same filename, the IDs differ. For local filesystem connectors, file identity may be derived from stable filesystem identity metadata (for example, device+inode).

> **FR-1032** | Priority: MUST
> **Description:** Chunk IDs MUST be derived from parent document ID, chunk position, and content hash.
> **Rationale:** Including the content hash ensures that chunks with changed content receive new IDs, enabling clean delete-and-reinsert re-ingestion. Including position ensures ordering is captured (idempotency-by-construction).
> **Acceptance Criteria:** Given a document producing 10 chunks, when chunk 5 has content "The core voltage is 0.9V", then its ID is derived from (document_id, 5, SHA256("The core voltage is 0.9V")). Given the same document with chunk 5 content changed to "The core voltage is 0.85V", then chunk 5 receives a different ID.

> **FR-1033** | Priority: MUST
> **Description:** Triple IDs MUST be derived from document ID, subject, predicate, and object.
> **Rationale:** Deterministic triple IDs enable deduplication of knowledge graph relationships across re-ingestion runs and prevent duplicate edges (idempotency-by-construction).
> **Acceptance Criteria:** Given a triple ("7nm_PDK", "SPECIFIES", "core_voltage_0.9V") from document D1, when the same triple is extracted on re-ingestion, then it receives the same triple ID. Given a different triple ("7nm_PDK", "SPECIFIES", "core_voltage_0.85V"), then it receives a different ID.

> **FR-1034** | Priority: MUST
> **Description:** Chunk IDs MUST NOT survive across content changes. When earlier content shifts chunk boundaries, all downstream chunks receive new IDs. This is intentional for the delete-and-reinsert re-ingestion strategy.
> **Rationale:** If a paragraph is inserted at the beginning of a document, all subsequent chunk boundaries shift. New IDs for all affected chunks ensure the delete-and-reinsert strategy cleanly replaces stale data (idempotency-by-construction).
> **Acceptance Criteria:** Given a document with 10 chunks, when a new paragraph is inserted before chunk 3 causing chunks 3-10 to shift, then chunks 3-10 all receive new IDs. The re-ingestion strategy deletes old chunk IDs 3-10 and inserts the new ones. Negative: old chunk IDs for positions 3-10 do not persist in the vector store after re-ingestion.

---

## 11. Storage Schema Requirements

### 11.1 Vector Store Schema

The vector store collection MUST support the following property categories:

| Category | Properties |
|----------|-----------|
| **Chunk content** | Raw content (keyword-indexed), enriched content (embedded), context header (display only) |
| **Chunk metadata** | Chunk index, content type, chunking method, token count, quality score, content hash |
| **Structural context** | Section path, page numbers |
| **Searchable metadata** | Chunk-level keywords (keyword-indexed), entities (keyword-indexed), linked figures, linked tables |
| **Navigation** | Previous/next chunk IDs |
| **Document identity** | Document ID, title, domain, type, source path, source format |
| **Document metadata** | Document-level keywords (filterable, NOT keyword-indexed), summary, content hash, extraction confidence |
| **Review** | Review tier, review status, reviewed by, review date |
| **Operational** | Retrieval feedback score, ingestion timestamp, pipeline version |

### 11.2 Vector Index Requirements

> **FR-1120** | Priority: MUST
> **Description:** The vector index MUST support approximate nearest-neighbour search.
> **Rationale:** Exact nearest-neighbour search does not scale beyond small corpora. Approximate methods (e.g., HNSW) provide sub-linear search time necessary for a target of 1.5M chunks (configuration-driven-behaviour).
> **Acceptance Criteria:** Given a vector store with 100,000 chunks, when a similarity search is executed, then results are returned using an approximate nearest-neighbour algorithm (e.g., HNSW). Negative: exact brute-force search is not used as the default search method.

> **FR-1121** | Priority: MUST
> **Description:** The vector index parameters (construction quality, search quality, connectivity) MUST be configurable.
> **Rationale:** Different deployments have different accuracy/speed trade-offs. A small team prioritises accuracy; a large deployment prioritises speed. Configurable index parameters support both (configuration-driven-behaviour).
> **Acceptance Criteria:** Given configuration specifying HNSW parameters `ef_construction=200`, `ef=100`, `max_connections=32`, when the vector index is created, then these parameters are applied. Given different parameters, then the index reflects the new settings.

> **FR-1122** | Priority: MUST
> **Description:** The system MUST support hybrid search combining vector similarity and BM25 keyword matching.
> **Rationale:** Pure vector search struggles with exact technical identifiers (e.g., "TSMC N7" or "IEEE 1149.1"). BM25 keyword matching complements semantic search by handling exact-match queries that embeddings may not capture (context-preservation).
> **Acceptance Criteria:** Given a query "JEDEC JESD79-4 DDR4 timing", when hybrid search is executed, then results include chunks matched by BM25 on "JESD79-4" even if the embedding similarity is moderate. Given a conceptual query "memory interface signal integrity", then vector similarity dominates the ranking.

> **FR-1123** | Priority: MUST
> **Description:** BM25 indexing MUST be applied to chunk content, chunk-level keywords, and entities. BM25 MUST NOT be applied to document-level keywords (to prevent cross-chunk pollution).
> **Rationale:** Document-level keywords (e.g., "power management") apply to the entire document but may not be relevant to every chunk. BM25-indexing them at the chunk level would cause irrelevant chunks to match keyword queries, reducing precision (context-preservation).
> **Acceptance Criteria:** Given a document about "power management" with 15 chunks, where chunk 7 discusses "clock gating" and chunk 12 discusses "voltage scaling", when a BM25 search for "voltage scaling" is executed, then chunk 12 matches (term in chunk content) but chunk 7 does not match solely because "voltage scaling" is a document-level keyword. Negative: document-level keywords are stored as filterable properties but are not BM25-indexed.

### 11.3 Schema Versioning

> **FR-1130** | Priority: MUST
> **Description:** Additive schema changes (new properties) MUST NOT require re-ingestion. New properties MUST be null on existing objects.
> **Rationale:** Adding a new metadata field (e.g., "compliance_standard") should not force re-processing of the entire corpus. Null defaults allow gradual population (configuration-driven-behaviour).
> **Acceptance Criteria:** Given 10,000 existing chunks in the vector store, when a new property "compliance_standard" is added to the schema, then existing chunks have `compliance_standard = null` and remain searchable. Newly ingested chunks populate the field. No re-ingestion is required.

> **FR-1131** | Priority: MUST
> **Description:** Breaking schema changes (property removal, type change, index configuration change, embedding model change) MUST require creating a new collection and re-ingesting.
> **Rationale:** Changing the embedding model produces vectors in a different semantic space — mixing old and new embeddings in the same collection produces meaningless similarity scores. A clean collection ensures consistency (idempotency-by-construction).
> **Acceptance Criteria:** Given a schema change from embedding model "all-MiniLM-L6-v2" (384 dims) to "text-embedding-3-small" (1536 dims), when the migration is performed, then a new collection is created, all documents are re-ingested with the new model, and the old collection is retained until validation completes. Negative: old and new embeddings are never mixed in the same collection.

> **FR-1132** | Priority: MUST
> **Description:** A pipeline version identifier MUST be stored on every chunk to enable identifying the schema version that produced the data.
> **Rationale:** When investigating retrieval quality issues, knowing which pipeline version produced a chunk enables targeted re-ingestion of affected documents (idempotency-by-construction).
> **Acceptance Criteria:** Given pipeline version "1.2.0", when a document is ingested, then every stored chunk has `pipeline_version = "1.2.0"`. When the pipeline is upgraded to "1.3.0" and new documents are ingested, then new chunks have `pipeline_version = "1.3.0"` while old chunks retain "1.2.0".

> **FR-1133** | Priority: MUST
> **Description:** The system MUST support a migration strategy for breaking changes: create new collection → batch re-ingest → validate → swap active collection → delete old collection.
> **Rationale:** A structured migration strategy prevents data loss during schema transitions and enables rollback if validation fails. Swapping only after validation ensures zero-downtime migration (fail-safe-over-fail-fast).
> **Acceptance Criteria:** Given a breaking schema change, when the migration is executed, then: (1) a new collection is created, (2) all documents are re-ingested into the new collection, (3) validation confirms chunk counts and search quality meet thresholds, (4) the active collection pointer is swapped, (5) the old collection is deleted only after successful swap. Negative: if validation fails at step 3, the old collection remains active and the new collection is discarded.
>
## 12. Non-Functional Requirements

### 12.1 Performance (NFR-100)

> **NFR-101** | Priority: MUST
> **Description:** Single document processing (10-page PDF, no refactoring) MUST complete in less than 60 seconds.
> **Rationale:** Engineers need timely feedback when ingesting individual documents. A sub-minute target ensures the pipeline is practical for interactive single-document workflows without requiring batch scheduling.
> **Acceptance Criteria:** Given a 10-page PDF document with refactoring disabled, when processed through the full pipeline, then wall-clock time from invocation to completion is < 60 seconds on the minimum deployment environment (20 GB RAM, 4 vCPU).

> **NFR-102** | Priority: MUST
> **Description:** Single document processing (10-page PDF, with refactoring) MUST complete in less than 180 seconds.
> **Rationale:** Refactoring involves multi-pass LLM calls with fact-check and completeness validation loops, which are inherently slower. The 180-second budget accommodates this while remaining practical for interactive use.
> **Acceptance Criteria:** Given a 10-page PDF document with refactoring enabled (max 3 iterations), when processed through the full pipeline, then wall-clock time from invocation to completion is < 180 seconds on the minimum deployment environment.

> **NFR-103** | Priority: MUST
> **Description:** Batch throughput (sequential processing) MUST achieve at least 20 documents per hour.
> **Rationale:** The target corpus is 100,000 documents. At 20 docs/hour, initial ingestion of a 500-document pilot set completes in ~25 hours — a reasonable overnight batch window. Falling below this rate makes initial corpus ingestion impractical.
> **Acceptance Criteria:** Given a batch of 20 mixed-format documents (PDFs, DOCX, Markdown) averaging 10 pages each, when processed sequentially, then all 20 complete within 60 minutes.

> **NFR-104** | Priority: MUST
> **Description:** Embedding generation for a 32-chunk batch on local CPU MUST complete in less than 5 seconds.
> **Rationale:** Embedding is a per-document bottleneck. With an average of 15 chunks per document, a 32-chunk batch covers ~2 documents. Exceeding 5 seconds would dominate the per-document processing budget.
> **Acceptance Criteria:** Given 32 chunks of typical length (300–500 tokens each), when embeddings are generated using the configured local CPU embedding model, then the batch completes in < 5 seconds.

> **NFR-105** | Priority: MUST
> **Description:** Vector store upsert of 50 chunks to localhost MUST complete in less than 2 seconds.
> **Rationale:** Storage should not be a bottleneck relative to the compute-intensive stages (embedding, LLM calls). A 2-second cap ensures storage is a minor fraction of per-document time.
> **Acceptance Criteria:** Given 50 chunks with embeddings and full metadata (32+ properties), when upserted to a localhost vector store instance, then the operation completes in < 2 seconds.

> **NFR-106** | Priority: MUST
> **Description:** Re-ingestion cleanup of 100 old chunks MUST complete in less than 3 seconds.
> **Rationale:** Re-ingestion cleanup (deleting previous chunks before inserting new ones) must be fast to keep the re-ingestion path comparable to first-time ingestion. Slow cleanup would discourage document updates (idempotency-by-construction).
> **Acceptance Criteria:** Given a document with 100 previously stored chunks, when re-ingestion cleanup is triggered, then all 100 old chunks and their embeddings are deleted in < 3 seconds.

> **NFR-107** | Priority: MUST
> **Description:** Pipeline startup (graph compilation) MUST complete in less than 1 second.
> **Rationale:** The LangGraph DAG compilation is a cold-start cost paid on every CLI invocation. Exceeding 1 second would make the tool feel sluggish for single-document interactive use.
> **Acceptance Criteria:** Given the pipeline is invoked via CLI, when the DAG is compiled and ready to accept a document, then the startup phase completes in < 1 second (excluding embedding model loading).

> **NFR-108** | Priority: MUST
> **Description:** Embedding model cold start (first-time load) MUST complete within 10–30 seconds (one-time cost).
> **Rationale:** Local embedding models require loading weights into memory on first use. This is an acceptable one-time cost per session but must be bounded to prevent perceived hangs.
> **Acceptance Criteria:** Given the embedding model has not been loaded in the current process, when the first embedding request is made, then the model loads and produces embeddings within 30 seconds. Subsequent requests in the same session incur no load penalty.

> **NFR-109** | Priority: MUST
> **Description:** Memory usage per document MUST remain below 2 GB peak RSS.
> **Rationale:** The minimum deployment environment has 20 GB RAM, shared with the vector store, graph database, and OS. A 2 GB per-document cap ensures the pipeline does not crowd out co-located services.
> **Acceptance Criteria:** Given a 100-page document (the maximum supported size per NFR-202), when processed through the full pipeline, then peak resident set size (RSS) does not exceed 2 GB as measured by process monitoring.

**Performance Targets Summary:**

| ID | Operation | Target |
|----|-----------|--------|
| NFR-101 | Single document (10pp, no refactoring) | < 60 seconds |
| NFR-102 | Single document (10pp, with refactoring) | < 180 seconds |
| NFR-103 | Batch throughput (sequential) | ≥ 20 documents/hour |
| NFR-104 | Embedding generation (32-chunk batch, local CPU) | < 5 seconds |
| NFR-105 | Vector store upsert (50 chunks, localhost) | < 2 seconds |
| NFR-106 | Re-ingestion cleanup (100 old chunks) | < 3 seconds |
| NFR-107 | Pipeline startup (graph compilation) | < 1 second |
| NFR-108 | Embedding model cold start (first-time load) | 10–30 seconds (one-time) |
| NFR-109 | Memory usage per document | < 2 GB peak RSS |

### 12.2 Scalability (NFR-200)

> **NFR-201** | Priority: MUST
> **Description:** The system MUST process documents sequentially by default. Parallel document processing is reserved for future versions.
> **Rationale:** Sequential processing simplifies state management, error handling, and resource accounting for the initial deployment. Parallelism introduces concurrency risks (e.g., KG node conflicts, vector store race conditions) that are deferred to a later phase.
> **Acceptance Criteria:** Given a batch of 10 documents, when processed, then documents are processed one at a time in order. No two documents are in-flight simultaneously. The processing log shows sequential start/end timestamps with no overlap.

> **NFR-202** | Priority: MUST
> **Description:** The system MUST support documents up to ~100 pages. Larger documents SHOULD be split before ingestion.
> **Rationale:** A 100-page limit bounds memory consumption (NFR-109) and processing time. Engineering documents rarely exceed this — those that do (e.g., 500-page combined specs) are better split into logical sub-documents for retrieval quality.
> **Acceptance Criteria:** Given a 100-page PDF, when ingested, then the pipeline processes it successfully within the NFR-109 memory limit. Given a 150-page PDF, when ingested, then the system logs a warning recommending the document be split, but continues processing.

> **NFR-203** | Priority: MUST
> **Description:** The vector store MUST support up to 1,500,000 chunks (target corpus: 100,000 documents at ~15 chunks per document). For larger deployments, sharding or domain-partitioned collections SHOULD be used.
> **Rationale:** The target corpus of 100,000 engineering documents at ~15 chunks each yields ~1.5M chunks. The vector store must handle this scale without degraded search latency. Beyond this, domain-partitioned collections provide both performance and organisational benefits.
> **Acceptance Criteria:** Given a vector store collection containing 1,500,000 chunks with embeddings, when a hybrid search query is executed, then results are returned within acceptable latency (< 500ms). The collection remains stable under continuous upsert/delete operations.

> **NFR-204** | Priority: MUST
> **Description:** The knowledge graph (graph database mode) MUST scale to billions of triples. Vector store cross-reference mode MUST be practical up to ~1M triples.
> **Rationale:** A dedicated graph database (e.g., Neo4j) is designed for graph-scale data. The vector store cross-reference fallback is a simpler alternative with inherent scale limits. Both modes must handle their expected workloads.
> **Acceptance Criteria:** Given a graph database backend, when loaded with 1 billion triples, then traversal queries (e.g., "find all documents referencing specification X") complete within acceptable latency. Given a vector store cross-reference backend with 1M triples, then cross-reference lookups remain responsive.

### 12.3 Reliability (NFR-300)

> **NFR-301** | Priority: MUST
> **Description:** The pipeline crash rate MUST be zero. All errors MUST be caught and logged, not propagated as unhandled exceptions.
> **Rationale:** In a batch processing environment, an unhandled crash in one document aborts the entire batch and potentially leaves the vector store in an inconsistent state. Zero-crash design ensures every document produces either a result or a logged error (fail-safe-over-fail-fast).
> **Acceptance Criteria:** Given a batch of 100 documents including 5 with corrupt content, 3 with unsupported formats, and 2 that trigger LLM timeouts, when processed, then the pipeline completes without any unhandled exceptions. All 10 problem documents have logged errors. The remaining 90 documents are processed successfully.

> **NFR-302** | Priority: MUST
> **Description:** Every LLM-dependent stage MUST have a deterministic fallback (100% coverage).
> **Rationale:** LLM services are inherently unreliable — they can timeout, return malformed responses, or be unavailable entirely. Without fallbacks, LLM outages would halt the entire pipeline (fail-safe-over-fail-fast).
> **Acceptance Criteria:** Given the LLM provider is unreachable, when a document is processed through the full pipeline, then every LLM-dependent stage (chunking, refactoring, metadata, cross-references, multimodal, KG extraction) activates its deterministic fallback. The document completes with lower-quality but usable results. The processing log records each fallback activation.

> **NFR-303** | Priority: MUST
> **Description:** External services (vector store, LLM, embedding model, graph database) MUST be initialised lazily on first use, not at pipeline construction time. Pipeline construction MUST succeed without external services running.
> **Rationale:** Lazy initialisation enables dry-run mode, unit testing, and pipeline configuration validation without requiring all services to be online. It also improves startup time and makes the system more resilient to transient service unavailability.
> **Acceptance Criteria:** Given the vector store and LLM provider are offline, when the pipeline is constructed (DAG compiled), then construction succeeds without errors. When a document is processed in dry-run mode, then no connection attempts are made to external services. When a document is processed in normal mode, then connections are established on first use of each service.

### 12.4 Maintainability (NFR-400)

> **NFR-401** | Priority: MUST
> **Description:** Each processing stage MUST conform to a common abstract interface with uniform error handling, logging, and state wrapping.
> **Rationale:** A uniform interface ensures that any developer can understand, debug, and modify any stage without learning stage-specific patterns. It also enables the pipeline orchestrator to treat all stages generically (swappability-over-lock-in).
> **Acceptance Criteria:** Given the abstract stage interface, when a new processing stage is implemented, then it must implement the standard methods (process, validate input, handle error). Given any existing stage, when inspected, then it conforms to the same interface with no stage-specific error handling patterns outside the interface contract.

> **NFR-402** | Priority: MUST
> **Description:** Replacing a processing stage MUST require implementing the interface and registering the new component; no other code changes.
> **Rationale:** The swappability principle requires that replacing a stage (e.g., swapping the chunking algorithm) is a localised change. If replacing a stage requires modifying orchestration code, routing logic, or other stages, the architecture has failed (swappability-over-lock-in).
> **Acceptance Criteria:** Given a new chunking implementation that conforms to the stage interface, when registered as the active chunking stage, then the pipeline uses it without any changes to other stages, the orchestrator, or the configuration schema (beyond the stage registration).

> **NFR-403** | Priority: MUST
> **Description:** The routing logic MUST derive routing decisions from the processing log (auditable) rather than directly from configuration.
> **Rationale:** When debugging why a stage was skipped or executed, the processing log provides an auditable trail. If routing reads configuration directly, the decision rationale is implicit and harder to trace (fail-safe-over-fail-fast).
> **Acceptance Criteria:** Given a document processed with cross-reference extraction skipped via configuration, when the processing log is inspected, then it contains an explicit entry such as "cross-reference extraction: SKIPPED (reason: disabled in configuration)". The routing decision is traceable to a log entry, not inferred from configuration state.

### 12.5 Security & Compliance (SC-100)

> **SC-101** | Priority: MUST
> **Description:** All pipeline operations (document ingestion, re-ingestion, deletion, tier changes) MUST produce timestamped audit trail entries suitable for compliance review.
> **Rationale:** Engineering organisations operating under ISO 9001 or similar quality frameworks require traceability of document processing actions. Audit trails enable compliance review and incident investigation.
> **Acceptance Criteria:** Given a document is ingested, when the audit log is inspected, then it contains a timestamped entry with: operation type (ingestion), document ID, source path, user/service identity, and outcome (success/failure). Given a tier change, then a separate audit entry records the old tier, new tier, and reason.

> **SC-102** | Priority: MUST
> **Description:** All document processing and data storage MUST occur within the configured deployment boundary (VPC, on-premise server, or local machine). No data MUST leave the deployment boundary unless the LLM or embedding provider is explicitly configured as an external API.
> **Rationale:** Engineering documents may contain proprietary design information (e.g., process node details, circuit architectures). Data sovereignty within the deployment boundary is a baseline security requirement.
> **Acceptance Criteria:** Given a deployment configured with local LLM and local embedding model, when a document is processed, then network monitoring confirms zero outbound data transfers beyond the deployment boundary. Given a deployment configured with an external LLM API, when a document is processed, then only LLM requests are sent externally, and the audit log records which documents were sent to which endpoint (per SC-103).

> **SC-103** | Priority: MUST
> **Description:** The system MUST NOT transmit document content to any service not explicitly listed in the pipeline configuration. When using external LLM APIs, the system MUST log which documents were sent to which external endpoint.
> **Rationale:** Prevents accidental data exfiltration via misconfigured or undeclared services. Logging external transmissions enables security audit and data lineage tracking.
> **Acceptance Criteria:** Given the pipeline configuration lists only "Ollama at localhost:11434" as the LLM provider, when a stage attempts to call a different endpoint (e.g., api.openai.com), then the request is blocked or rejected. Given an external LLM API is configured, when a document is processed, then the audit log contains entries listing each external API call with the document ID and endpoint URL.

> **SC-104** | Priority: MUST
> **Description:** Stored chunks, embeddings, and KG triples MUST support configurable retention policies. The system MUST support expiry-based cleanup of data older than a configurable retention period.
> **Rationale:** Engineering documents may have lifecycle constraints (e.g., project-specific specs that become irrelevant after tapeout). Retention policies prevent unbounded data accumulation and support data governance requirements.
> **Acceptance Criteria:** Given a retention policy of 365 days is configured, when a cleanup job runs, then all chunks, embeddings, and KG triples with an ingestion timestamp older than 365 days are identified for deletion. Given a document re-ingested within the retention period, then its timestamp is refreshed and it is not flagged for cleanup.

> **SC-105** | Priority: MUST
> **Description:** API access to the vector store and graph database MUST use configurable authentication credentials. Credentials MUST NOT be stored in plain text in configuration files; environment variable or secrets manager references MUST be supported.
> **Rationale:** Plain-text credentials in configuration files are a common security vulnerability, especially when configuration files are committed to version control. Environment variables and secrets managers are standard secure credential management approaches.
> **Acceptance Criteria:** Given a configuration file referencing a vector store API key as `${WEAVIATE_API_KEY}`, when the pipeline starts, then the key is resolved from the environment variable. Given a configuration file containing a plain-text API key (e.g., `api_key: "sk-abc123"`), when validated, then a warning is logged recommending environment variable or secrets manager usage.

> **SC-106** | Priority: MUST
> **Description:** The pipeline MUST NOT index or store personally identifiable information (PII) beyond what exists in source documents. No PII MUST be generated or inferred by pipeline processing stages.
> **Rationale:** The pipeline processes engineering documents, not personnel records. Any PII present in source documents (e.g., author names) passes through, but the pipeline must not synthesise new PII (e.g., inferring employee IDs from naming patterns).
> **Acceptance Criteria:** Given a document containing an author name "John Smith" in its header, when processed, then the author name is preserved as-is in metadata. Given a document with no PII, when metadata generation runs, then no PII is generated (e.g., no inferred author identities, no email addresses synthesised from name patterns).

### 12.6 Deployment (NFR-600)

> **NFR-601** | Priority: MUST
> **Description:** The minimum deployment environment MUST be: 20 GB RAM, 50 GB storage, 4 vCPU.
> **Rationale:** This specification sets the baseline hardware requirement to ensure consistent performance targets (NFR-100 series) are achievable. The 20 GB RAM accommodates the embedding model (~4 GB), vector store, and pipeline processing concurrently.
> **Acceptance Criteria:** Given a server with exactly 20 GB RAM, 50 GB storage, and 4 vCPU, when the full pipeline (with local embedding model and local vector store) is deployed and a 10-page PDF is processed, then all performance targets (NFR-101 through NFR-109) are met.

> **NFR-602** | Priority: MUST
> **Description:** GPU access MUST be optional. GPU is required only for local embedding model inference at scale. CPU-only mode MUST be fully supported for all pipeline operations.
> **Rationale:** Many engineering servers lack GPUs. The pipeline must be deployable on commodity hardware. GPU acceleration is a performance optimisation, not a functional requirement (configuration-driven-behaviour).
> **Acceptance Criteria:** Given a server with no GPU, when the pipeline is deployed and configured with a CPU-compatible embedding model, then all pipeline operations complete successfully. Embedding generation uses CPU inference. No errors or warnings related to missing GPU hardware appear.

> **NFR-603** | Priority: MUST
> **Description:** The system MUST support containerised deployment (Docker). A Dockerfile and docker-compose configuration MUST be provided.
> **Rationale:** Containerisation ensures reproducible deployment environments and simplifies dependency management. Docker Compose enables single-command deployment of the pipeline with its co-located services (vector store, graph database).
> **Acceptance Criteria:** Given a clean Docker host, when `docker-compose up` is executed, then the pipeline, vector store, and graph database services start successfully. When a document is ingested via CLI within the container, then it is processed and stored correctly.

> **NFR-604** | Priority: MUST
> **Description:** The system MUST support deployment within an AWS VPC with no public internet access when configured with local LLM, embedding, and VLM providers.
> **Rationale:** Engineering organisations often operate in air-gapped or VPC-isolated environments for IP protection. The pipeline must function without internet when all providers are local (fail-safe-over-fail-fast).
> **Acceptance Criteria:** Given a VPC with no internet gateway and all providers configured as local (Ollama LLM, local embedding model, local VLM), when a document is processed, then no outbound internet requests are attempted and the document is processed successfully.

> **NFR-605** | Priority: MUST
> **Description:** The system MUST support local/on-premise deployment on Linux servers (the same infrastructure used for existing batch job submission).
> **Rationale:** Engineering teams already have Linux batch job infrastructure. Deploying on existing servers avoids provisioning new hardware and leverages familiar operational workflows.
> **Acceptance Criteria:** Given a Linux server (e.g., RHEL 8/9 or Ubuntu 20.04+) with the minimum hardware requirements (NFR-601), when the pipeline is installed via standard Python packaging, then all pipeline operations function correctly without containerisation.

---

## 13. System-Level Acceptance Criteria

| Criterion | Threshold | Related Requirements |
|-----------|-----------|----------------------|
| Chunks produced per 10-page document | 8–30 (depending on density) | FR-601, FR-602 |
| Quality score distribution | > 80% of chunks score ≥ 0.5 | FR-1103, FR-1104 |
| Near-duplicate detection | 0 duplicate chunks in vector store after re-ingestion | FR-1102 |
| Re-ingestion cleanup completeness | 0 orphaned chunks from previous version | FR-1404, FR-1405 |
| Cross-reference detection | ≥ 90% of explicit references ("see Section X") detected | FR-901 |
| Abbreviation resolution | ≥ 95% of dictionary abbreviations correctly expanded | FR-1601, FR-1605 |
| LLM fallback coverage | 100% of LLM stages have deterministic fallback | FR-1702 |
| Pipeline crash rate | 0 unhandled crashes | FR-1701, NFR-301 |

---

## 14. Evaluation Framework Requirements (FR-2000)

> **FR-2001** | Priority: MUST
> **Description:** The system MUST include an evaluation framework that measures end-to-end retrieval quality against a ground-truth dataset.
> **Rationale:** Without objective measurement, there is no way to determine whether pipeline changes (e.g., new chunking strategy, different embedding model) improve or degrade retrieval quality. Evaluation closes the feedback loop between pipeline engineering and retrieval outcomes.
> **Acceptance Criteria:** Given a ground-truth dataset with queries and expected chunks, when the evaluation framework is executed, then it retrieves chunks for each query and compares results against ground truth, producing metric scores (Recall, Precision, MRR).

> **FR-2002** | Priority: MUST
> **Description:** The evaluation dataset MUST contain queries with associated ground-truth chunks, relevance levels (primary/supporting), and query intent classification.
> **Rationale:** Relevance levels distinguish "the exact answer chunk" from "a helpful context chunk." Intent classification (lookup vs. how-to vs. troubleshooting) ensures evaluation covers the diversity of real engineering queries.
> **Acceptance Criteria:** Given the evaluation dataset, when inspected, then each query entry contains: query text, a list of ground-truth chunk IDs with relevance level (primary or supporting), and an intent classification (e.g., specification_lookup, procedural_howto, conceptual_explanation, troubleshooting, comparison).

> **FR-2003** | Priority: MUST
> **Description:** The evaluation dataset MUST be built collaboratively with domain experts, covering multiple domains and query intents (specification lookup, procedural how-to, conceptual explanation, troubleshooting, comparison).
> **Rationale:** An evaluation dataset built without domain expert input would not reflect real engineering queries. Coverage across multiple domains and intents prevents optimisation for one query type at the expense of others.
> **Acceptance Criteria:** Given the evaluation dataset, when analysed, then it contains queries from at least 3 engineering domains (e.g., front-end design, DFT, physical design) and at least 4 of the 5 intent types (specification lookup, procedural how-to, conceptual explanation, troubleshooting, comparison).

> **FR-2004** | Priority: MUST
> **Description:** The minimum viable evaluation dataset MUST contain 50 queries with an average of 3 ground-truth chunks per query.
> **Rationale:** 50 queries with ~3 ground-truth chunks each provides sufficient statistical power to detect meaningful differences between pipeline configurations. Fewer queries risk noisy metrics that cannot distinguish real improvements from variance.
> **Acceptance Criteria:** Given the evaluation dataset, when counted, then it contains at least 50 queries. The total number of ground-truth chunk associations divided by the number of queries is at least 3.0.

> **FR-2005** | Priority: MUST
> **Description:** The system MUST compute the following metrics: Recall@5 (target ≥ 0.75), Recall@10 (target ≥ 0.85), Precision@10 (target ≥ 0.50), MRR (target ≥ 0.60), Abbreviation Hit Rate (target ≥ 0.95).
> **Rationale:** These metrics cover complementary aspects of retrieval quality — Recall measures completeness, Precision measures noise, MRR measures ranking quality, and Abbreviation Hit Rate measures domain-specific term handling. Targets are calibrated for engineering documentation retrieval.
> **Acceptance Criteria:** Given the evaluation framework is run against the ground-truth dataset, when results are produced, then all five metrics are computed and reported. For a passing evaluation: Recall@5 ≥ 0.75, Recall@10 ≥ 0.85, Precision@10 ≥ 0.50, MRR ≥ 0.60, Abbreviation Hit Rate ≥ 0.95.

> **FR-2006** | Priority: MUST
> **Description:** The system MUST support measuring BM25 enrichment impact in isolation (keyword-only search mode) to validate that keyword enrichment is net-positive.
> **Rationale:** BM25 keyword enrichment adds complexity and storage overhead. If keyword search does not improve retrieval over vector-only search, the enrichment is wasted effort. Isolated measurement validates the investment.
> **Acceptance Criteria:** Given the evaluation framework, when run in keyword-only mode (BM25 without vector similarity), then metrics are computed. When compared against vector-only mode, then the impact of BM25 enrichment is quantified (positive or negative delta for each metric).

> **FR-2007** | Priority: MUST
> **Description:** The evaluation framework MUST support A/B comparison of pipeline configurations (e.g., different embedding models, chunk sizes, enrichment strategies).
> **Rationale:** Iterative pipeline improvement requires comparing configurations objectively. Without A/B comparison, decisions about embedding models or chunk sizes would be based on intuition rather than measured retrieval quality.
> **Acceptance Criteria:** Given two pipeline configurations (A: 512-token chunks with BGE-large, B: 256-token chunks with BGE-M3), when both are evaluated against the same ground-truth dataset, then the framework produces a side-by-side comparison report showing metric deltas (e.g., Recall@10: A=0.82, B=0.87, delta=+0.05).

> **FR-2008** | Priority: MUST
> **Description:** The evaluation runner MUST be invocable via CLI and optionally triggered automatically after batch ingestion.
> **Rationale:** CLI invocation enables manual evaluation runs during development. Automatic post-batch evaluation catches regressions immediately when new documents are ingested (configuration-driven-behaviour).
> **Acceptance Criteria:** Given the CLI, when `pipeline evaluate --dataset eval.json` is executed, then the evaluation runs and reports results. Given the configuration `evaluation.auto_run_after_batch: true`, when a batch ingestion completes, then the evaluation framework runs automatically and results are logged.

---

## 15. Feedback & Continuous Improvement Requirements (FR-2100)

> **FR-2101** | Priority: MUST
> **Description:** The system MUST store retrieval feedback scores (per-chunk user ratings) as a mutable property on stored chunk objects in the vector store.
> **Rationale:** Feedback scores enable retrieval-time quality weighting — boosting chunks that users find helpful and penalising those that are not. Storing on the chunk object avoids a separate feedback store and keeps the signal co-located with the data it describes.
> **Acceptance Criteria:** Given a chunk stored in the vector store, when a feedback score (e.g., 4 out of 5) is recorded, then the chunk's `retrieval_feedback_score` property is updated in-place. When the chunk is subsequently retrieved, the feedback score is available for weighting.

> **FR-2102** | Priority: MUST
> **Description:** The system MUST provide a feedback ingestion API for recording user ratings (e.g., thumbs up/down, 1–5 scale) on retrieved chunks, linking each rating to the chunk ID and query context.
> **Rationale:** Structured feedback collection (chunk ID + query context + rating) enables analysis of which chunks perform well for which query types, supporting targeted pipeline improvements.
> **Acceptance Criteria:** Given the feedback API, when a rating of "thumbs down" is submitted for chunk ID "chunk-abc123" with query context "What is the clock frequency for the 7nm block?", then the rating is stored with the chunk ID and query text. When feedback records are queried, then the entry is retrievable by chunk ID or query text.

> **FR-2103** | Priority: MUST
> **Description:** Feedback scores MUST be available as a retrieval-time weighting signal, allowing the retrieval layer to boost or penalise chunks based on accumulated user feedback.
> **Rationale:** User feedback directly reflects retrieval quality from the consumer's perspective. Incorporating it as a weighting signal creates a self-improving retrieval system where frequently-helpful chunks are surfaced more prominently.
> **Acceptance Criteria:** Given two chunks with identical vector similarity scores but different feedback scores (chunk A: 4.5, chunk B: 1.2), when the retrieval layer applies feedback weighting, then chunk A is ranked higher than chunk B in the final results.

> **FR-2104** | Priority: MUST
> **Description:** The system MUST support periodic feedback analysis to identify consistently low-rated chunks or documents, flagging them as candidates for re-processing, review tier demotion, or manual review.
> **Rationale:** Chunks that consistently receive poor feedback may indicate extraction errors, stale content, or poor chunking decisions. Periodic analysis surfaces these systematically rather than relying on manual inspection.
> **Acceptance Criteria:** Given a feedback analysis job is run, when chunks with an average feedback score below a configurable threshold (e.g., < 2.0 over 10+ ratings) are identified, then they are flagged in a report listing chunk ID, document ID, average score, and rating count. The report recommends actions: re-process, demote review tier, or flag for manual review.

---

## 16. External Dependencies

### 16.1 Required Services

| Service | Purpose |
|---------|---------|
| Vector database (e.g., Weaviate) | Vector storage, approximate nearest-neighbour search, hybrid search, metadata filtering |
| LLM provider (e.g., OpenAI, Anthropic, Ollama) | Semantic chunking, refactoring, metadata generation, cross-reference extraction, KG extraction |

### 16.2 Optional Services

| Service | Purpose |
|---------|---------|
| VLM provider (e.g., Ollama/LLaVA) | Figure-to-text conversion |
| Graph database (e.g., Neo4j) | Dedicated knowledge graph storage (alternative to vector store cross-references) |
| Observability platform (e.g., Langfuse) | Pipeline tracing and monitoring |

### 16.3 Downstream Dependencies (Outside This System)

| Service | Purpose | Interface Contract |
|---------|---------|-------------------|
| Reranker model (e.g., BGE-Reranker-v2-m3) | Re-scores retrieved chunks for relevance before answer generation | Consumes chunk content + query text; the embedding pipeline SHALL produce chunks with sufficient standalone context for effective reranking |
| Answer generation LLM | Generates answers from retrieved context | Consumes ranked chunks with metadata; the pipeline SHALL store both raw content (for display) and enriched content (for embedding) to support flexible downstream formatting |

### 16.4 Deployment Constraints

> **NFR-501** | Priority: MUST
> **Description:** The system MUST support offline/air-gapped deployment using local models (local embedding model, local LLM via Ollama).
> **Rationale:** Engineering environments handling proprietary ASIC designs often operate in air-gapped networks. The pipeline must be fully functional without any internet connectivity when configured with local providers (fail-safe-over-fail-fast).
> **Acceptance Criteria:** Given a server with no network connectivity beyond localhost, when the pipeline is configured with a local embedding model and Ollama LLM, then a document is processed end-to-end with no network errors. No DNS lookups or outbound connection attempts are made.

> **NFR-502** | Priority: MUST
> **Description:** The system MUST NOT require outbound internet connectivity when configured with local providers.
> **Rationale:** This is the contrapositive of NFR-501 — ensuring that no hidden dependency (e.g., telemetry, model update checks, license validation) forces internet access when the deployment is configured for local operation.
> **Acceptance Criteria:** Given a deployment with all providers configured as local and a firewall blocking all outbound traffic, when a batch of 10 documents is processed, then all 10 complete successfully. Firewall logs show zero blocked outbound connection attempts from the pipeline process.

---

## Appendix A. Glossary

| Term | Definition |
|------|-----------|
| BM25 | Best Matching 25 — a probabilistic ranking function for keyword-based text search |
| BYOM | Bring Your Own Model — mode where embeddings are computed externally and passed as pre-computed vectors to the vector store |
| Chunk | The atomic unit of the retrieval system; a segment of document text that is individually embedded and stored |
| DAG | Directed Acyclic Graph — the processing pipeline topology |
| Deterministic ID | An identifier derived from content via cryptographic hashing, ensuring the same input always produces the same ID |
| HNSW | Hierarchical Navigable Small World — an approximate nearest-neighbour graph index algorithm |
| Hybrid Search | Combined vector similarity search and BM25 keyword search |
| Idempotent | An operation that produces the same result whether applied once or multiple times |
| Knowledge Graph | A graph of entities and relationships extracted from documents |
| LangGraph | A graph-based orchestration framework (part of the LangChain ecosystem) used to define the processing pipeline DAG |
| PII | Personally Identifiable Information — data that could identify a specific individual |
| RAG | Retrieval-Augmented Generation — a pattern where retrieved context is provided to an LLM for answer generation |
| Reranker | A cross-encoder model that re-scores retrieved chunks for relevance given a specific query, improving precision over embedding-only retrieval |
| Re-ingestion | Processing a previously ingested document again, cleaning up old data and inserting new data |
| Review Tier | A trust classification (Fully/Partially/Self Reviewed) controlling a document's visibility in search results |
| Triple | A subject-predicate-object relationship in the knowledge graph |
| VLM | Vision-Language Model — a multimodal model that can process both images and text |

---

## Appendix B. Document References

| Document | Purpose |
|----------|---------|
| RAG_embedding_pipeline_spec_summary.md | Combined specification + architecture summary — requirements overview, architecture wireframes, design decisions, risk register, and phasing |
| INGESTION_PIPELINE_IMPLEMENTATION.md | Phased implementation plan with task breakdown and code appendix |
| Strategic Proposal: AI-Enabled Knowledge Management Platform | Business case, adoption strategy, infrastructure requirements, and phased rollout plan. This spec is a sub-component of the platform described in the proposal. |

---

## Appendix C. Implementation Phasing

This section maps specification requirements to the implementation phases defined in the Strategic Proposal. Requirements not listed are included in Phase 1 by default.

### Phase 1 — Pilot (Year 1, H1)

**Objective:** Functional RAG pipeline on a document subset with baseline evaluation.

| Scope | Requirements |
|-------|-------------|
| Core pipeline stages | FR-100 (Ingestion), FR-200 (Structure), FR-400 (Cleaning), FR-600 (Chunking), FR-700 (Enrichment), FR-800 (Metadata), FR-1100 (Quality), FR-1200 (Embedding & Storage) |
| CLI interface | FR-1900 |
| Configuration system | FR-1800 (all) |
| Re-ingestion | FR-1400 (all) |
| Review tiers | FR-1500 (all) |
| Error handling & fallbacks | FR-1700 (all) |
| Basic evaluation | FR-2001–FR-2005 (core metrics on 50-query dataset) |
| Local deployment | NFR-501, NFR-502, NFR-601–NFR-605 |
| Data model & schema | FR-1030–FR-1034, FR-1120–FR-1133 |

**Success criteria:** RAG system operational on document subset; retrieval accuracy > 80% on pilot golden question set.

### Phase 2 — Core Development (Year 1, H2)

**Objective:** Full pipeline with advanced features, end-to-end automated evaluation.

| Scope | Requirements |
|-------|-------------|
| Document refactoring | FR-500 (all) |
| Multimodal processing | FR-300 (all) |
| Cross-reference extraction | FR-900 (all) |
| Knowledge graph extraction & storage | FR-1000 (all), FR-1300 (all) |
| Domain vocabulary | FR-1600 (all) |
| A/B evaluation | FR-2006–FR-2008 |
| Security foundations | SC-101–SC-103 |

**Success criteria:** End-to-end workflow operational; automated evaluation against human-validated baseline.

### Phase 3 — Production Deployment (Year 2, H1)

**Objective:** User-facing deployment with UI, feedback collection, and expanded document coverage.

| Scope | Requirements |
|-------|-------------|
| Feedback collection & analysis | FR-2100 (all) |
| Programmatic API | FR-1950 (all) |
| SharePoint integration | FR-113 |
| Observability (Langfuse) | Observability configuration (FR-1800) |
| Full security & compliance | SC-104–SC-106 |
| Web dashboard UI | Out of scope for this spec — see Strategic Proposal |

**Success criteria:** 80–90% of target documents indexed; feedback collection operational; GUI deployed.

### Phase 4 — Optimisation (Year 2, H2+)

**Objective:** Production maturity, parameter optimisation, self-service, LLM migration.

| Scope | Requirements |
|-------|-------------|
| AI-assisted parameter tuning | Feedback analysis (FR-2104) driving configuration adjustments |
| Self-service document embedding | Simplified ingestion workflow (FR-1901 + FR-1951) |
| LLM migration (cloud → self-hosted) | Swappability requirements (FR-1209, FR-306, FR-208) |
| 95% accuracy target | FR-2005 metric targets at full corpus scale |

**Success criteria:** 95% retrieval accuracy; self-service embedding functional; daily automated testing operational.

---

## Appendix D. Open Questions

The following questions SHALL be resolved before finalising this specification:

1. **Deployment model:** Containerised (Docker) or bare-metal? Single-node or distributed? *(Partially addressed by NFR-603–NFR-605; final decision needed.)*
2. **Authentication:** How do users authenticate to the vector store and graph database? How are autonomous agent service accounts provisioned? What command/operation guardrails need to be established for agent access? *(See Strategic Proposal — IT Security & Access Control questions.)*
3. **Monitoring:** What operational monitoring and alerting is required beyond the processing log? What Langfuse dashboards are needed for production?
4. **Document deletion:** Should the system support explicit document deletion (remove all chunks and KG triples for a document)?
5. **Multi-tenancy:** Should different teams/projects have separate collections or share a single collection with metadata-based isolation? *(The Strategic Proposal implies domain-level separation — Front-end, DFT, Physical Design, Verification — confirm if this maps to separate collections or metadata filters.)*
6. **Backup and recovery:** What is the backup strategy for the vector store and knowledge graph?
7. **Concurrent re-ingestion:** Should the system support concurrent re-ingestion of different documents, or is sequential processing sufficient?
8. **Retention policy:** Should documents/chunks have a configurable retention period or expiry? *(SC-104 establishes the requirement; exact retention periods need definition.)*
9. **LLM migration strategy:** The Strategic Proposal outlines a migration path from Claude API (Months 1–6) → Llama 70B via PrivateLink (Month 6+) → Llama 405B (Year 2+). What triggers the migration decision? What acceptance criteria must the self-hosted model meet before replacing the cloud API?
10. **Embedding model selection:** The Strategic Proposal specifies BGE-M3 (multi-lingual, multi-granularity); the architecture document uses BGE-large (1024d) as the reference model. Confirm the target embedding model for Phase 1 deployment.
11. **Business KPI mapping:** The Strategic Proposal targets "80% retrieval accuracy on pilot golden question set" and "30%+ productivity improvement." How do these map to the technical metrics in FR-2005 (Recall@5 ≥ 0.75, Recall@10 ≥ 0.85, MRR ≥ 0.60)? Define the translation between technical evaluation metrics and business-reported accuracy figures.

---

## Requirements Traceability Matrix

| REQ ID | Section | Priority | Component/Stage |
|--------|---------|----------|-----------------|
| FR-101 | 3.1 | MUST | Document Ingestion |
| FR-102 | 3.1 | MUST | Document Ingestion |
| FR-103 | 3.1 | MUST | Document Ingestion |
| FR-104 | 3.1 | MUST | Document Ingestion |
| FR-105 | 3.1 | MUST | Document Ingestion |
| FR-106 | 3.1 | MUST | Document Ingestion |
| FR-107 | 3.1 | MUST | Document Ingestion |
| FR-108 | 3.1 | MUST | Document Ingestion |
| FR-109 | 3.1 | MUST | Document Ingestion |
| FR-110 | 3.1 | SHOULD | Document Ingestion |
| FR-111 | 3.1 | MUST | Document Ingestion |
| FR-112 | 3.1 | MUST | Document Ingestion |
| FR-113 | 3.1 | SHOULD | Document Ingestion |
| FR-201 | 3.2 | MUST | Structure Detection |
| FR-202 | 3.2 | MUST | Structure Detection |
| FR-203 | 3.2 | MUST | Structure Detection |
| FR-204 | 3.2 | MUST | Structure Detection |
| FR-205 | 3.2 | MUST | Structure Detection |
| FR-206 | 3.2 | MUST | Structure Detection |
| FR-207 | 3.2 | MUST | Structure Detection |
| FR-208 | 3.2 | MUST | Structure Detection |
| FR-301 | 3.3 | MUST | Multimodal Processing |
| FR-302 | 3.3 | MUST | Multimodal Processing |
| FR-303 | 3.3 | MUST | Multimodal Processing |
| FR-304 | 3.3 | MUST | Multimodal Processing |
| FR-305 | 3.3 | MUST | Multimodal Processing |
| FR-306 | 3.3 | MUST | Multimodal Processing |
| FR-307 | 3.3 | MUST | Multimodal Processing |
| FR-401 | 3.4 | MUST | Text Cleaning |
| FR-402 | 3.4 | MUST | Text Cleaning |
| FR-403 | 3.4 | MUST | Text Cleaning |
| FR-404 | 3.4 | MUST | Text Cleaning |
| FR-405 | 3.4 | MUST | Text Cleaning |
| FR-501 | 3.5 | MUST | Document Refactoring |
| FR-502 | 3.5 | MUST | Document Refactoring |
| FR-503 | 3.5 | MUST | Document Refactoring |
| FR-504 | 3.5 | MUST | Document Refactoring |
| FR-505 | 3.5 | MUST | Document Refactoring |
| FR-506 | 3.5 | MUST | Document Refactoring |
| FR-507 | 3.5 | MUST | Document Refactoring |
| FR-508 | 3.5 | MUST | Document Refactoring |
| FR-601 | 3.6 | MUST | Chunking |
| FR-602 | 3.6 | MUST | Chunking |
| FR-603 | 3.6 | MUST | Chunking |
| FR-604 | 3.6 | MUST | Chunking |
| FR-605 | 3.6 | MUST | Chunking |
| FR-606 | 3.6 | MUST | Chunking |
| FR-607 | 3.6 | MUST | Chunking |
| FR-608 | 3.6 | MUST | Chunking |
| FR-609 | 3.6 | MUST | Chunking |
| FR-610 | 3.6 | MUST | Chunking |
| FR-611 | 3.6 | MUST | Chunking |
| FR-701 | 3.7 | MUST | Chunk Enrichment |
| FR-702 | 3.7 | MUST | Chunk Enrichment |
| FR-703 | 3.7 | MUST | Chunk Enrichment |
| FR-704 | 3.7 | MUST | Chunk Enrichment |
| FR-705 | 3.7 | MUST | Chunk Enrichment |
| FR-801 | 3.8 | MUST | Metadata Generation |
| FR-802 | 3.8 | MUST | Metadata Generation |
| FR-803 | 3.8 | MUST | Metadata Generation |
| FR-804 | 3.8 | MUST | Metadata Generation |
| FR-805 | 3.8 | MUST | Metadata Generation |
| FR-806 | 3.8 | MUST | Metadata Generation |
| FR-901 | 3.9 | MUST | Cross-Reference Extraction |
| FR-902 | 3.9 | MUST | Cross-Reference Extraction |
| FR-903 | 3.9 | MUST | Cross-Reference Extraction |
| FR-904 | 3.9 | MUST | Cross-Reference Extraction |
| FR-905 | 3.9 | MUST | Cross-Reference Extraction |
| FR-1001 | 3.10 | MUST | Knowledge Graph Extraction |
| FR-1002 | 3.10 | MUST | Knowledge Graph Extraction |
| FR-1003 | 3.10 | MUST | Knowledge Graph Extraction |
| FR-1004 | 3.10 | MUST | Knowledge Graph Extraction |
| FR-1005 | 3.10 | MUST | Knowledge Graph Extraction |
| FR-1006 | 3.10 | MUST | Knowledge Graph Extraction |
| FR-1007 | 3.10 | MUST | Knowledge Graph Extraction |
| FR-1008 | 3.10 | MUST | Knowledge Graph Extraction |
| FR-1009 | 3.10 | MUST | Knowledge Graph Extraction |
| FR-1101 | 3.11 | MUST | Quality Validation |
| FR-1102 | 3.11 | MUST | Quality Validation |
| FR-1103 | 3.11 | MUST | Quality Validation |
| FR-1104 | 3.11 | MUST | Quality Validation |
| FR-1105 | 3.11 | MUST | Quality Validation |
| FR-1201 | 3.12 | MUST | Embedding & Storage |
| FR-1202 | 3.12 | MUST | Embedding & Storage |
| FR-1203 | 3.12 | MUST | Embedding & Storage |
| FR-1204 | 3.12 | MUST | Embedding & Storage |
| FR-1205 | 3.12 | MUST | Embedding & Storage |
| FR-1206 | 3.12 | MUST | Embedding & Storage |
| FR-1207 | 3.12 | MUST | Embedding & Storage |
| FR-1208 | 3.12 | MUST | Embedding & Storage |
| FR-1209 | 3.12 | MUST | Embedding & Storage |
| FR-1301 | 3.13 | MUST | Knowledge Graph Storage |
| FR-1302 | 3.13 | MUST | Knowledge Graph Storage |
| FR-1303 | 3.13 | MUST | Knowledge Graph Storage |
| FR-1304 | 3.13 | MUST | Knowledge Graph Storage |
| FR-1401 | 4 | MUST | Re-ingestion |
| FR-1402 | 4 | MUST | Re-ingestion |
| FR-1403 | 4 | MUST | Re-ingestion |
| FR-1404 | 4 | MUST | Re-ingestion |
| FR-1405 | 4 | MUST | Re-ingestion |
| FR-1406 | 4 | MUST | Re-ingestion |
| FR-1407 | 4 | MUST | Re-ingestion |
| FR-1408 | 4 | MUST | Re-ingestion |
| FR-1409 | 4 | MUST | Re-ingestion |
| FR-1501 | 5.1 | MUST | Review Tiers |
| FR-1502 | 5.1 | MUST | Review Tiers |
| FR-1503 | 5.1 | MUST | Review Tiers |
| FR-1504 | 5.1 | MUST | Review Tiers |
| FR-1510 | 5.2 | MUST | Review Tiers |
| FR-1511 | 5.2 | MUST | Review Tiers |
| FR-1512 | 5.2 | MUST | Review Tiers |
| FR-1513 | 5.2 | MUST | Review Tiers |
| FR-1514 | 5.2 | MUST | Review Tiers |
| FR-1520 | 5.3 | MUST | Review Tiers |
| FR-1521 | 5.3 | MUST | Review Tiers |
| FR-1601 | 6 | MUST | Domain Vocabulary |
| FR-1602 | 6 | MUST | Domain Vocabulary |
| FR-1603 | 6 | MUST | Domain Vocabulary |
| FR-1604 | 6 | MUST | Domain Vocabulary |
| FR-1605 | 6 | MUST | Domain Vocabulary |
| FR-1606 | 6 | MUST | Domain Vocabulary |
| FR-1701 | 7 | MUST | Error Handling |
| FR-1702 | 7 | MUST | Error Handling |
| FR-1703 | 7 | MUST | Error Handling |
| FR-1704 | 7 | MUST | Error Handling |
| FR-1705 | 7 | MUST | Error Handling |
| FR-1706 | 7 | MUST | Error Handling |
| FR-1801 | 8.1 | MUST | Configuration |
| FR-1802 | 8.1 | MUST | Configuration |
| FR-1803 | 8.1 | MUST | Configuration |
| FR-1840 | 8.4 | MUST | Configuration |
| FR-1841 | 8.4 | MUST | Configuration |
| FR-1842 | 8.4 | MUST | Configuration |
| FR-1843 | 8.4 | MUST | Configuration |
| FR-1844 | 8.4 | MUST | Configuration |
| FR-1845 | 8.4 | MUST | Configuration |
| FR-1846 | 8.4 | MUST | Configuration |
| FR-1901 | 9.1 | MUST | Interface |
| FR-1902 | 9.1 | MUST | Interface |
| FR-1903 | 9.1 | MUST | Interface |
| FR-1904 | 9.1 | MUST | Interface |
| FR-1951 | 9.2 | MUST | Interface |
| FR-1952 | 9.2 | MUST | Interface |
| FR-1030 | 10.3 | MUST | Deterministic Identity |
| FR-1031 | 10.3 | MUST | Deterministic Identity |
| FR-1032 | 10.3 | MUST | Deterministic Identity |
| FR-1033 | 10.3 | MUST | Deterministic Identity |
| FR-1034 | 10.3 | MUST | Deterministic Identity |
| FR-1120 | 11.2 | MUST | Vector Index |
| FR-1121 | 11.2 | MUST | Vector Index |
| FR-1122 | 11.2 | MUST | Vector Index |
| FR-1123 | 11.2 | MUST | Vector Index |
| FR-1130 | 11.3 | MUST | Schema Versioning |
| FR-1131 | 11.3 | MUST | Schema Versioning |
| FR-1132 | 11.3 | MUST | Schema Versioning |
| FR-1133 | 11.3 | MUST | Schema Versioning |
| NFR-101 | 12.1 | MUST | Performance |
| NFR-102 | 12.1 | MUST | Performance |
| NFR-103 | 12.1 | MUST | Performance |
| NFR-104 | 12.1 | MUST | Performance |
| NFR-105 | 12.1 | MUST | Performance |
| NFR-106 | 12.1 | MUST | Performance |
| NFR-107 | 12.1 | MUST | Performance |
| NFR-108 | 12.1 | MUST | Performance |
| NFR-109 | 12.1 | MUST | Performance |
| NFR-201 | 12.2 | MUST | Scalability |
| NFR-202 | 12.2 | MUST | Scalability |
| NFR-203 | 12.2 | MUST | Scalability |
| NFR-204 | 12.2 | MUST | Scalability |
| NFR-301 | 12.3 | MUST | Reliability |
| NFR-302 | 12.3 | MUST | Reliability |
| NFR-303 | 12.3 | MUST | Reliability |
| NFR-401 | 12.4 | MUST | Maintainability |
| NFR-402 | 12.4 | MUST | Maintainability |
| NFR-403 | 12.4 | MUST | Maintainability |
| NFR-501 | 16.4 | MUST | Deployment Constraints |
| NFR-502 | 16.4 | MUST | Deployment Constraints |
| NFR-601 | 12.6 | MUST | Deployment |
| NFR-602 | 12.6 | MUST | Deployment |
| NFR-603 | 12.6 | MUST | Deployment |
| NFR-604 | 12.6 | MUST | Deployment |
| NFR-605 | 12.6 | MUST | Deployment |
| SC-101 | 12.5 | MUST | Security & Compliance |
| SC-102 | 12.5 | MUST | Security & Compliance |
| SC-103 | 12.5 | MUST | Security & Compliance |
| SC-104 | 12.5 | MUST | Security & Compliance |
| SC-105 | 12.5 | MUST | Security & Compliance |
| SC-106 | 12.5 | MUST | Security & Compliance |
| FR-2001 | 14 | MUST | Evaluation |
| FR-2002 | 14 | MUST | Evaluation |
| FR-2003 | 14 | MUST | Evaluation |
| FR-2004 | 14 | MUST | Evaluation |
| FR-2005 | 14 | MUST | Evaluation |
| FR-2006 | 14 | MUST | Evaluation |
| FR-2007 | 14 | MUST | Evaluation |
| FR-2008 | 14 | MUST | Evaluation |
| FR-2101 | 15 | MUST | Feedback |
| FR-2102 | 15 | MUST | Feedback |
| FR-2103 | 15 | MUST | Feedback |
| FR-2104 | 15 | MUST | Feedback |

**Total Requirements: 200**

- MUST: 198
- SHOULD: 2
- MAY: 0
