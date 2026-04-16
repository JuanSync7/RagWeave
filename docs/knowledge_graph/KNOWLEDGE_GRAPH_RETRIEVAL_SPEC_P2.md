# Knowledge Graph Retrieval — Phase 2 Specification

**RagWeave**
Version: 1.0.0 | Status: Draft | Domain: Knowledge Graph

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0.0 | 2026-04-14 | AI Assistant | Initial Phase 2 specification. Community context integration, verb normalization, operator configurability improvements. Extends KNOWLEDGE_GRAPH_RETRIEVAL_SPEC.md v1.0.0. |

---

## 1. Scope & Definitions

### 1.1 Problem Statement

Phase 1 of the KG retrieval enhancement (KNOWLEDGE_GRAPH_RETRIEVAL_SPEC.md) added typed edge traversal, path pattern matching, and graph context formatting. These capabilities produce detailed, structural graph context — specific entities, triples, and multi-hop path narratives injected into the LLM prompt.

However, this context is **locally scoped**: it follows edges outward from seed entities and reports only what the traversal directly touches. When a query triggers broad structural fanout (e.g., "what breaks if I change constraint X?"), the traversal may reach entities across multiple graph regions. The LLM receives the structural chain but lacks **thematic context** about what those regions represent. Without understanding that cluster A is "the database migration layer" and cluster B is "the authentication middleware," the LLM cannot reason about *why* the blast radius matters — only *what* it touches.

The community detection and summarization infrastructure (KNOWLEDGE_GRAPH_SPEC.md §10, REQ-KG-700–719) already produces pre-computed, LLM-generated thematic summaries for each community. These summaries exist at index time and cost zero at query time. However, they are currently used only for term expansion (REQ-KG-609) — community member names are injected as additional search terms. The summaries themselves are not surfaced in the generation prompt.

Additionally, three configuration gaps from Phase 1 limit operator control:

1. **Marker style** (`markdown`/`xml`/`plain`) is implemented in the formatter but has no environment variable binding — operators cannot change it without code modification.
2. **Max hop fanout** (`_MAX_HOP_FANOUT=50`) is a module-level constant in `path_matcher.py` — operators cannot tune it per deployment.
3. **Verb normalization** uses naive underscore-to-space replacement (`fixed_by` → `fixed by`) — predicates that require custom verb forms (`fixed_by` → `was fixed by`) cannot be configured.

### 1.2 Scope

This specification defines requirements for:

- **Community context injection** — surfacing pre-built community summaries in the graph context block alongside detailed traversal results
- **Operator configurability** — exposing marker style, max hop fanout, and verb normalization as configurable parameters

**Entry point:** The graph context formatting stage (Stage 3 in the Phase 1 architecture), after typed traversal and path pattern matching have produced their results.

**Exit point:** The augmented graph context block injected into the LLM prompt.

**Relationship to Phase 1:** This spec extends KNOWLEDGE_GRAPH_RETRIEVAL_SPEC.md v1.0.0. No Phase 1 requirements are superseded. Community context is a new section added to the graph context block. Config changes add new fields alongside existing ones.

**Relationship to parent spec:** Community detection (REQ-KG-700–719) and global retrieval (REQ-KG-609) are defined in KNOWLEDGE_GRAPH_SPEC.md. This spec consumes community summaries produced by that infrastructure — it does not modify detection or summarization behavior.

### 1.3 Terminology

| Term | Definition |
|------|-----------|
| **Community summary** | A 2–4 sentence LLM-generated thematic description of a graph community, produced at index time by `CommunitySummarizer` (REQ-KG-701) |
| **Community context section** | A new section in the graph context block that presents community summaries for communities touched by traversal |
| **Touched community** | A community that contains at least one entity reached during typed traversal or path pattern matching |
| **Verb normalization table** | A mapping from predicate labels to natural-language verb phrases used in path narrative rendering |
| **Thematic framing** | Context that describes what a cluster of entities represents as a group, as opposed to individual entity descriptions or relationships |

