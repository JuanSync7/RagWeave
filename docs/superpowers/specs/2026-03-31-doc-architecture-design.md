# Documentation Architecture — Design Spec

**Date:** 2026-03-31
**Status:** Approved (brainstormed and validated in conversation)
**Deliverable:** Update to `doc-authoring` skill (documentation skills router)

---

## 1. Problem Statement

The project's documentation suite has grown to include both generic pipeline specifications (describing what a stage does) and implementation-specific specifications (describing how a specific tool fulfills that contract). These currently coexist using three ad-hoc patterns:

1. **Parallel chains** (Document Processing + Docling Chunking) — two full doc chains side-by-side in the same directory
2. **Framework + implementation** (NeMo Guardrails + Colang) — parent framework spec with implementation layer
3. **Sequential extension** (Import Check + Enhancements) — additive requirements continuing parent ID ranges

No formal convention governs which pattern to use, where to place documents, or how they cross-reference each other. As the project adds more provider integrations (each requiring a full 6-document chain), the current approach will not scale.

Additionally, these conventions are embedded in project-specific config (CLAUDE.md), making them non-portable across projects. They belong in the `doc-authoring` skill so any project can use them.

## 2. Design Decisions

### 2.1 Document Taxonomy — Role x Layer

Documents have two orthogonal dimensions:

**Role** — the structural purpose of the document:

| Role | What it is | Placement |
|------|-----------|-----------|
| **Pipeline Spec** | Pure interface contract for a stage. Defines what the stage does, its inputs/outputs, acceptance criteria. No tool names in requirements. | `docs/{domain}/{stage}/` |
| **Integration Spec** | How a specific tool/library implements one or more stages. References which pipeline FRs it fulfills/modifies. | `docs/{domain}/integrations/{provider}/` |
| **Platform Spec** | Cross-cutting requirements spanning multiple stages (config, error handling, lifecycle). | `docs/{domain}/` (root level) |
| **Extension Spec** | Additive requirements extending a base spec without replacing it. IDs continue from parent. | Same directory as parent spec |

**Layer** — the document type in the authoring chain (unchanged from current):

```
Layer 1 — Platform Spec          (manual)
Layer 2 — Spec Summary            → /write-spec-summary
Layer 3 — Authoritative Spec      → /write-spec
Layer 4 — Implementation Plan     → /write-impl
Layer 5 — Engineering Guide       → /write-engineering-guide
Layer 6 — Module Tests            → /write-module-tests (or /write-test-docs)
```

Every role gets the full layer chain. Documents can be short, but the chain is what keeps consistency.

### 2.2 Directory Structure Convention

Generic specs describe stages. Integration specs describe providers. They live in separate directory trees within the same domain.

```
docs/{domain}/
  {stage_a}/                        <- pipeline specs (pure interface)
    {STAGE_A}_SPEC.md
    {STAGE_A}_SPEC_SUMMARY.md
    {STAGE_A}_DESIGN.md
    {STAGE_A}_IMPLEMENTATION.md
    {STAGE_A}_ENGINEERING_GUIDE.md
    {STAGE_A}_MODULE_TESTS.md
  {stage_b}/
    ...
  integrations/                     <- provider implementations
    {provider_x}/
      {PROVIDER_X}_SPEC.md
      {PROVIDER_X}_SPEC_SUMMARY.md
      {PROVIDER_X}_DESIGN.md
      {PROVIDER_X}_IMPLEMENTATION.md
      {PROVIDER_X}_ENGINEERING_GUIDE.md
      {PROVIDER_X}_MODULE_TESTS.md
    {provider_y}/
      ...
    README.md                       <- discovery index: lists all providers
  {DOMAIN}_PLATFORM_SPEC.md         <- cross-cutting (root level)
  README.md
```

Key rules:

- **One directory per provider**, full chain inside, regardless of how many stages it touches.
- **Cross-phase providers** (e.g., Docling touching both doc processing and embedding) live at domain level in `integrations/` — not nested inside a single stage.
- **`integrations/README.md`** lists all providers with a one-line summary and which stages each touches. This is the discovery entry point.
- **Extension specs** stay in the same directory as their parent (no separate folder).

### 2.3 Cross-Reference Protocol

Documents are written across sessions. Each document needs enough pointers that a future session can reconstruct relationships.

**Pipeline spec -> Integration specs (downstream pointers):**

Companion Documents field:
```
| Companion Documents | ... DOCLING_SPEC.md (Docling integration — structure detection, chunking) |
```

Plus an Integrations table (added when the first integration spec is written):
```markdown
## Integrations

| Provider | Stages | Spec |
|----------|--------|------|
| Docling  | Structure Detection, Chunking | integrations/docling/DOCLING_SPEC.md |
```

**Integration spec -> Pipeline spec (upstream pointers):**

```markdown
| Upstream   | DOCUMENT_PROCESSING_SPEC.md, EMBEDDING_PIPELINE_SPEC.md |
| Implements | FR-201 (section tree), FR-202 (table extraction), FR-208 (swappable provider) |
| Modifies   | FR-400–FR-499 (text cleaning — skipped when this provider succeeds) |
```

`Implements` = which generic FRs this integration fulfills.
`Modifies` = which generic FRs change behavior when this integration is active.

