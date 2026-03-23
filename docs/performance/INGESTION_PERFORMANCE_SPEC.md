# RAG Ingestion Performance and Validation Specification

## Document Information

> **Document intent:** This is a formal specification for the **ingestion performance and validation layer** — the "left side" quality gate that measures whether the ingestion pipeline produces good chunks and embeddings in the first place. If embeddings are bad, no amount of retrieval tuning helps.
> For the 13-node pipeline functional requirements, see `docs/ingestion/INGESTION_PIPELINE_SPEC.md`.
> For cross-cutting platform requirements (re-ingestion, config, error handling), see `docs/ingestion/INGESTION_PLATFORM_SPEC.md`.
> For the companion retrieval-side performance spec, see `RAG_RETRIEVAL_PERFORMANCE_SPEC.md`.

| Field | Value |
|-------|-------|
| System | AION RAG Document Embedding Pipeline |
| Document Type | Performance Specification (Validation & Quality Requirements) |
| Companion Documents | INGESTION_PIPELINE_SPEC.md (Pipeline Functional Requirements), INGESTION_PLATFORM_SPEC.md (Platform/Cross-Cutting Requirements), RAG_RETRIEVAL_PERFORMANCE_SPEC.md (Retrieval Performance) |
| Version | 1.0 |
| Status | Draft |

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-03-17 | AI Assistant | Initial specification covering embedding quality, chunking quality, ingestion throughput, incremental correctness, storage efficiency, and model comparison |

---

## 1. Scope & Definitions

### 1.1 Problem Statement

The ingestion pipeline transforms documents into vector embeddings, but there is currently no systematic way to measure whether the output is good. Chunking decisions, embedding quality, and ingestion throughput are unobserved — failures are only discovered downstream when retrieval quality degrades. Specific gaps:

1. **Embedding quality is unmeasured.** A model upgrade or configuration change could silently degrade semantic similarity accuracy, but there is no evaluation harness to detect it before production traffic is affected.
2. **Chunking quality is assumed, not verified.** Bad chunk boundaries (splitting a table across two chunks, or merging unrelated sections) degrade retrieval precision, but boundary accuracy and information preservation are not tracked.
3. **Throughput has no baseline.** There are no benchmarks for documents/min by format or size, making capacity planning guesswork and bottleneck identification manual.
4. **Re-ingestion correctness is untested at scale.** Idempotency (FR-1407) and cleanup correctness (FR-1404, FR-1405) are specified but not continuously validated.
5. **Storage growth is unmonitored.** Vector count, index size, and deduplication rates are not tracked, preventing capacity planning.
6. **Model comparison has no harness.** Evaluating alternative embedding models requires ad hoc scripts with no standardized A/B methodology.

### 1.2 Scope

This specification defines requirements for **measuring and validating ingestion output quality, throughput, and operational correctness**. The boundary is:

- **Entry point:** Ingestion pipeline produces chunks, embeddings, and metadata.
- **Exit point:** Quality and performance metrics are emitted, evaluated against thresholds, and used in release decisions.

**In scope:**

- Embedding quality evaluation (semantic similarity, cross-lingual, drift detection)
- Chunking quality metrics (coherence, boundary accuracy, information preservation)
- Ingestion throughput benchmarking (stage timing, bottleneck identification)
- Re-ingestion correctness validation (idempotency, orphan detection)
- Storage efficiency monitoring (vector density, deduplication, capacity planning)
- Model comparison harness (A/B embedding model evaluation)

### 1.2.1 Current Implementation Status (2026-03-17)

- No ingestion performance evaluation harness exists.
- Quality validation node (FR-1100) performs per-chunk scoring but does not aggregate fleet-level metrics.
- Re-ingestion has manifest-based cleanup (FR-1400 series) but no continuous correctness verification.

### 1.3 Terminology

| Term | Definition |
|------|-----------|
| **Chunk Coherence** | Measure of whether a chunk contains a single logical topic or concept, versus merging unrelated content |
| **Boundary Accuracy** | Whether chunk split points align with natural document structure (section breaks, paragraph boundaries) versus splitting mid-sentence or mid-table |
| **Information Preservation** | Whether all source content survives the chunking and enrichment pipeline without data loss, truncation, or semantic distortion |
| **Embedding Drift** | Change in embedding space geometry between model versions or configuration changes, measured by alignment of known-similar and known-dissimilar pairs |
| **Orphaned Vector** | A vector in the store that has no corresponding entry in the ingestion manifest, typically from incomplete cleanup during re-ingestion |
| **Gold Set** | A curated, versioned dataset with known-correct labels used for offline evaluation |
| **Recall@k** | Fraction of relevant items found in the top-k retrieved results |
| **nDCG@k** | Normalized Discounted Cumulative Gain — measures ranking quality, rewarding relevant items appearing earlier in results |
| **Throughput Envelope** | Documented ingestion capacity (documents/min) for each document format under standard hardware |