### 1.4 Requirement Priority Levels

Same as Phase 1: RFC 2119 — MUST, SHOULD, MAY.

### 1.5 Requirement Format

Same as Phase 1. Requirements are grouped with the following ID ranges:

| Section | ID Range | Component |
|---------|----------|-----------|
| 3 | REQ-KG-1300–1309 | Community Context Integration |
| 4 | REQ-KG-1310–1319 | Verb Normalization |
| 5 | REQ-KG-1320–1329 | Configuration Enhancements |
| 6 | REQ-KG-1330–1339 | Non-Functional Requirements |

### 1.6 Assumptions & Constraints

| ID | Assumption / Constraint | Impact if Violated |
|----|------------------------|--------------------|
| A-1 | Community detection and summarization have been run at least once before retrieval queries are issued | Community context section will be empty — not an error, but no thematic framing is available |
| A-2 | `CommunityDetector.is_ready` returns `True` when summaries exist | Community context injection has no way to check readiness independently |
| A-3 | `kg_schema.yaml` is the single source of truth for valid edge types and (optionally) verb normalization mappings | Verb normalization table must be maintained alongside edge type definitions |
| A-4 | Phase 1 retrieval infrastructure is implemented and operational | This spec extends Phase 1 — it does not function independently |

### 1.7 Design Principles

| Principle | Description |
|-----------|-------------|
| **Community context is additive** | Community summaries supplement the detailed graph context — they do not replace entity descriptions, triples, or path narratives. When no communities are touched or no summaries exist, the Phase 1 output is unchanged. |
| **Index-time cost, query-time free** | Community summaries are pre-computed. The retrieval path performs only dictionary lookups — no LLM calls at query time for community context. |
| **Operator-tunable** | Every behavioral parameter introduced in Phase 1 or Phase 2 is exposed as a `KGConfig` field with a corresponding `RAG_KG_` environment variable. No tunable is hardcoded as a module constant. |

### 1.8 Out of Scope

**Out of scope — this spec:**

- Community detection algorithm changes (Leiden resolution, hierarchical levels)
- Community summarization prompt or LLM changes
- Query-time LLM summarization of graph context (not needed — pre-built summaries suffice)
- Global search mode (fan out to all communities without seed entity) — deferred to Phase 3
- Named path pattern references in schema — deferred (inline patterns sufficient for current scale)
- Tokenizer integration for token budget — deferred (chars/4 approximation adequate for soft budget)

**Out of scope — this project:**

- Graph neural network embeddings
- Real-time graph updates during query session
- Cross-graph federation

---

## 2. System Overview

### 2.1 Architecture Diagram

```
User Query
    │
    ▼
┌──────────────────────────────────────────────────┐
│ [1] ENTITY MATCHING (existing — REQ-KG-600)      │
│     Produces: seed_entities[]                     │
└──────────────────┬───────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────┐
│ [2] TYPED EDGE TRAVERSAL    (Phase 1)            │
│     + PATH PATTERN MATCHING                      │
│     Produces: typed_neighbors[], paths[],        │
│               triples[]                          │
│                                                  │
│     NEW: collect community_ids from all          │
│          traversed entities                      │
└──────────────────┬───────────────────────────────┘
                   │
                   ├──→ BM25 query augmentation (existing)
                   │
                   ▼
┌──────────────────────────────────────────────────┐
│ [3] GRAPH CONTEXT FORMATTING  (Phase 1 + P2)     │
│                                                  │
│     Phase 1 sections:                            │
│       § Entity Summaries                         │
│       § Relationship Triples                     │
│       § Path Narratives  ◄── verb normalization  │
│                                                  │
│     NEW Phase 2 section:                         │
│       § Community Context  ◄── pre-built         │
│                                summaries         │
│                                                  │
│     Token budget applied to detailed sections;   │
│     community summaries have own budget slice    │
│                                                  │
│     Produces: graph_context_block (text)         │
└──────────────────┬───────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────┐
│ [4] PROMPT INJECTION        (Phase 1)            │
│     Insert graph_context_block into LLM prompt   │
└──────────────────────────────────────────────────┘
                   │
                   ▼
            LLM Generation
```

