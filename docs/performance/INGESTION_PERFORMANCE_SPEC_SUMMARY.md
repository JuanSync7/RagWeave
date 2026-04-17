# Ingestion Performance and Validation Spec Summary

## 1) Generic System Overview

### Purpose

A document ingestion pipeline converts raw source documents into indexed vector representations, but the quality of that conversion is often invisible until retrieval fails. This system — the ingestion performance and validation layer — exists to make quality observable at the point it is produced. It measures whether the pipeline's output (chunks, embeddings, and their metadata) is good enough to serve accurate retrieval before any query ever runs. Without this layer, embedding degradation from model upgrades, chunking failures from format-specific edge cases, and storage drift from incomplete re-ingestion operations go undetected until retrieval quality regresses in production.

### How It Works

The validation layer operates as a post-ingestion observer that evaluates pipeline output across six dimensions, each running as a distinct evaluation job.

The **embedding quality job** measures whether the embedding model correctly captures semantic relationships in the target domain. It does this by comparing model output against a curated dataset of known-similar and known-dissimilar content pairs. It also evaluates accuracy on content spanning multiple languages and detects geometric drift in the embedding space when the model is upgraded or reconfigured. When a change causes metrics to fall below threshold, the job raises a regression signal that blocks deployment.

The **chunking quality job** evaluates whether the segmentation of documents into retrieval units is structurally sound. It checks that each chunk covers a single coherent topic, that split points align with natural document boundaries rather than cutting mid-sentence or mid-table, and that no content from the source document is lost or distorted during transformation. Distribution statistics on chunk sizes are also tracked per document format.

The **throughput benchmarking job** instruments each processing stage individually, measuring how long each stage takes per document format and size. It aggregates these timings into per-format ingestion rates and identifies which stages consume the most processing time, giving engineers actionable data for optimization.

The **incremental correctness job** validates the behavior of the pipeline when a document is re-ingested. It checks that re-ingesting an unchanged document produces no side effects, that re-ingesting a changed document fully removes old data, and that no residual content from incomplete cleanup operations lingers in the index.

The **storage efficiency job** monitors the density and growth of the indexed representation over time. It tracks how many indexed units are produced per document, how quickly the index grows, and whether near-duplicate content from repeated or overlapping source documents is accumulating.

The **model comparison harness** provides a structured evaluation path for assessing alternative embedding models. It runs both the candidate and production models against the same evaluation corpus and computes quality and throughput metrics side by side, enforcing a migration gate that blocks model changes without evidence of equivalent or better performance.

All jobs emit metrics to the observability stack for operational dashboarding and trend analysis.

### Tunable Knobs

Several dimensions of the validation layer's behavior are configurable. **Regression thresholds** control how much embedding quality or chunking quality can decline before a deployment is blocked — operators can tune sensitivity based on domain tolerance for quality variance. **Drift tolerance** governs how much change in the embedding space geometry is acceptable across model versions before a flag is raised. **Evaluation dataset configuration** allows engineers to specify the location and version of the gold evaluation corpus, enabling corpus rotation as the domain evolves. **Scheduling intervals** for the incremental correctness reconciliation job are configurable, allowing more or less frequent checks depending on ingestion volume and operational risk appetite. **Bottleneck thresholds** define what fraction of total pipeline time a single stage must consume before it is highlighted as a bottleneck. **Benchmark profiles** for throughput testing are versioned and configurable, specifying the representative documents used for reproducible benchmarking.

### Design Rationale

The system is shaped by two core beliefs. First, quality problems caught at ingestion are far cheaper to remediate than quality problems discovered via retrieval degradation — by the time a retrieval regression is observed, the source may be a weeks-old pipeline change with confounding factors. Second, relative change detection (did quality drop from the last run?) is more actionable than absolute threshold monitoring alone, because acceptable absolute thresholds shift over time as models and corpora evolve.