### 1.4 Requirement Priority Levels

This specification uses the key words defined in [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119) to indicate requirement levels:

| Keyword | Meaning |
|---------|---------|
| **MUST** / **SHALL** | Absolute requirement. The system cannot be considered conformant without implementing this. |
| **SHOULD** / **RECOMMENDED** | There may be valid reasons to omit this in particular circumstances, but the full implications must be understood and carefully weighed. |
| **MAY** / **OPTIONAL** | Truly optional. The system is conformant whether or not this is implemented. |

### 1.5 Requirement Format

Requirements use REQ-xxx IDs grouped by section:

| Section | ID Range | Component |
|---------|----------|-----------|
| 3 | REQ-1xx | Embedding Quality |
| 4 | REQ-2xx | Chunking Quality |
| 5 | REQ-3xx | Ingestion Throughput |
| 6 | REQ-4xx | Incremental Correctness |
| 7 | REQ-5xx | Storage Efficiency |
| 8 | REQ-6xx | Model Comparison |
| 9 | REQ-9xx | Non-Functional Requirements |

### 1.6 Assumptions & Constraints

| ID | Assumption / Constraint | Impact if Violated |
|----|------------------------|--------------------|
| A-1 | The 13-node ingestion pipeline (INGESTION_PIPELINE_SPEC.md) is the system under evaluation | Metrics must be redesigned for a different pipeline topology |
| A-2 | BGE-M3 is the current embedding model and BGE-reranker-v2-m3 the current reranker | Gold set baselines and drift thresholds are model-specific and must be recalibrated |
| A-3 | Weaviate is the vector store with hybrid search (vector + BM25) | Storage efficiency metrics and orphan detection queries are Weaviate-specific |
| A-4 | A representative evaluation corpus can be maintained for the target domain | Quality metric confidence degrades without stable benchmark coverage |
| A-5 | Stage-level timing instrumentation can be added to pipeline nodes | Throughput bottleneck identification requires per-node telemetry |
| A-6 | LiteLLM provides provider-agnostic model access for LLM-dependent evaluation steps | Evaluation harness portability depends on LiteLLM abstraction |

### 1.7 Design Principles

| Principle | Description |
|-----------|-------------|
| **Measure Before Ship** | Embedding model, chunking config, or pipeline changes require benchmark evidence before production deployment |
| **Left-Side Quality Gate** | Ingestion quality problems must be caught at ingestion time, not discovered via retrieval degradation |
| **Regression over Absolutes** | Relative change detection (did quality drop?) is more actionable than absolute thresholds alone |
| **Automate over Audit** | Quality checks must run automatically in CI/CD, not depend on manual review |
| **Representative over Exhaustive** | Evaluation datasets should cover high-risk scenarios (domain ambiguity, complex tables, cross-references) rather than attempting full corpus coverage |

### 1.8 Out of Scope

The following are explicitly **not covered** by this specification:

- Retrieval-side performance (latency controls, query evaluation, load testing) — see `RAG_RETRIEVAL_PERFORMANCE_SPEC.md`
- Pipeline functional requirements (what each node does) — see `INGESTION_PIPELINE_SPEC.md`
- Re-ingestion and configuration behavior — see `INGESTION_PLATFORM_SPEC.md`
- Generation quality (answer faithfulness, hallucination rate)
- Cost tracking and billing (LLM cost per ingestion run)
- End-to-end query-to-answer latency

---

## 2. System Overview

### 2.1 Architecture Diagram

```
Ingestion Pipeline Output (chunks, embeddings, metadata)
    │
    ▼
┌──────────────────────────────────────┐
│ [1] EMBEDDING QUALITY EVALUATION     │
│     Semantic similarity, drift,      │
│     cross-lingual accuracy           │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│ [2] CHUNKING QUALITY EVALUATION      │
│     Coherence, boundary accuracy,    │
│     information preservation         │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│ [3] THROUGHPUT BENCHMARKING          │
│     Stage timing, bottleneck ID,     │
│     format-specific throughput       │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│ [4] INCREMENTAL CORRECTNESS          │
│     Idempotency, orphan detection,   │
│     manifest reconciliation          │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│ [5] STORAGE EFFICIENCY MONITORING    │
│     Vector density, dedup rate,      │
│     index growth, capacity forecast  │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│ [6] MODEL COMPARISON HARNESS         │
│     A/B evaluation, retrieval-side   │
│     quality impact, migration gates  │
└──────────────────────────────────────┘
```