### 2.2 Data Flow — Community Context Path

| Stage | Input | Output |
|-------|-------|--------|
| Typed Traversal | Seed entities + edge-type filter | Neighbor entities with `community_id` attributes |
| Community ID Collection | All traversed entities (seeds + neighbors + path entities) | Deduplicated set of community IDs |
| Summary Lookup | Community IDs + `CommunityDetector` | `Dict[int, CommunitySummary]` for touched communities |
| Community Section Formatting | Community summaries + marker style | Formatted text lines for the Community Context section |
| Budget Integration | Community section + Phase 1 sections + token budget | Budget-bounded graph context block |

---

## 3. Community Context Integration

The graph context block currently contains three sections: Entity Summaries, Relationship Triples, and Path Narratives. All three describe **local** graph structure around seed entities. This section adds a fourth section — **Community Context** — that provides **thematic framing** for the regions of the graph that the traversal touched.

---

> **REQ-KG-1300** | Priority: MUST
>
> **Description:** After typed traversal and path pattern matching, the system MUST collect the `community_id` attribute from every entity encountered during traversal — including seed entities, typed neighbors, and all entities on matched path hops. The collection MUST produce a deduplicated set of community IDs. Community ID `-1` (the miscellaneous bucket for sub-threshold communities) MUST be excluded.
>
> **Rationale:** The set of touched communities defines which thematic summaries are relevant to the current query. Collecting IDs from all traversal stages (not just seeds) ensures that blast-radius queries spanning multiple communities receive summaries for every affected region.
>
> **Acceptance Criteria:**
> 1. A traversal that visits entities in communities 3, 7, and 3 produces the deduplicated set `{3, 7}`.
> 2. A traversal that visits only entities with `community_id = -1` produces an empty set.
> 3. A traversal that visits entities without a `community_id` attribute skips those entities without error.
> 4. Community IDs are collected from seed entities, typed neighbor results, and every hop in matched path results.

---

> **REQ-KG-1302** | Priority: MUST
>
> **Description:** For each community ID in the collected set, the system MUST look up the pre-built `CommunitySummary` via `CommunityDetector.get_summary(community_id)`. Communities with no summary (returns `None`) MUST be silently skipped. The lookup MUST NOT trigger any LLM call, graph traversal, or computation beyond a dictionary access.
>
> **Rationale:** Community summaries are computed at index time (REQ-KG-701). The retrieval path must not pay for re-computation. Skipping missing summaries ensures graceful behavior when summarization is incomplete or a community was just detected but not yet summarized.
>
> **Acceptance Criteria:**
> 1. For community IDs `{3, 7}` where community 3 has a summary and community 7 does not, only community 3's summary is included.
> 2. The lookup is a dictionary access on `CommunityDetector.summaries` — no LLM provider is invoked.
> 3. A `CommunityDetector` with `is_ready = False` results in zero community summaries being included — no error raised.
> 4. Lookup time is O(1) per community.

---