The evaluation layer is intentionally an observer rather than a participant in the ingestion data path. This means evaluation failures must not block data processing — they raise signals and gate deployment decisions, but they do not halt ingestion. This separation prevents the evaluation harness from becoming a source of availability risk.

The emphasis on scenario-based evaluation slices (rather than aggregate accuracy alone) reflects domain risk: a model that handles narrative prose well but fails on specification tables or domain-ambiguous terms can look healthy in aggregate while causing targeted retrieval failures on the most critical content.

### Boundary Semantics

**Entry point:** The validation layer receives pipeline output — chunks, embeddings, and ingestion metadata — after the ingestion pipeline has completed processing a document or batch. It does not participate in or modify the ingestion data path itself.

**Exit point:** The layer produces evaluation reports, metric time series emitted to the observability stack, regression signals for CI/CD gates, and migration recommendations for model comparison. These outputs are consumed by release tooling, operational dashboards, and engineering review workflows.

**State maintained:** Gold evaluation datasets, benchmark profiles, historical metric runs with pipeline and model version metadata, and incremental correctness reconciliation state.

**Responsibility boundary:** This layer evaluates ingestion output quality. Retrieval-side performance (query latency, ranking quality under load), generation quality, and end-to-end answer faithfulness are out of scope and covered by companion specifications.

---

## 2) Header

| Field | Value |
|-------|-------|
| **Companion Spec** | `docs/performance/INGESTION_PERFORMANCE_SPEC.md` |
| **Version** | 1.0 |
| **Status** | Draft |
| **Document Type** | Spec Summary (Layer 2) |
| **See Also** | `INGESTION_PIPELINE_SPEC.md`, `INGESTION_PLATFORM_SPEC.md`, `RAG_RETRIEVAL_PERFORMANCE_SPEC.md` |

**Purpose of this summary:** Provides a concise digest of the companion spec for technical stakeholders who need the shape and intent of the ingestion performance and validation requirements without reading every requirement. It does not replace the spec.

---

## 3) Scope and Boundaries

**Entry point:** Ingestion pipeline produces chunks, embeddings, and metadata.

**Exit point:** Quality and performance metrics are emitted, evaluated against thresholds, and used in release decisions.

**In scope:**

- Embedding quality evaluation (semantic similarity, cross-lingual accuracy, drift detection)
- Chunking quality metrics (coherence, boundary accuracy, information preservation, size distribution)
- Ingestion throughput benchmarking (stage timing, bottleneck identification, format-specific baselines)
- Re-ingestion correctness validation (idempotency, orphan detection, cleanup completeness)
- Storage efficiency monitoring (vector density, deduplication, index growth, capacity forecasting)
- Model comparison harness (A/B embedding model evaluation, migration gates)

**Out of scope:**

- Retrieval-side performance (latency controls, query evaluation, load testing)
- Pipeline functional requirements (what each node does)
- Re-ingestion and configuration behavior (platform-level concerns)
- Generation quality (answer faithfulness, hallucination rate)
- Cost tracking and billing (LLM cost per ingestion run)
- End-to-end query-to-answer latency

---

## 4) Architecture / Pipeline Overview

The validation layer is composed of six sequentially documented evaluation stages. In practice these may run independently or in combination depending on trigger context (CI gate, scheduled job, on-demand benchmark).

```
Ingestion Pipeline Output (chunks, embeddings, metadata)
         │
         ▼
┌─────────────────────────────────┐
│ [1] Embedding Quality           │ ← similarity accuracy, drift, cross-lingual
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│ [2] Chunking Quality            │ ← coherence, boundary accuracy, preservation
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│ [3] Throughput Benchmarking     │ ← stage timing, bottleneck ID, format rates
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│ [4] Incremental Correctness     │ ← idempotency, orphan detection, cleanup
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│ [5] Storage Efficiency          │ ← vector density, dedup, growth, forecast
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│ [6] Model Comparison Harness    │ ← A/B eval, migration gate          [opt]
└─────────────────────────────────┘
         │
         ▼
  Metrics / Reports / CI Gate Signals
```