### 2.2 Data Flow Summary

| Stage | Input | Output |
|-------|-------|--------|
| Embedding Quality Evaluation | Embeddings + gold similarity pairs | Similarity accuracy, drift score, cross-lingual recall |
| Chunking Quality Evaluation | Chunks + source documents + gold boundary annotations | Coherence score, boundary accuracy, preservation rate |
| Throughput Benchmarking | Pipeline execution logs + stage timings | Documents/min by format, stage latency breakdown, bottleneck report |
| Incremental Correctness | Manifest state + vector store state + re-ingestion logs | Idempotency pass/fail, orphan count, cleanup completeness |
| Storage Efficiency Monitoring | Vector store metrics + manifest | Vectors/doc ratio, dedup rate, index size trend, capacity forecast |
| Model Comparison Harness | Evaluation corpus + candidate model embeddings | Recall@k delta, nDCG@k delta, migration recommendation |

---

## 3. Embedding Quality

> **REQ-101** | Priority: MUST
> **Description:** The system MUST maintain a gold evaluation set of semantically similar and dissimilar document pairs, representative of the target engineering domain.
> **Rationale:** Embedding quality cannot be measured without ground truth. Ad hoc evaluation misses domain-specific failure modes (e.g., "clock domain" meaning different things in DFT vs physical design contexts).
> **Acceptance Criteria:** Gold set includes a minimum of 50 similar pairs and 50 dissimilar pairs across at least 3 domain categories. The dataset is versioned and stored alongside evaluation tooling.

> **REQ-102** | Priority: MUST
> **Description:** The system MUST compute semantic similarity accuracy on the gold set, measuring whether the embedding model ranks known-similar pairs above known-dissimilar pairs.
> **Rationale:** This is the fundamental quality metric — if the model cannot distinguish similar from dissimilar content in the target domain, all downstream retrieval is compromised.
> **Acceptance Criteria:** Evaluation job produces a similarity discrimination score (e.g., AUC-ROC on similarity ranking). Score is compared against the configured baseline threshold.

> **REQ-103** | Priority: SHOULD
> **Description:** The system SHOULD evaluate cross-lingual retrieval quality when the corpus contains documents in multiple languages.
> **Rationale:** BGE-M3 supports multilingual embeddings, but cross-lingual accuracy may degrade for domain-specific terminology that lacks training coverage.
> **Acceptance Criteria:** If the gold set includes cross-lingual pairs, the evaluation job produces a separate cross-lingual similarity score. Degradation below threshold is flagged.

> **REQ-104** | Priority: MUST
> **Description:** The system MUST detect embedding drift when the embedding model version, configuration, or fine-tuning state changes.
> **Rationale:** A model upgrade that improves general benchmarks can silently degrade domain-specific accuracy. Drift detection catches this before production traffic is affected.
> **Acceptance Criteria:** Given two embedding model versions, the drift evaluation computes alignment shift on the gold set and reports whether the change exceeds the configured drift tolerance. Drift exceeding tolerance blocks deployment unless explicitly overridden.

> **REQ-105** | Priority: MUST
> **Description:** The system MUST enforce a regression gate in CI/CD that blocks embedding model or configuration changes when gold set quality metrics degrade beyond configured thresholds.
> **Rationale:** Un-gated changes can silently degrade embedding quality. The retrieval performance spec (REQ-203) gates retrieval-side changes; this gates the ingestion-side equivalently.
> **Acceptance Criteria:** CI pipeline fails when embedding quality score drops below baseline minus tolerance. The gate is bypassable only with explicit override and audit log entry.

> **REQ-106** | Priority: SHOULD
> **Description:** The system SHOULD include scenario-based evaluation slices for domain-ambiguous terms, numerical specifications, and structurally complex content (tables, diagrams with captions).
> **Rationale:** Aggregate accuracy can mask critical failure modes. A model that handles prose well but fails on specification tables is dangerous in an engineering domain.
> **Acceptance Criteria:** Slice-level reports are generated per evaluation run. Slices include at minimum: domain-ambiguous terms, numerical content, and tabular content.

---

## 4. Chunking Quality

> **REQ-201** | Priority: MUST
> **Description:** The system MUST measure chunk coherence — the degree to which each chunk contains a single logical topic rather than merging unrelated content.
> **Rationale:** Incoherent chunks reduce retrieval precision: a chunk about both "clock tree synthesis" and "power grid analysis" will match queries for either topic but satisfy neither well.
> **Acceptance Criteria:** Coherence scoring is computed on a gold-annotated sample. The score is reported as a distribution (p50, p95) and compared against baseline.