> **REQ-KG-1304** | Priority: MUST
>
> **Description:** The graph context formatter MUST render a **Community Context** section containing one entry per retrieved community summary. Each entry MUST include: (a) a community identifier label, (b) the `summary_text` from `CommunitySummary`, and (c) a count of how many traversed entities belong to that community. The section MUST appear after the Path Narratives section and before any truncation annotation. When no community summaries are retrieved, the section MUST be omitted entirely (consistent with REQ-KG-780 empty-section rule).
>
> **Rationale:** Placing community context last in the block follows the information architecture principle of specifics-before-context: the LLM reads specific entities, relationships, and paths first, then receives the thematic framing that helps interpret them. Including the traversed-entity count helps the LLM gauge the scope of each community's involvement.
>
> **Acceptance Criteria:**
> 1. The Community Context section appears after Path Narratives in the formatted output.
> 2. Each entry renders as: `[Community {id}] ({N} entities touched): {summary_text}`.
> 3. When zero community summaries are retrieved, the section heading and all community content is absent from the output.
> 4. The section uses the configured marker style (markdown: `### Communities`, xml: `<communities>...</communities>`, plain: `--- COMMUNITIES ---`).

---

> **REQ-KG-1306** | Priority: MUST
>
> **Description:** The community context section MUST have its own independent token sub-budget, configured via `community_context_token_budget` (default: 200 tokens). This sub-budget is **in addition to** the existing `graph_context_token_budget` that governs Entity Summaries, Relationship Triples, and Path Narratives. The total graph context block size is bounded by the sum of both budgets. When community summaries exceed the community sub-budget, summaries MUST be truncated by removing the community with the fewest traversed entities first (lowest involvement = lowest priority).
>
> **Rationale:** Community summaries are compact (2–4 sentences each, ~50–100 tokens) and provide qualitatively different context than detailed traversal results. A shared budget would force community summaries to compete with path narratives — and since the Phase 1 truncation logic drops paths before entities, community summaries would be truncated early despite providing non-redundant thematic framing. A separate sub-budget ensures both detailed and thematic context survive.
>
> **Acceptance Criteria:**
> 1. A query touching 5 communities (50 tokens each = 250 tokens) with `community_context_token_budget=200` truncates by dropping the community with fewest traversed entities.
> 2. The Phase 1 `graph_context_token_budget` applies only to Entity Summaries, Relationship Triples, and Path Narratives — unchanged from Phase 1.
> 3. Setting `community_context_token_budget=0` disables community context entirely (no community section rendered).
> 4. The total graph context block size never exceeds `graph_context_token_budget + community_context_token_budget`.

---

> **REQ-KG-1308** | Priority: MUST
>
> **Description:** Community context injection MUST degrade gracefully. If any error occurs during community ID collection, summary lookup, or community section formatting, the system MUST proceed with the Phase 1 graph context block (Entity Summaries, Relationship Triples, Path Narratives) and log the error at WARNING level. Community context failures MUST NOT cause request failures or degrade the Phase 1 context.
>
> **Rationale:** Community context is additive thematic framing. The Phase 1 context is already a complete, useful representation of graph structure. Failing the entire context block because a community summary lookup raised an exception would violate the graceful degradation principle established in REQ-KG-1214.
>
> **Acceptance Criteria:**
> 1. A test injecting an exception into community ID collection confirms: Phase 1 context is produced unchanged, WARNING logged.
> 2. A test injecting an exception into summary lookup confirms: Phase 1 context is produced unchanged, WARNING logged.
> 3. The log entry includes the exception type, message, and the stage where the failure occurred.

---

## 4. Verb Normalization

Phase 1 path narratives replace underscores with spaces in predicate labels (`fixed_by` → `fixed by`). This produces grammatically awkward narratives for predicates that require different verb forms. This section defines a configurable verb normalization table.

---

> **REQ-KG-1310** | Priority: MUST
>
> **Description:** The graph context formatter MUST support a configurable **verb normalization table** — a mapping from predicate labels (as defined in `kg_schema.yaml`) to human-readable verb phrases. When rendering path narratives (REQ-KG-784), the formatter MUST look up each predicate in the verb normalization table; if a mapping exists, use the mapped phrase; if no mapping exists, fall back to the current underscore-to-space replacement.
>
> **Rationale:** Predicate labels are identifiers, not prose. `fixed_by` should render as `"was fixed by"`, not `"fixed by"`. `design_decision_for` should render as `"has design decision for"`, not `"design decision for"`. A configurable table lets domain experts define natural-language renderings without code changes.
>
> **Acceptance Criteria:**
> 1. With table `{"fixed_by": "was fixed by"}`, the path narrative renders `"A was fixed by B"` instead of `"A fixed by B"`.
> 2. A predicate not in the table falls back to underscore replacement: `"depends_on"` → `"depends on"`.
> 3. The table is loaded from configuration — not hardcoded.
> 4. An empty table produces identical behavior to Phase 1 (pure underscore replacement).