---

## 5) Requirement Framework

- **ID convention:** `REQ-xxx` — three-digit numeric suffix grouped by section
- **Priority keywords:** RFC 2119 — **MUST/SHALL** (absolute), **SHOULD/RECOMMENDED** (conditional), **MAY/OPTIONAL** (truly optional)
- **Format:** Each requirement includes description, rationale, and acceptance criteria

| Section | ID Range | Domain |
|---------|----------|--------|
| 3 | REQ-1xx | Embedding Quality |
| 4 | REQ-2xx | Chunking Quality |
| 5 | REQ-3xx | Ingestion Throughput |
| 6 | REQ-4xx | Incremental Correctness |
| 7 | REQ-5xx | Storage Efficiency |
| 8 | REQ-6xx | Model Comparison |
| 9 | REQ-9xx | Non-Functional Requirements |

**Total requirements: 37** — 24 MUST, 13 SHOULD, 0 MAY.

---

## 6) Functional Requirement Domains

**Embedding Quality (REQ-1xx)** — Covers gold evaluation set maintenance, semantic similarity accuracy measurement, optional cross-lingual evaluation, drift detection on model changes, CI/CD regression gating, and scenario-based slice evaluation for domain-ambiguous and structurally complex content.

**Chunking Quality (REQ-2xx)** — Covers coherence scoring against gold annotations, boundary alignment accuracy against ideal split points, information preservation rate validation, chunk size distribution statistics per format, and detection of mixed-structure chunks.

**Ingestion Throughput (REQ-3xx)** — Covers per-node stage-level timing telemetry, aggregate throughput reporting in documents/min and pages/min by format, bottleneck node identification, standardized versioned benchmark profiles per format, throughput trend history, and separation of LLM-dependent from deterministic node timings.

**Incremental Correctness (REQ-4xx)** — Covers idempotency validation (re-ingesting unchanged documents produces zero side effects), orphan vector detection via manifest reconciliation, cleanup completeness verification after changed-document re-ingestion, scheduled periodic reconciliation, and equivalence validation between fresh ingestion and delete-and-reinsert re-ingestion.

**Storage Efficiency (REQ-5xx)** — Covers vectors-per-document ratio tracking by format and size class, index size growth rate monitoring, optional chunk deduplication rate reporting, optional capacity forecasting, and observability stack metric emission for operational dashboarding.

**Model Comparison (REQ-6xx)** — Covers standardized benchmark harness comparing candidate vs. production models, end-to-end retrieval quality evaluation (not only embedding similarity), optional parallel A/B evaluation on representative queries, a migration gate enforcing minimum quality thresholds before model promotion, per-slice comparison reports, and throughput/resource consumption comparison.

---

## 7) Non-Functional and Security Themes

**Performance targets** — Evaluation jobs have target completion durations to prevent them from being skipped or run infrequently in CI contexts. Jobs that exceed targets emit warnings.

**Graceful degradation** — The evaluation harness must not block ingestion when its own dependencies are unavailable. Each failure mode (missing gold set, unreachable vector store, unavailable observability stack) has a defined degraded behavior with appropriate warnings.

**Configuration externalization** — All thresholds, dataset paths, scheduling intervals, and benchmark profiles must be in versioned external configuration. No threshold values are hardcoded.

**Metric history and traceability** — Evaluation results are stored with full pipeline version, model version, config hash, and corpus snapshot metadata to support root-cause analysis of regressions.

---

## 8) Design Principles