> **REQ-202** | Priority: MUST
> **Description:** The system MUST measure chunk boundary accuracy — whether split points align with natural document structure (section breaks, paragraph boundaries, table boundaries) rather than splitting mid-sentence or mid-table.
> **Rationale:** Boundary errors cause information loss: a table split across two chunks loses row-column context, and a sentence split mid-clause becomes ambiguous.
> **Acceptance Criteria:** Given a gold set of documents with annotated ideal split points, the evaluation computes boundary alignment rate (fraction of actual boundaries within N characters of an ideal boundary). Rate is reported and compared against baseline.

> **REQ-203** | Priority: MUST
> **Description:** The system MUST measure information preservation rate — whether all source content survives the chunking and enrichment pipeline without data loss or truncation.
> **Rationale:** The ingestion pipeline specification requires "content restructuring SHALL NOT summarise or remove information" (Design Principle: context preservation over compression). This metric validates that invariant.
> **Acceptance Criteria:** Given a source document with known character count and content tokens, the evaluation verifies that the union of all chunks reconstructs to within a configured tolerance of the original content. Missing content is flagged with location in the source document.

> **REQ-204** | Priority: MUST
> **Description:** The system MUST track chunk size distribution statistics (min, max, mean, median, p95, standard deviation) per ingestion run and per document format.
> **Rationale:** Abnormal chunk size distributions indicate configuration problems or format-specific parsing failures. Extremely short chunks waste embedding compute; extremely long chunks exceed model input limits.
> **Acceptance Criteria:** Distribution statistics are emitted per ingestion run. Chunks below minimum threshold or above maximum threshold are counted and flagged. Distribution is broken down by source document format.

> **REQ-205** | Priority: SHOULD
> **Description:** The system SHOULD detect and report chunks that contain mixed structural content (e.g., a chunk that starts as a paragraph but ends with a table row fragment).
> **Rationale:** Mixed-structure chunks are a specific failure mode of boundary detection. They are harder to embed accurately and produce noisy retrieval results.
> **Acceptance Criteria:** Structural analysis heuristic identifies chunks with mixed content types. Count and percentage of mixed-structure chunks are reported per run.

---

## 5. Ingestion Throughput

> **REQ-301** | Priority: MUST
> **Description:** The system MUST emit structured stage-level timing telemetry for every pipeline node execution, including node name, duration, document format, and document size.
> **Rationale:** Throughput optimization requires identifying which nodes are bottlenecks and whether bottlenecks are format-specific (e.g., Docling is slow on complex PDFs but fast on Markdown).
> **Acceptance Criteria:** Every ingestion run produces per-node timing records. Records include node name, wall-clock duration in milliseconds, input document format, and input document page count or byte size.

> **REQ-302** | Priority: MUST
> **Description:** The system MUST compute and report aggregate ingestion throughput in documents/minute and pages/minute, broken down by document format.
> **Rationale:** Capacity planning requires knowing how fast the pipeline processes each document type under standard hardware conditions.
> **Acceptance Criteria:** Throughput report is generated per batch ingestion run. Report includes per-format breakdown and overall aggregate. Results are stored for trend comparison.

> **REQ-303** | Priority: MUST
> **Description:** The system MUST identify throughput bottleneck nodes — the nodes consuming the highest fraction of total pipeline wall-clock time.
> **Rationale:** Optimization effort should target the most expensive nodes. Without bottleneck identification, engineers may optimise low-impact stages.
> **Acceptance Criteria:** Throughput report ranks nodes by cumulative wall-clock time percentage. Nodes consuming more than a configured threshold (e.g., >30% of total time) are flagged as bottlenecks.

> **REQ-304** | Priority: MUST
> **Description:** The system MUST define standardized throughput benchmark profiles for each supported document format, including representative document sizes and complexity levels.
> **Rationale:** Throughput claims must be reproducible. Ad hoc benchmarking with different documents produces incomparable results.
> **Acceptance Criteria:** Benchmark profiles are versioned and include at minimum: small PDF (<10 pages), large PDF (50-100 pages), complex PDF (tables + images), DOCX, Markdown, and plain text. Profiles specify expected document characteristics.

> **REQ-305** | Priority: SHOULD
> **Description:** The system SHOULD track throughput trend history and annotate runs with configuration metadata (model version, chunking config, hardware spec).
> **Rationale:** Throughput regressions from configuration or dependency changes must be detectable via historical comparison.
> **Acceptance Criteria:** Benchmark history is stored with run metadata. Throughput changes beyond configured tolerance between consecutive runs are flagged.