---

> **REQ-KG-1312** | Priority: SHOULD
>
> **Description:** The verb normalization table SHOULD be defined in `kg_schema.yaml` alongside edge type definitions, under a `verb_normalization` key. Each entry maps an edge type label to its natural-language verb phrase. Edge types without an entry use the underscore-to-space fallback.
>
> **Rationale:** `kg_schema.yaml` is already the single source of truth for edge type vocabulary (REQ-KG-764). Co-locating verb forms with edge type definitions ensures they stay synchronized — a newly added edge type's verb form is defined in the same place.
>
> **Acceptance Criteria:**
> 1. `kg_schema.yaml` accepts a `verb_normalization` key containing a mapping of edge type labels to verb phrases.
> 2. Adding `verb_normalization: { fixed_by: "was fixed by" }` to the schema and reloading config produces the mapped phrase in path narratives.
> 3. A missing `verb_normalization` key in the schema is not an error — the formatter uses underscore replacement for all predicates.

---

## 5. Configuration Enhancements

Phase 1 introduced five `KGConfig` fields. This section adds fields for community context, verb normalization, and two parameters that were previously hardcoded.

---

> **REQ-KG-1320** | Priority: MUST
>
> **Description:** `KGConfig` MUST add a field `community_context_token_budget: int` with a default value of `200`. This controls the independent token sub-budget for the community context section (REQ-KG-1306). Setting to `0` disables community context injection.
>
> **Rationale:** Operators need to tune how much prompt space community summaries consume, independently of the detailed graph context budget.
>
> **Acceptance Criteria:**
> 1. `KGConfig` defines `community_context_token_budget: int = 200`.
> 2. The field is populated from `RAG_KG_COMMUNITY_CONTEXT_TOKEN_BUDGET`.
> 3. Config validation rejects values < 0 with a clear error message.

---

> **REQ-KG-1322** | Priority: MUST
>
> **Description:** `KGConfig` MUST add a field `graph_context_marker_style: str` with a default value of `"markdown"`. Valid values are `"markdown"`, `"xml"`, and `"plain"`. This field replaces the previously hardcoded marker style in the formatter constructor.
>
> **Rationale:** Phase 1 implemented marker style support (REQ-KG-788) but the value was hardcoded at construction time. Operators deploying in environments where markdown is not rendered (e.g., plain-text logging pipelines, XML-based prompt templates) cannot switch styles without code changes.
>
> **Acceptance Criteria:**
> 1. `KGConfig` defines `graph_context_marker_style: str = "markdown"`.
> 2. The field is populated from `RAG_KG_GRAPH_CONTEXT_MARKER_STYLE`.
> 3. Config validation rejects values not in `{"markdown", "xml", "plain"}` with a clear error message.

---

> **REQ-KG-1324** | Priority: MUST
>
> **Description:** `KGConfig` MUST add a field `max_hop_fanout: int` with a default value of `50`. This replaces the module-level constant `_MAX_HOP_FANOUT` in `path_matcher.py`. The `PathMatcher` MUST read this value from the config at construction time.
>
> **Rationale:** The hop fanout limit caps how many entities are explored per hop during path pattern evaluation. In dense graphs (e.g., ASIC designs where a signal `connects_to` hundreds of ports), the default of 50 may be too low, causing incomplete path results. In sparse graphs, a lower value reduces unnecessary exploration. Operators need to tune this per deployment without code changes.
>
> **Acceptance Criteria:**
> 1. `KGConfig` defines `max_hop_fanout: int = 50`.
> 2. The field is populated from `RAG_KG_MAX_HOP_FANOUT`.
> 3. Config validation rejects values < 1 with a clear error message.
> 4. `PathMatcher` uses `config.max_hop_fanout` instead of the module constant.