| Principle | Summary |
|-----------|---------|
| **Measure Before Ship** | Embedding model, chunking config, or pipeline changes require benchmark evidence before production deployment |
| **Left-Side Quality Gate** | Ingestion quality problems must be caught at ingestion time, not discovered via retrieval degradation |
| **Regression over Absolutes** | Relative change detection is more actionable than absolute threshold monitoring alone |
| **Automate over Audit** | Quality checks must run automatically in CI/CD, not depend on manual review |
| **Representative over Exhaustive** | Evaluation datasets should cover high-risk scenarios rather than attempting full corpus coverage |

---

## 9) Key Decisions

- **Observer, not participant:** The validation layer explicitly does not participate in the ingestion data path. Evaluation failures raise signals but do not block data processing — only deployment gates and model migration decisions are blocked.
- **Gold set as ground truth:** Embedding and chunking quality are anchored to a curated, versioned evaluation dataset rather than relying on live-corpus heuristics. This trades coverage for reproducibility and domain specificity.
- **Slice-level evaluation required:** Aggregate accuracy metrics are insufficient. The spec requires per-slice breakdowns covering domain-ambiguous terms, numerical content, tabular content, and cross-lingual pairs to prevent aggregate improvements masking targeted regressions.
- **Retrieval quality bridges ingestion and retrieval evaluation:** Model comparison is not limited to embedding similarity metrics — it requires end-to-end retrieval quality measurement, bridging this spec to the retrieval performance spec.
- **Phased delivery in four phases:** Quality metrics baseline → throughput benchmarking → correctness and storage → model comparison harness.

---

## 10) Acceptance, Evaluation, and Feedback

The spec defines six system-level acceptance criteria:

| Area | Acceptance Signal |
|------|------------------|
| Embedding quality regression detection | Drift exceeding tolerance blocks deployment |
| Chunking quality observability | Coherence, boundary, and preservation metrics emitted per run |
| Throughput baseline | Per-format throughput published for all supported formats |
| Re-ingestion correctness | Zero orphans after clean re-ingestion; idempotency validated |
| Storage capacity forecasting | Growth rate tracked and capacity alert configured |
| Model comparison evidence | No model migration without quality gate pass |

No continuous feedback loop or human review framework is defined — evaluation is CI/CD-integrated and metric-driven.

---

## 11) External Dependencies

**Required:**

- Ingestion pipeline (the system under evaluation) — must be instrumented with per-node timing telemetry
- Gold evaluation dataset — curated, versioned; evaluation jobs cannot run without it
- Vector store — required for orphan detection and model comparison retrieval evaluation
- Observability stack — required for metric emission; degraded local buffering mode available on disconnect

**Optional:**

- LLM provider (via provider-agnostic abstraction layer) — required for LLM-dependent stage timing separation and evaluation steps that use language model scoring
- A/B test infrastructure — required only for parallel model comparison mode

**Downstream contracts:**

- CI/CD pipeline — consumes regression gate signals; must support blocking on failure output
- Operational dashboards — consume time-series metrics from the observability stack
- Release tooling — consumes model migration gate pass/fail reports

---

## 12) Companion Documents

| Document | Relationship |
|----------|-------------|
| `INGESTION_PIPELINE_SPEC.md` | Defines the 13-node pipeline whose output this spec evaluates |
| `INGESTION_PLATFORM_SPEC.md` | Defines re-ingestion correctness requirements validated by the incremental correctness section |
| `RAG_RETRIEVAL_PERFORMANCE_SPEC.md` | Companion retrieval-side performance spec; model comparison section bridges both specs |
| `OPERATIONS_PLATFORM_SPEC.md` | Defines observability infrastructure that storage efficiency metrics integrate with |

This summary (Layer 2) digests the companion spec (Layer 3). For full requirement text, rationale, and acceptance criteria, read the companion spec directly.

---

## 13) Sync Status

| Field | Value |
|-------|-------|
| **Spec version** | 1.0 |
| **Spec date** | 2026-03-17 |
| **Summary written** | 2026-04-10 |
| **Summary aligned to** | `INGESTION_PERFORMANCE_SPEC.md` v1.0 |