> **REQ-306** | Priority: SHOULD
> **Description:** The system SHOULD measure LLM-dependent node throughput separately from deterministic node throughput, since LLM latency is provider-dependent and variable.
> **Rationale:** LLM-dependent stages (document refactoring, metadata generation, KG extraction) have fundamentally different latency profiles from deterministic stages (text cleaning, chunking). Mixing them in aggregate metrics obscures actionable bottleneck information.
> **Acceptance Criteria:** Throughput reports distinguish LLM-dependent nodes from deterministic nodes. LLM-dependent node timings include provider latency breakdown where available (via LiteLLM metrics).

---

## 6. Incremental Correctness

> **REQ-401** | Priority: MUST
> **Description:** The system MUST validate re-ingestion idempotency: re-ingesting an unchanged document MUST produce no new data, no deleted data, and no side effects.
> **Rationale:** FR-1407 specifies idempotency as a requirement. This metric continuously validates that invariant rather than relying on one-time testing.
> **Acceptance Criteria:** Idempotency validation ingests a document, re-ingests the same unchanged document, and verifies: zero new chunks, zero deleted chunks, zero new KG triples, zero deleted KG triples, zero LLM calls beyond hash comparison. Any deviation is a failure.

> **REQ-402** | Priority: MUST
> **Description:** The system MUST detect orphaned vectors — vectors in the store that have no corresponding entry in the ingestion manifest.
> **Rationale:** Orphaned vectors from incomplete cleanup (FR-1404, FR-1405) waste storage, pollute search results with stale content, and can cause contradictory retrieval results (e.g., returning both old and new versions of a specification).
> **Acceptance Criteria:** Orphan detection job reconciles vector store state against ingestion manifest. Orphaned vectors are counted and reported with source document identity. Non-zero orphan count triggers an alert.

> **REQ-403** | Priority: MUST
> **Description:** The system MUST validate cleanup completeness after re-ingestion of a changed document: the vector store MUST contain only chunks from the new version, with zero residual chunks from the previous version.
> **Rationale:** FR-1404 requires full cleanup before new data insertion. This metric validates that the cleanup implementation actually removes all old data.
> **Acceptance Criteria:** After re-ingesting a changed document, validation queries the vector store for chunks matching the old content hash. Zero matches is a pass. Any matches indicate incomplete cleanup.

> **REQ-404** | Priority: SHOULD
> **Description:** The system SHOULD run incremental correctness validation as a scheduled job (not only on-demand), to detect drift from external vector store mutations or incomplete recovery from failures.
> **Rationale:** Orphans can accumulate from partial failures, manual interventions, or vector store compaction issues. Periodic reconciliation catches problems before they affect retrieval quality.
> **Acceptance Criteria:** Scheduled reconciliation job runs at configured interval. Results are logged with timestamp, orphan count, and manifest-vs-store delta. Alert fires if orphan count exceeds threshold.

> **REQ-405** | Priority: MUST
> **Description:** The system MUST validate that the "delete and reinsert" re-ingestion strategy (FR-1408) produces output equivalent to fresh ingestion: the same document ingested fresh and re-ingested with "delete and reinsert" MUST produce identical chunk content and embedding vectors.
> **Rationale:** If "delete and reinsert" produces different output than fresh ingestion, the re-ingestion strategy is not trustworthy and engineers cannot rely on it for pipeline configuration changes.
> **Acceptance Criteria:** Given a document ingested fresh and the same document re-ingested with "delete_and_reinsert" strategy, chunk content and embedding vectors are compared. Byte-identical chunk content and vector similarity above 0.9999 (accounting for floating-point non-determinism) is a pass.

---

## 7. Storage Efficiency

> **REQ-501** | Priority: MUST
> **Description:** The system MUST track and report vectors-per-document ratio, broken down by document format and size class.
> **Rationale:** Abnormal vector density indicates chunking configuration problems. Too many vectors per document wastes storage and slows search; too few indicates under-chunking and lost granularity.
> **Acceptance Criteria:** Per-run report includes vectors/document ratio with breakdown by format. Ratios outside configured min/max bounds are flagged.

> **REQ-502** | Priority: MUST
> **Description:** The system MUST track vector store index size over time and report growth rate.
> **Rationale:** Unmonitored index growth leads to surprise storage exhaustion and performance degradation (HNSW search time increases with index size).
> **Acceptance Criteria:** Index size is recorded after each ingestion run. Growth rate (bytes/document, bytes/week) is computed and stored for trend analysis. Growth exceeding forecast tolerance triggers a capacity alert.