---

> **REQ-KG-1326** | Priority: MUST
>
> **Description:** All configurable parameters introduced in Section 5 of this spec MUST be readable from environment variables with the `RAG_KG_` prefix, following the existing `KGConfig` naming convention established in REQ-KG-1216.
>
> **Rationale:** Consistency with the existing configuration surface.
>
> **Acceptance Criteria:**
> 1. Each Section 5 field has a corresponding `RAG_KG_` environment variable listed in its own requirement.
> 2. A smoke test sets all new variables to non-default values and asserts `KGConfig` reflects them.

---

## 6. Non-Functional Requirements

---

> **REQ-KG-1330** | Priority: MUST
>
> **Description:** Community context injection (community ID collection + summary lookup + formatting) MUST NOT add more than 5ms of latency at P95 to the graph context formatting stage, for queries touching up to 10 communities.
>
> **Rationale:** Community context injection is designed to be zero-cost at query time — dictionary lookups and string formatting only. A 5ms ceiling confirms that no inadvertent computation (e.g., re-summarization, graph traversal) has crept in.
>
> **Acceptance Criteria:**
> 1. A benchmark measures community injection overhead for queries touching 1, 5, and 10 communities.
> 2. P95 overhead is ≤ 5ms at each level.

---

> **REQ-KG-1332** | Priority: MUST
>
> **Description:** Verb normalization table loading from `kg_schema.yaml` MUST occur once at startup (or config reload), not per-query. The loaded table MUST be cached in memory for the lifetime of the formatter instance.
>
> **Rationale:** YAML file I/O on every query would add unnecessary latency. Loading once and caching is consistent with how edge type validation already works.
>
> **Acceptance Criteria:**
> 1. The YAML file is read exactly once during formatter initialization.
> 2. A second call to `format()` does not trigger file I/O.
> 3. Table reload occurs when the config is explicitly reloaded.

---

> **REQ-KG-1334** | Priority: MUST
>
> **Description:** All Phase 2 features MUST degrade gracefully to Phase 1 behavior when their dependencies are unavailable. Specifically: (a) When `CommunityDetector` is `None` or `is_ready=False`, community context is silently omitted. (b) When `verb_normalization` key is absent from `kg_schema.yaml`, underscore-to-space fallback applies. (c) When `community_context_token_budget=0`, community context is disabled.
>
> **Rationale:** Phase 2 features are additive. Deployments that have not run community detection, or have not updated their schema with verb mappings, must continue to function identically to Phase 1.
>
> **Acceptance Criteria:**
> 1. A deployment with no `CommunityDetector` configured produces identical output to Phase 1.
> 2. A schema without `verb_normalization` produces identical path narratives to Phase 1.
> 3. Setting `community_context_token_budget=0` produces identical output to Phase 1.

---

## 7. System-Level Acceptance Criteria

| Criterion | Threshold | Related Requirements |
|-----------|-----------|---------------------|
| Community injection latency | ≤ 5ms P95 (≤ 10 communities) | REQ-KG-1300, REQ-KG-1330 |
| Verb normalization correctness | All mapped predicates render mapped phrases | REQ-KG-1310, REQ-KG-1312 |
| Budget enforcement | Total block ≤ `graph_context_token_budget + community_context_token_budget` | REQ-KG-1306 |
| Graceful degradation | Phase 1 output unchanged when Phase 2 deps unavailable | REQ-KG-1308, REQ-KG-1334 |
| Config surface complete | All new params have `RAG_KG_` env vars | REQ-KG-1326 |

