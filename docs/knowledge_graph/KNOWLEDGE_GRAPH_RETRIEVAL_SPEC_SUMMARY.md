## 1) Generic System Overview

<!-- SCRAPEABLE SECTION — must be tech-agnostic. No FR-IDs, no technology names, no file names, no threshold values. Written from scratch. 250–450 words across all five sub-sections. -->

### Purpose

The graph-aware retrieval subsystem closes the gap between a richly typed knowledge graph and a retrieval pipeline that ignores relationship structure. Without it, the graph stores valuable domain knowledge — fix policies, port connectivity, specification traceability, design decisions — but query expansion treats every edge identically, producing noisy BM25 augmentations and giving the language model no structured relationship context. This subsystem makes the graph's typed relationships actionable at query time.

### How It Works

A user query enters the existing entity matching stage, which identifies seed entities in the graph. Those seeds then pass through a typed edge traversal stage that follows only edges matching a configured set of predicate types, rather than performing unrestricted neighbor expansion. When path pattern templates are configured — ordered sequences of edge types such as "issue → fixed-by → decision → specified-by → specification" — the traversal evaluates each pattern step by step, retaining the full chain of intermediate entities and edge labels at every hop. Multiple patterns may be evaluated in parallel against the same seed set.

The traversal results feed into a graph context formatter that assembles a structured text block with three sections: entity summaries (name, type, and description for each relevant entity), relationship triples grouped by predicate type, and path narratives — human-readable sentences that articulate multi-hop reasoning chains. This block respects a configurable token budget, shedding lower-priority content (neighbor descriptions first, then triples, then paths, then seed descriptions) to fit.

Finally, the formatted context block is injected into the language model's generation prompt in a labeled section placed before retrieved document chunks. When context is empty or the feature is disabled, the prompt section is omitted entirely — no empty placeholder.

### Tunable Knobs

Operators control which edge types are followed during traversal, filtering out noisy relationship categories. Path pattern templates define multi-hop reasoning chains; multiple patterns can run simultaneously. A token budget caps how much of the prompt window graph context may consume. A master toggle enables or disables the entire enhancement, allowing safe rollout and instant rollback. Section marker style for the context block is configurable to match different prompt formats.

### Design Rationale

The system is designed around a typed-first, untyped-fallback principle: when no edge-type filter is configured, existing unrestricted expansion applies unchanged, preserving backward compatibility. All edge types and path patterns are validated against the canonical schema at startup, catching misconfiguration before any query runs. Graph context is additive — it supplements document chunks rather than replacing them. Traversal respects the same fan-out limits as untyped expansion, ensuring typed queries never produce larger result sets than the system already handles.

### Boundary Semantics

Entry: seed entities identified by the upstream entity matcher and the current graph state. Exit: (a) typed expansion terms appended to the lexical query, and (b) a formatted graph context block forwarded to the generation prompt. The subsystem does not own entity matching, document retrieval, or answer generation — responsibility ends once expansion terms and the context block are produced.

---

# Knowledge Graph Retrieval — Specification Summary

**Companion document to:** `KNOWLEDGE_GRAPH_RETRIEVAL_SPEC.md` (v1.0.0, Draft)
**Purpose:** Requirements-level digest for stakeholders, reviewers, and implementers.
**See also:** `KNOWLEDGE_GRAPH_SPEC.md` (parent spec), `KNOWLEDGE_GRAPH_DESIGN.md`, `KNOWLEDGE_GRAPH_ENGINEERING_GUIDE.md`, `RETRIEVAL_QUERY_SPEC.md`

---

## 2) Scope and Boundaries

**Entry point:** A user query arrives at the retrieval pipeline's KG expansion stage.

**Exit points:**

- Typed expansion terms augmenting the lexical query
- A structured graph-context block injected into the LLM generation prompt

### In scope

- Typed edge traversal with configurable predicate filters
- Multi-hop path pattern queries with ordered edge type sequences
- Graph context formatting with entity summaries, grouped triples, and path narratives
- Token-budgeted context assembly with priority-based truncation
- Prompt injection of graph-derived context into the generation template
- Configuration fields for edge filters, path patterns, token budget, and master toggle
- Schema-validated edge types and path patterns at startup

### Out of scope — this spec

- Entity extraction and graph ingestion
- Entity matching and query normalization
- Community detection and global retrieval
- Graph storage backend internals
- Graph visualization and export

### Out of scope — this project

- Natural-language-to-graph-query translation
- Graph neural network embeddings for retrieval
- Real-time graph updates during a query session

---

## 3) Architecture / Pipeline Overview

```
User Query
       │
       ▼
  [1] Entity Matching (existing)
       │ seed_entities[]
       ▼
  [2] Typed Edge Traversal
       ├── edge-type filter → typed neighbors
       └── path patterns?
            ├─ YES → multi-hop path matching
            └─ NO  → untyped fallback
       │ expansion_terms[] + paths[]
       ├──→ BM25 query augmentation
       ▼
  [3] Graph Context Formatting
       │ graph_context_block (text)
       ▼
  [4] Prompt Injection
       │ augmented LLM prompt
       ▼
  LLM Generation
```