> **REQ-503** | Priority: SHOULD
> **Description:** The system SHOULD measure and report chunk deduplication rate — the fraction of chunks that are near-duplicates of existing chunks in the store.
> **Rationale:** High deduplication rates indicate either redundant source documents or a chunking strategy that produces overlapping content. Both waste storage and can bias retrieval toward over-represented content.
> **Acceptance Criteria:** Deduplication analysis compares new chunks against existing chunks using embedding similarity threshold. Near-duplicate count and percentage are reported per run.

> **REQ-504** | Priority: SHOULD
> **Description:** The system SHOULD provide storage capacity forecasting based on current growth rate and planned ingestion volume.
> **Rationale:** Proactive capacity planning prevents service disruption from storage exhaustion.
> **Acceptance Criteria:** Given current index size, growth rate, and projected document volume, the system produces a capacity forecast with estimated time-to-threshold. Forecast is updated after each ingestion run.

> **REQ-505** | Priority: MUST
> **Description:** The system MUST emit storage efficiency metrics to the observability stack (Prometheus/Grafana) for operational monitoring.
> **Rationale:** Storage metrics must be available in the same dashboards as retrieval and platform metrics for unified operational visibility.
> **Acceptance Criteria:** Prometheus metrics include: total vector count, index size bytes, vectors per document (gauge), orphan count (gauge). Grafana dashboard displays storage trends.

---

## 8. Model Comparison

> **REQ-601** | Priority: MUST
> **Description:** The system MUST provide a benchmark harness for evaluating alternative embedding models against the current production model using the same gold evaluation set and metrics.
> **Rationale:** Embedding model selection is a high-impact decision. Without standardized comparison, model changes are based on vendor benchmarks that may not reflect domain-specific performance.
> **Acceptance Criteria:** Benchmark harness accepts a model identifier, runs the gold evaluation set through both the candidate and production models, and produces a side-by-side comparison report with all metrics from sections 3 and 4.

> **REQ-602** | Priority: MUST
> **Description:** The system MUST evaluate candidate embedding models using end-to-end retrieval quality (recall@k, nDCG@k) on a retrieval evaluation set, not only embedding similarity metrics.
> **Rationale:** Embedding similarity accuracy does not directly predict retrieval quality. A model with slightly lower similarity scores but better retrieval ranking is preferable. This bridges the gap between ingestion-side and retrieval-side evaluation.
> **Acceptance Criteria:** Model comparison includes retrieval evaluation: candidate embeddings are loaded into a test vector store, and standardized retrieval queries are executed. Recall@k and nDCG@k are computed and compared against the production model baseline.

> **REQ-603** | Priority: SHOULD
> **Description:** The system SHOULD support parallel A/B evaluation where both production and candidate embeddings are stored and retrieval quality is compared on live-equivalent queries.
> **Rationale:** Offline evaluation with gold sets may not capture all real-world query patterns. A/B evaluation on representative queries provides higher-confidence model comparison.
> **Acceptance Criteria:** A/B harness ingests a test corpus with both models, runs a query set against both, and reports per-query and aggregate quality deltas.

> **REQ-604** | Priority: MUST
> **Description:** The system MUST define a model migration gate: minimum quality thresholds that a candidate model must meet or exceed before it can replace the production model.
> **Rationale:** Model migration without a quality gate risks silent degradation. The gate ensures that model changes are evidence-based.
> **Acceptance Criteria:** Migration gate checks: (1) embedding similarity accuracy >= production baseline, (2) retrieval recall@k >= production baseline, (3) no slice-level regression beyond tolerance on any evaluation slice. Gate failure blocks migration with a detailed report.

> **REQ-605** | Priority: SHOULD
> **Description:** The system SHOULD report model comparison results with per-slice breakdowns (domain-ambiguous, numerical, tabular, cross-lingual) in addition to aggregate scores.
> **Rationale:** A candidate model may improve aggregate scores while regressing on critical slices. Per-slice visibility prevents trading overall improvement for domain-specific degradation.
> **Acceptance Criteria:** Comparison report includes per-slice scores for all configured evaluation slices. Slice-level regressions are highlighted even when aggregate scores improve.

> **REQ-606** | Priority: SHOULD
> **Description:** The system SHOULD track ingestion throughput and resource consumption (memory, GPU utilisation) differences between candidate and production models.
> **Rationale:** A quality-equivalent model that ingests twice as fast or uses half the memory is preferable. Model comparison should consider operational cost, not only quality.
> **Acceptance Criteria:** Comparison report includes throughput (documents/min) and peak resource consumption for both models on the standard benchmark profiles.