---

## 8. Requirements Traceability Matrix

| REQ ID | Section | Priority | Component |
|--------|---------|----------|-----------|
| REQ-KG-1300 | 3 | MUST | Community Context Integration |
| REQ-KG-1302 | 3 | MUST | Community Context Integration |
| REQ-KG-1304 | 3 | MUST | Community Context Integration |
| REQ-KG-1306 | 3 | MUST | Community Context Integration |
| REQ-KG-1308 | 3 | MUST | Community Context Integration |
| REQ-KG-1310 | 4 | MUST | Verb Normalization |
| REQ-KG-1312 | 4 | SHOULD | Verb Normalization |
| REQ-KG-1320 | 5 | MUST | Configuration |
| REQ-KG-1322 | 5 | MUST | Configuration |
| REQ-KG-1324 | 5 | MUST | Configuration |
| REQ-KG-1326 | 5 | MUST | Configuration |
| REQ-KG-1330 | 6 | MUST | Non-Functional |
| REQ-KG-1332 | 6 | MUST | Non-Functional |
| REQ-KG-1334 | 6 | MUST | Non-Functional |

**Total Requirements: 14**

- MUST: 13
- SHOULD: 1
- MAY: 0

---

## 9. Phase 1 Open Questions — Resolutions

This section resolves the three open questions from KNOWLEDGE_GRAPH_RETRIEVAL_SPEC.md Appendix C:

| # | Question | Resolution |
|---|----------|------------|
| 1 | **Verb normalization table location** — schema vs separate file? | **In `kg_schema.yaml`** under `verb_normalization` key (REQ-KG-1312). Keeps single source of truth. The dictionary is small (~15–20 entries, bounded by edge type count). |
| 2 | **Named pattern references** — named aliases vs inline? | **Deferred.** Current scale (5–30 patterns) does not justify the indirection. Inline patterns remain the only format. Revisit if pattern count exceeds ~50. |
| 3 | **Tokenizer choice** — real tokenizer vs chars/4? | **Keep chars/4 approximation.** The token budget is a soft limit protecting prompt space. ±20% drift is acceptable for a budget of 500. Adding a tokenizer dependency (tiktoken or model-specific) provides marginal accuracy for a soft constraint. Revisit only if users report prompt truncation issues. |

---

## Appendix A. Document References

| Document | Purpose |
|----------|---------|
| `KNOWLEDGE_GRAPH_RETRIEVAL_SPEC.md` (v1.0.0) | Phase 1 specification — typed traversal, path patterns, context formatting, prompt injection |
| `KNOWLEDGE_GRAPH_SPEC.md` (v1.1.0) | Parent specification — community detection (§10, REQ-KG-700–719), global retrieval (REQ-KG-609) |
| `config/kg_schema.yaml` | Edge type vocabulary, entity type definitions, verb normalization table (new) |
| `KNOWLEDGE_GRAPH_RETRIEVAL_ENGINEERING_GUIDE.md` | Phase 1 engineering guide |

---

## Appendix B. Relationship to Existing Community Infrastructure

This spec **consumes** community summaries — it does not produce them. The full community pipeline is:

```
Index time (KNOWLEDGE_GRAPH_SPEC.md):
  Graph built → CommunityDetector.detect() → Leiden clustering
                                            → CommunityDetector.summaries assigned
  CommunitySummarizer.summarize_all() → LLM summarization per community
                                      → CommunitySummary.summary_text populated
  CommunityDetector.save_sidecar() → persisted to JSON

Query time (this spec):
  Typed traversal → entities have community_id attribute
  Collect community IDs → {3, 7, 12}
  CommunityDetector.get_summary(cid) → CommunitySummary (dict lookup, O(1))
  Format into Community Context section → inject into graph context block
```

No modification to `CommunityDetector`, `CommunitySummarizer`, or `CommunitySummary` is required.