**Session boundary rules:**

- Writing a **pipeline spec**: no need to read integration specs. You define the interface.
- Writing an **integration spec**: MUST read the pipeline spec first. `Implements`/`Modifies` fields are derived from it.
- **Adding a swap point**: if an integration reveals the pipeline spec needs a new FR, update the pipeline spec in the same session (living-interface principle).

### 2.4 Routing Enhancement

The doc-authoring router gains an upstream question before the existing layer routing:

```
User request arrives
    |
    v
Determine ROLE
    "Is this a generic pipeline spec, an integration spec,
     a platform spec, or an extension spec?"
    |
    +-- Pipeline    -> target: docs/{domain}/{stage}/
    +-- Integration -> target: docs/{domain}/integrations/{provider}/
    |                  MUST read pipeline spec first
    +-- Platform    -> target: docs/{domain}/
    +-- Extension   -> target: same dir as parent spec
    |
    v
Determine LAYER (existing routing)
    "What do you need to produce?"
    |
    +-- Spec Summary       -> /write-spec-summary
    +-- Authoritative Spec -> /write-spec
    +-- Implementation     -> /write-impl
    +-- Engineering Guide  -> /write-engineering-guide
    |
    v
Pass structural context to write-* skill:
    - target directory
    - document role
    - companion docs to cross-reference
    - for integrations: which pipeline FRs to read
```

The write-* skills themselves do not change. They receive structural context from the router.

### 2.5 Governance Additions

Added to the existing doc-authoring governance rules:

**Interface purity rule:** Pipeline specs MUST NOT contain implementation-specific requirements. If a requirement names a specific tool, config key, or provider behavior, it belongs in that provider's integration spec. The pipeline spec may name the default provider in prose but all FRs must be tool-agnostic.

**Living interface rule:** When writing an integration spec reveals that the pipeline spec is missing a swap point or stage boundary, add the generic FR to the pipeline spec in the same session. Do not leave the gap for a future session.

**Integration coherence gate** (added to existing coherence gates):

- [ ] `Implements` field lists every pipeline FR this integration fulfills
- [ ] `Modifies` field lists every pipeline FR whose behavior changes
- [ ] Pipeline spec's Integrations table includes this provider
- [ ] No implementation-specific FRs exist in the pipeline spec

### 2.6 Naming Convention

| Role | File naming | Example |
|------|------------|---------|
| Pipeline | `{STAGE}_{DOC_TYPE}.md` | `DOCUMENT_PROCESSING_SPEC.md` |
| Integration | `{PROVIDER}_{DOC_TYPE}.md` (inside provider dir) | `integrations/docling/DOCLING_SPEC.md` |
| Platform | `{DOMAIN}_PLATFORM_{DOC_TYPE}.md` | `INGESTION_PLATFORM_SPEC.md` |
| Extension | `{PARENT}_{FEATURE}_{DOC_TYPE}.md` | `IMPORT_CHECK_ENHANCEMENTS_SPEC.md` |

Doc types: `SPEC`, `SPEC_SUMMARY`, `DESIGN`, `IMPLEMENTATION`, `ENGINEERING_GUIDE`, `MODULE_TESTS`.

### 2.7 Living Interface Principle

Generic pipeline specs are not frozen at creation. They evolve as integrations reveal new swap points:

1. Start with a pipeline spec defining stage flow, inputs/outputs, acceptance criteria. No specific tools.
2. First integration written — reveals which FRs need swappability. Add those to the pipeline spec.
3. Second integration written — may reveal new swap points the first didn't need. Add those too.

The pipeline spec grows its interface surface incrementally, driven by concrete integration needs — not by speculative upfront design.

## 3. Migration Notes

Existing documents that would move under this convention:

| Current location | New location | Notes |
|-----------------|-------------|-------|
| `docs/ingestion/document_processing/DOCLING_CHUNKING_*.md` (6 files) | `docs/ingestion/integrations/docling/DOCLING_*.md` | Rename from `DOCLING_CHUNKING_` to `DOCLING_` since it's inside the provider directory |
| `docs/guardrails/COLANG_GUARDRAILS_*.md` (4 files) | `docs/guardrails/integrations/colang/COLANG_*.md` | Move from flat guardrails dir to integrations |
| `docs/guardrails/nemo_guardrails/NEMO_GUARDRAILS_*.md` | `docs/guardrails/integrations/nemo/NEMO_*.md` | Consistent with pattern |

Docling-specific FRs currently in `DOCUMENT_PROCESSING_SPEC.md` (FR-209, FR-210, FR-588) should move to the Docling integration spec. The pipeline spec keeps only tool-agnostic FRs.

Migration is not urgent — apply the convention to new work and migrate existing docs opportunistically.

## 4. Applicability Beyond Ingestion

This pattern generalizes to any domain:

| Domain | Pipeline stages | Potential integrations |
|--------|----------------|----------------------|
| Ingestion | Document Processing, Embedding | Docling, Weaviate, LangGraph |
| Retrieval | Query Processing, Generation | LiteLLM, search backends |
| Guardrails | Policy evaluation | NeMo, Colang |
| Server | API routing, storage | MinIO, auth providers |
| Observability | Tracing, metrics | Langfuse, OpenTelemetry |