---

## 9. Non-Functional Requirements

> **REQ-901** | Priority: SHOULD
> **Description:** The system SHOULD meet the following evaluation harness performance targets:
>
> | Evaluation Job | Target |
> |----------------|--------|
> | Embedding quality evaluation (gold set) | < 5 minutes for 100 pair gold set |
> | Chunking quality evaluation (annotated sample) | < 10 minutes for 50 document sample |
> | Orphan detection (full reconciliation) | < 15 minutes for 100K vector store |
> | Model comparison (full pipeline) | < 30 minutes for standard benchmark profiles |
>
> **Rationale:** Evaluation jobs that take too long will be skipped or run infrequently, reducing their value as quality gates.
> **Acceptance Criteria:** Evaluation jobs complete within target durations on standard hardware. Jobs exceeding targets log a warning.

> **REQ-902** | Priority: MUST
> **Description:** The system MUST degrade gracefully when evaluation dependencies are unavailable:
>
> | Component Unavailable | Degraded Behavior |
> |----------------------|-------------------|
> | Gold evaluation set | Skip quality evaluation, log warning, mark release gates as non-passing |
> | Vector store (for orphan detection) | Skip orphan detection, log warning, continue ingestion |
> | Observability stack (Prometheus) | Buffer metrics locally, retry emission on reconnect |
>
> The system MUST NOT block ingestion pipeline execution due to evaluation harness failures.
> **Rationale:** The evaluation layer is an observer, not a participant in the ingestion data path. Evaluation failures must not cause data processing outages.
> **Acceptance Criteria:** Failure injection tests verify that each degraded path produces appropriate warnings without blocking ingestion.

> **REQ-903** | Priority: MUST
> **Description:** All evaluation thresholds, gold set paths, benchmark profiles, alert triggers, and scheduling intervals MUST be externalized to versioned configuration.
> **Rationale:** Quality thresholds evolve as the domain corpus grows and model capabilities change. Configuration changes must not require code modifications.
> **Acceptance Criteria:** Configuration changes apply on restart or controlled reload. All configurable parameters have documented defaults and valid ranges.

> **REQ-904** | Priority: MUST
> **Description:** The system MUST track evaluation metric trend history with run metadata (pipeline version, model version, config hash, corpus snapshot version).
> **Rationale:** Root-cause analysis of quality regressions requires correlating metric changes with specific pipeline or model changes.
> **Acceptance Criteria:** Historical evaluation results are stored with full metadata. Run-to-run comparison is possible by any metadata dimension.

---

## 10. System-Level Acceptance Criteria

| Criterion | Threshold | Related Requirements |
|-----------|-----------|---------------------|
| Embedding quality regression detection | Drift exceeding tolerance blocks deployment | REQ-104, REQ-105 |
| Chunking quality observability | Coherence + boundary + preservation metrics emitted per run | REQ-201, REQ-202, REQ-203 |
| Throughput baseline established | Per-format throughput published for all supported formats | REQ-302, REQ-304 |
| Re-ingestion correctness | Zero orphans after clean re-ingestion; idempotency validated | REQ-401, REQ-402, REQ-403 |
| Storage capacity forecasting | Growth rate tracked and capacity alert configured | REQ-502, REQ-505 |
| Model comparison evidence | No model migration without quality gate pass | REQ-601, REQ-604 |

---

## 11. Requirements Traceability Matrix