Typed traversal and path pattern matching share the same fan-out limits as untyped expansion. The context formatter enforces a token budget with priority-based truncation. When the feature is disabled, stages 2–4 are skipped entirely.

---

## 4) Requirement Framework

The spec uses a formal requirement framework with the following elements:

- **ID convention:** `REQ-KG-xxx`, continuing the parent spec's namespace from 760 onward
- **Priority keywords:** RFC 2119 (`MUST`, `SHOULD`, `MAY`)
- **Per-requirement structure:** Description, Rationale, Acceptance Criteria
- **Traceability matrix:** Appendix listing all 28 requirements with section, priority, and component
- **Glossary:** Appendix A defines 8 technical terms

---

## 5) Functional Requirement Domains

The functional requirements cover typed graph traversal, multi-hop path queries, structured context generation, and prompt integration.

- **Typed Edge Traversal & Filtering** (`REQ-KG-760`–`REQ-KG-769`) — backend typed-traversal method, expander dispatch, schema validation, untyped fallback, fan-out limits
- **Path Pattern Queries** (`REQ-KG-770`–`REQ-KG-779`) — pattern definition, step-by-step evaluation, multiple patterns per query, full path results, schema validation with type compatibility
- **Graph Context Formatting** (`REQ-KG-780`–`REQ-KG-789`) — structured block with entity/triple/path sections, entity descriptions with fallback, path narratives, token budget truncation, configurable section markers
- **Prompt Injection Integration** (`REQ-KG-790`–`REQ-KG-799`) — structured expander return type, pipeline threading, prompt template slot, clean omission when empty
- **Configuration** (`REQ-KG-1200`–`REQ-KG-1209`) — edge type list, path patterns, token budget, master toggle, startup validation

---

## 6) Non-Functional and Security Themes

### Non-functional areas (`REQ-KG-1210`–`REQ-KG-1219`)

- **Performance** — latency ceilings for typed traversal and context formatting
- **Graceful degradation** — typed traversal failure falls back to untyped; formatting failure proceeds without graph context
- **Configuration externalization** — all parameters accessible via environment variables with consistent prefix

The spec does not define a standalone security requirement family.

---

## 7) Design Principles

- **Typed-first, untyped-fallback**: when filters are configured, follow only matching edges; otherwise, existing untyped expansion applies unchanged
- **Graph context is additive**: supplements document chunks, never replaces them
- **Schema-validated paths**: invalid edge types in path patterns are rejected at startup, not silently ignored at query time
- **Bounded complexity**: typed traversal respects the same fan-out limits as untyped expansion

---

## 8) Key Decisions Captured by the Spec

- The backend ABC gains a new `query_neighbors_typed` method rather than adding filter parameters to the existing method — cleaner contract, no signature pollution
- The expander returns a structured result (terms + graph context block) instead of a bare list — minimal intervention at the boundary
- Graph context is positioned before document chunks in the prompt — background knowledge as a lens for evidence reading
- Master toggle defaults to off — opt-in rollout, zero overhead when disabled
- Path patterns are ordered sequences, not unordered sets — edge traversal order matters for semantic chains
- Token budget truncation follows a fixed priority order (neighbors → triples → paths → seeds) — path narratives are highest value

---

## 9) Acceptance, Evaluation, and Feedback

- **Per-requirement acceptance criteria:** Every functional requirement carries testable criteria with ASIC-domain examples
- **System-level acceptance criteria:** Cross-cutting thresholds for traversal latency, formatting latency, graceful degradation, backward compatibility, and config validation
- **Open questions:** Three pending decisions documented in Appendix C (verb normalization location, named pattern references, tokenizer choice)

---

## 10) Companion Documents

| Document | Role |
|----------|------|
| `KNOWLEDGE_GRAPH_RETRIEVAL_SPEC.md` | Authoritative requirements baseline |
| `KNOWLEDGE_GRAPH_RETRIEVAL_SPEC_SUMMARY.md` | This document — requirements digest |
| `KNOWLEDGE_GRAPH_SPEC.md` | Parent specification (extraction, storage, basic expansion) |
| `KNOWLEDGE_GRAPH_SPEC_SUMMARY.md` | Parent spec requirements digest |
| `KNOWLEDGE_GRAPH_ENGINEERING_GUIDE.md` | Operator guide for the KG subsystem |
| `RETRIEVAL_QUERY_SPEC.md` | Retrieval pipeline spec (Stage 2 integration point) |
| `config/kg_schema.yaml` | Schema defining valid entity and edge types |

---

## 11) Sync Status

Aligned to `KNOWLEDGE_GRAPH_RETRIEVAL_SPEC.md` v1.0.0 as of 2026-04-13.