| REQ ID | Section | Priority | Component |
|--------|---------|----------|-----------|
| REQ-101 | 3 | MUST | Embedding Quality |
| REQ-102 | 3 | MUST | Embedding Quality |
| REQ-103 | 3 | SHOULD | Embedding Quality |
| REQ-104 | 3 | MUST | Embedding Quality |
| REQ-105 | 3 | MUST | Embedding Quality |
| REQ-106 | 3 | SHOULD | Embedding Quality |
| REQ-201 | 4 | MUST | Chunking Quality |
| REQ-202 | 4 | MUST | Chunking Quality |
| REQ-203 | 4 | MUST | Chunking Quality |
| REQ-204 | 4 | MUST | Chunking Quality |
| REQ-205 | 4 | SHOULD | Chunking Quality |
| REQ-301 | 5 | MUST | Ingestion Throughput |
| REQ-302 | 5 | MUST | Ingestion Throughput |
| REQ-303 | 5 | MUST | Ingestion Throughput |
| REQ-304 | 5 | MUST | Ingestion Throughput |
| REQ-305 | 5 | SHOULD | Ingestion Throughput |
| REQ-306 | 5 | SHOULD | Ingestion Throughput |
| REQ-401 | 6 | MUST | Incremental Correctness |
| REQ-402 | 6 | MUST | Incremental Correctness |
| REQ-403 | 6 | MUST | Incremental Correctness |
| REQ-404 | 6 | SHOULD | Incremental Correctness |
| REQ-405 | 6 | MUST | Incremental Correctness |
| REQ-501 | 7 | MUST | Storage Efficiency |
| REQ-502 | 7 | MUST | Storage Efficiency |
| REQ-503 | 7 | SHOULD | Storage Efficiency |
| REQ-504 | 7 | SHOULD | Storage Efficiency |
| REQ-505 | 7 | MUST | Storage Efficiency |
| REQ-601 | 8 | MUST | Model Comparison |
| REQ-602 | 8 | MUST | Model Comparison |
| REQ-603 | 8 | SHOULD | Model Comparison |
| REQ-604 | 8 | MUST | Model Comparison |
| REQ-605 | 8 | SHOULD | Model Comparison |
| REQ-606 | 8 | SHOULD | Model Comparison |
| REQ-901 | 9 | SHOULD | Non-Functional |
| REQ-902 | 9 | MUST | Non-Functional |
| REQ-903 | 9 | MUST | Non-Functional |
| REQ-904 | 9 | MUST | Non-Functional |

**Total Requirements: 37**
- MUST: 24
- SHOULD: 13
- MAY: 0

---

## Appendix A. Document References

| Document | Location | Relationship |
|----------|----------|-------------|
| Ingestion Pipeline Spec | `docs/ingestion/INGESTION_PIPELINE_SPEC.md` | Defines the 13-node pipeline whose output this spec evaluates |
| Ingestion Platform Spec | `docs/ingestion/INGESTION_PLATFORM_SPEC.md` | Defines re-ingestion correctness requirements (FR-1400 series) validated by section 6 |
| Retrieval Performance Spec | `docs/performance/RAG_RETRIEVAL_PERFORMANCE_SPEC.md` | Companion spec covering retrieval-side performance; model comparison (section 8) bridges both specs |
| Operations Platform Spec | `docs/operations/OPERATIONS_PLATFORM_SPEC.md` | Defines observability infrastructure that storage efficiency metrics (section 7) integrate with |

## Appendix B. Implementation Phasing

### Phase 1 — Quality Metrics Baseline (2-3 weeks)

**Objective:** Establish embedding and chunking quality measurement with regression gates.

| Scope | Requirements |
|-------|-------------|
| Gold evaluation set + embedding quality metrics | REQ-101, REQ-102, REQ-103, REQ-106 |
| Embedding drift detection + CI gate | REQ-104, REQ-105 |
| Chunking quality metrics | REQ-201, REQ-202, REQ-203, REQ-204, REQ-205 |
| Configuration externalization | REQ-903 |

**Success criteria:** Pipeline and model changes trigger quality evaluation. Regressions block deployment.

### Phase 2 — Throughput Benchmarking (1-2 weeks)

**Objective:** Establish ingestion throughput baselines and bottleneck visibility.

| Scope | Requirements |
|-------|-------------|
| Stage-level timing telemetry | REQ-301 |
| Throughput reporting + benchmark profiles | REQ-302, REQ-303, REQ-304 |
| Throughput trend tracking | REQ-305, REQ-306 |

**Success criteria:** Per-format throughput baselines are published. Bottleneck nodes are identified.

### Phase 3 — Correctness & Storage (1-2 weeks)

**Objective:** Validate re-ingestion correctness and establish storage monitoring.

| Scope | Requirements |
|-------|-------------|
| Idempotency validation + orphan detection | REQ-401, REQ-402, REQ-403, REQ-405 |
| Scheduled reconciliation | REQ-404 |
| Storage efficiency metrics + Prometheus integration | REQ-501, REQ-502, REQ-503, REQ-504, REQ-505 |

**Success criteria:** Zero orphans after clean re-ingestion. Storage growth is tracked and alerted.

### Phase 4 — Model Comparison Harness (2-3 weeks)

**Objective:** Enable evidence-based embedding model evaluation and migration.

| Scope | Requirements |
|-------|-------------|
| Benchmark harness + retrieval evaluation | REQ-601, REQ-602, REQ-603 |
| Migration gate + reporting | REQ-604, REQ-605, REQ-606 |
| Non-functional targets + degraded modes + trend history | REQ-901, REQ-902, REQ-904 |

**Success criteria:** Model changes cannot proceed without benchmark evidence. A/B comparison is standardized.
