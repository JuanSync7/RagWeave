# Design Sketch: Retrieval Docs Split — QUERY + GENERATION 5+5 Suite

**Date:** 2026-03-25
**Run:** 2026-03-25-retrieval-docs-split
**Approach:** Spec-anchored split (Approach A)

---

## Goal Statement

Split the combined `RETRIEVAL_DESIGN.md` and `RETRIEVAL_IMPLEMENTATION.md` (which cover the full 8-stage pipeline) into clean QUERY and GENERATION module doc suites. Create the two missing QUERY module docs (`RETRIEVAL_QUERY_ENGINEERING_GUIDE.md`, `RETRIEVAL_QUERY_MODULE_TESTS.md`). End state: 5 QUERY docs + 5 GENERATION docs, each suite fully self-contained, traceable to its spec, and sufficient for an agent to execute independently.

---

## Chosen Approach

**Spec-anchored split.** Every task in the combined docs is assigned to exactly one module by looking up which spec owns the requirement number. No cross-module references within a doc suite. "SHARED" tasks are resolved deterministically:

| Formerly-SHARED Task | Req | Assigned To |
|---------------------|-----|-------------|
| Embedding cache | REQ-306 | QUERY |
| Connection pool | REQ-307 | QUERY |
| Query result cache | REQ-308 | QUERY |
| Retry logic | REQ-605 | GENERATION |
| Observability | REQ-801–803 | GENERATION |
| Pipeline state + routing | REQ-706 | GENERATION |

---

## Key Decisions

1. **RAGPipelineState owned by GENERATION.** It is the LangGraph graph's wire type (defined in `graph.py`, owned by GENERATION). QUERY stages are consumers — they read/write their own fields on the state. QUERY_IMPLEMENTATION references it as an established input contract, not as something it defines.

2. **Phase 0 contracts split cleanly.** Each Phase 0 task contains stubs for either QUERY or GENERATION stages. The pipeline state (Task 0.3) goes to GENERATION; conversation memory types (Task 0.5) go to QUERY; guardrail types split by stage (pre-retrieval guard → QUERY, post-generation guard → GENERATION).

3. **Delete combined docs after split is verified.** `RETRIEVAL_DESIGN.md` and `RETRIEVAL_IMPLEMENTATION.md` are deleted once both module splits are confirmed complete. Pipeline-level overview docs (`RETRIEVAL_SPEC_SUMMARY.md`, `RETRIEVAL_ENGINEERING_GUIDE.md`) are retained but updated to reference the new module suites.

4. **QUERY engineering guide and module tests written from QUERY spec + QUERY design as inputs.** Mirror the structure of `RETRIEVAL_GENERATION_ENGINEERING_GUIDE.md` and `RETRIEVAL_GENERATION_MODULE_TESTS.md` exactly.

5. **Parallel wave execution.** Wave 1 splits DESIGN and IMPLEMENTATION in parallel (two agents). Wave 2 writes QUERY engineering guide. Wave 3 writes QUERY module tests. Each wave gates before the next.

---

## Target File Suite

### QUERY (5 docs)
| File | Status | Action |
|------|--------|--------|
| `RETRIEVAL_QUERY_SPEC.md` | ✓ exists | No change |
| `RETRIEVAL_QUERY_DESIGN.md` | ✗ missing | Create (split from RETRIEVAL_DESIGN.md) |
| `RETRIEVAL_QUERY_IMPLEMENTATION.md` | ✗ missing | Create (split from RETRIEVAL_IMPLEMENTATION.md) |
| `RETRIEVAL_QUERY_ENGINEERING_GUIDE.md` | ✗ missing | Create new (from QUERY spec + design) |
| `RETRIEVAL_QUERY_MODULE_TESTS.md` | ✗ missing | Create new (from QUERY engineering guide) |

### GENERATION (5 docs)
| File | Status | Action |
|------|--------|--------|
| `RETRIEVAL_GENERATION_SPEC.md` | ✓ exists | No change |
| `RETRIEVAL_GENERATION_DESIGN.md` | ✗ missing | Create (split from RETRIEVAL_DESIGN.md) |
| `RETRIEVAL_GENERATION_IMPLEMENTATION.md` | ✗ missing | Create (split from RETRIEVAL_IMPLEMENTATION.md) |
| `RETRIEVAL_GENERATION_ENGINEERING_GUIDE.md` | ✓ exists | No change |
| `RETRIEVAL_GENERATION_MODULE_TESTS.md` | ✓ exists | No change |

### To Delete After Split Verification
- `RETRIEVAL_DESIGN.md`
- `RETRIEVAL_IMPLEMENTATION.md`

---

## Component / Module List

- **Wave 1A Agent (haiku):** Write `RETRIEVAL_QUERY_DESIGN.md` + `RETRIEVAL_GENERATION_DESIGN.md` from RETRIEVAL_DESIGN.md section map
- **Wave 1B Agent (haiku):** Write `RETRIEVAL_QUERY_IMPLEMENTATION.md` + `RETRIEVAL_GENERATION_IMPLEMENTATION.md` from RETRIEVAL_IMPLEMENTATION.md section map
- **Wave 2 Agent (sonnet):** Write `RETRIEVAL_QUERY_ENGINEERING_GUIDE.md` using QUERY_SPEC + QUERY_DESIGN as inputs, GENERATION_ENGINEERING_GUIDE as structural template
- **Wave 3 Agent (sonnet):** Write `RETRIEVAL_QUERY_MODULE_TESTS.md` using QUERY_ENGINEERING_GUIDE as input, GENERATION_MODULE_TESTS as structural template

---

## Scope Boundary

**In scope:**
- Splitting RETRIEVAL_DESIGN.md → QUERY_DESIGN.md + GENERATION_DESIGN.md
- Splitting RETRIEVAL_IMPLEMENTATION.md → QUERY_IMPLEMENTATION.md + GENERATION_IMPLEMENTATION.md
- Creating RETRIEVAL_QUERY_ENGINEERING_GUIDE.md
- Creating RETRIEVAL_QUERY_MODULE_TESTS.md
- Deleting the two original combined docs

**Out of scope:**
- Modifying RETRIEVAL_QUERY_SPEC.md or RETRIEVAL_GENERATION_SPEC.md
- Modifying RETRIEVAL_GENERATION_ENGINEERING_GUIDE.md or RETRIEVAL_GENERATION_MODULE_TESTS.md
- Updating RETRIEVAL_SPEC_SUMMARY.md or RETRIEVAL_ENGINEERING_GUIDE.md (separate task)
- Any source code changes

---

## Open Questions

None. All "SHARED" task assignments resolved by spec requirement ownership.

---

## Appendix A: RETRIEVAL_DESIGN.md Section Map

Source: 2163-line document, v1.2. Agent uses this table as a lookup — no judgment calls needed.

### RETRIEVAL_QUERY_DESIGN.md (QUERY sections)

**Part A — Task Overview:**

| Lines | Section |
|-------|---------|
| 1–26 | Document header (adapt title to QUERY) |
| 33–52 | Task 1.1: Pre-Retrieval Guardrail Layer |
| 95–111 | Task 1.4: Input Validation at System Boundaries |
| 159–175 | Task 2.3: Risk Classification |
| 242–260 | Task 3.4: Multi-Turn Context / Coreference Resolution |
| 266–283 | Task 4.1: Connection Pooling for Vector Database (REQ-307 → QUERY) |
| 286–303 | Task 4.2: Embedding Cache (REQ-306 → QUERY) |
| 306–325 | Task 4.3: Query Result Cache (REQ-308 → QUERY) |
| 352–369 | Task 5.1: Externalize Injection Patterns |
| 372–391 | Task 5.2: Pre-Retrieval PII Filtering |
| 417–437 | Task 6.1: Conversation Memory Provider |
| 440–460 | Task 6.2: Sliding Window and Rolling Summary |
| 462–482 | Task 6.3: Conversation Lifecycle Operations |
| 485–501 | Task 6.4: Memory Context Injection |
| 504–543 | Task Dependency Graph (include full graph, filter QUERY tasks) |
| 546–572 | Task-to-Requirement Mapping (filter QUERY reqs) |

**Part B — Code Appendix:**

| Lines | Section |
|-------|---------|
| 575–576 | Part B header |
| 577–743 | B.1: Pre-Retrieval Guardrail Contract |
| 747–827 | B.2: Risk Classification Config Contract |
| 1335–1379 | B.8: Embedding Cache Pattern (REQ-306 → QUERY) |
| 1383–1467 | B.9: Query Result Cache Pattern (REQ-308 → QUERY) |
| 1471–1556 | B.10: Connection Pool Manager Pattern (REQ-307 → QUERY) |
| 1891–1975 | B.14: Multi-Turn Conversation State Pattern |
| 1979–2059 | B.15: Conversation Memory Provider Contract |
| 2068–2148 | B.16: Conversation Lifecycle Operations Pattern |
| 2157–2163 | Document Chain (adapt to QUERY companion refs) |

### RETRIEVAL_GENERATION_DESIGN.md (GENERATION sections)

**Part A — Task Overview:**

| Lines | Section |
|-------|---------|
| 1–26 | Document header (adapt title to GENERATION) |
| 54–72 | Task 1.2: Post-Generation Guardrail Layer |
| 75–92 | Task 1.3: Retry Logic for External LLM Calls (REQ-605 → GENERATION) |
| 118–135 | Task 2.1: 3-Signal Confidence Scoring |
| 138–156 | Task 2.2: Full-Pipeline LangGraph Routing |
| 182–199 | Task 3.1: Structured Document Formatter |
| 202–220 | Task 3.2: Version Conflict Detection |
| 222–240 | Task 3.3: PromptTemplate Integration |
| 327–346 | Task 4.4: Observability Instrumentation (REQ-801–803 → GENERATION) |
| 393–411 | Task 5.3: Post-Generation PII Filtering |
| 504–543 | Task Dependency Graph (include full graph, filter GENERATION tasks) |
| 546–572 | Task-to-Requirement Mapping (filter GENERATION reqs) |

**Part B — Code Appendix:**

| Lines | Section |
|-------|---------|
| 575–576 | Part B header |
| 831–941 | B.3: 3-Signal Confidence Scoring Contract |
| 945–1128 | B.4: Post-Generation Guardrail Contract |
| 1132–1215 | B.5: Version Conflict Detection Contract |
| 1219–1256 | B.6: Structured Document Formatter Pattern |
| 1260–1331 | B.7: Retry Logic Wrapper Contract (REQ-605 → GENERATION) |
| 1560–1604 | B.11: PromptTemplate Integration Pattern |
| 1608–1784 | B.12: Full-Pipeline LangGraph Definition Contract |
| 1788–1887 | B.13: Observability Wrapper Contract (REQ-801–803 → GENERATION) |
| 2157–2163 | Document Chain (adapt to GENERATION companion refs) |

> **Note on Phase 4 assignment:** Tasks 4.1 (Connection Pool, REQ-307), 4.2 (Embedding Cache, REQ-306), and 4.3 (Query Result Cache, REQ-308) belong entirely to QUERY_DESIGN — both their Part A task overviews and their Part B contracts (B.8, B.9, B.10). GENERATION_DESIGN includes only Task 4.4 (Observability, REQ-801–803).

---

## Appendix B: RETRIEVAL_IMPLEMENTATION.md Section Map

Source: 2612-line document, v1.2. Agent uses this table as a lookup — no judgment calls needed.

### RETRIEVAL_QUERY_IMPLEMENTATION.md (QUERY sections)

**Organizational sections:**

| Lines | Section |
|-------|---------|
| 1–22 | Document header (adapt title, spec references to QUERY only) |
| 24–82 | File Structure (QUERY files only — see file list below) |
| 85–158 | Dependency Graph (QUERY tasks only) |
| 160–182 | Task-to-Requirement Mapping (QUERY reqs only) |

**Phase 0 — Contract Definitions (QUERY contracts):**

| Lines | Section | Notes |
|-------|---------|-------|
| 185–191 | Phase 0 header | adapt |
| 193–410 | Task 0.1: Guardrail Types (QUERY portion: RiskLevel, GuardrailAction, GuardrailResult, validate_query()) | exclude PostGuardrailAction/PostGuardrailResult/evaluate_answer() |
| 1016–1152 | Task 0.5: Conversation Memory Types | full section |

**Phase A — Tests (QUERY test tasks):**

> Do NOT include: A-1.2 (1247–1305, post-gen guardrail → GEN), A-1.3 (1307–1341, retry → GEN), A-2.1 (1343–1393, confidence → GEN), A-2.2 (1395–1433, routing → GEN), A-3.1/3.2/3.3 (1465–1545, formatting/prompts → GEN), A-4.4 (1650–1676, observability → GEN).

| Lines | Section |
|-------|---------|
| 1160–1172 | Phase A header + preamble |
| 1174–1245 | Task A-1.1: Pre-Retrieval Guardrail Tests |
| 1436–1463 | Task A-2.3: Risk Classification Tests |
| 1547–1569 | Task A-3.4: Coreference Resolution Tests |
| 1572–1596 | Task A-4.1: Connection Pool Tests (REQ-307 → QUERY) |
| 1597–1621 | Task A-4.2: Embedding Cache Tests (REQ-306 → QUERY) |
| 1623–1648 | Task A-4.3: Query Result Cache Tests (REQ-308 → QUERY) |
| 1678–1705 | Task A-6.1: Memory Provider Tests |
| 1706–1731 | Task A-6.2: Memory Context Assembly Tests |
| 1733–1760 | Task A-6.3: Memory Lifecycle Tests |
| 1762–1784 | Task A-6.4: Memory Context Injection Tests |

**Phase B — Implementation (QUERY impl tasks):**

| Lines | Section |
|-------|---------|
| 1787–1792 | Phase B header |
| 1794–1822 | Task B-1.1: Pre-Retrieval Guardrail |
| 1932–1953 | Task B-2.3: Risk Classification |
| 2031–2055 | Task B-3.4: Multi-Turn Context / Coreference Resolution |
| 2057–2081 | Task B-4.1: Connection Pool Manager (REQ-307 → QUERY) |
| 2083–2107 | Task B-4.2: Embedding Cache (REQ-306 → QUERY) |
| 2109–2133 | Task B-4.3: Query Result Cache (REQ-308 → QUERY) |
| 2162–2186 | Task B-6.1: Conversation Memory Provider |
| 2188–2212 | Task B-6.2: Sliding Window and Rolling Summary |
| 2214–2240 | Task B-6.3: Conversation Lifecycle Operations |
| 2242–2266 | Task B-6.4: Memory Context Injection |

**Phase C/D/E (QUERY portions):**

| Lines | Section |
|-------|---------|
| 2269–2286 | Phase C header |
| 2350–2361 | Task C-6: Conversation Memory Module Doc |
| 2418–2434 | Task D-1.1: Pre-Retrieval Guardrail Coverage Tests |
| 2472–2488 | Task D-2.3: Risk Classification Coverage Tests |
| 2574–2593 | Phase E: Full Suite Verification (include, reference QUERY test suite) |
| 2595–2612 | Document Chain (adapt to QUERY companion refs) |

**QUERY source files (for File Structure section):**

```
src/retrieval/guardrails/__init__.py
src/retrieval/guardrails/pre_retrieval.py
src/retrieval/guardrails/types.py (QUERY types only)
src/retrieval/memory/__init__.py
src/retrieval/memory/types.py
src/retrieval/memory/provider.py
src/retrieval/memory/context.py
src/retrieval/memory/service.py
src/retrieval/memory/injection.py
src/retrieval/context_resolver.py
src/retrieval/pool.py
src/retrieval/cached_embeddings.py
src/retrieval/result_cache.py
config/guardrails.yaml (QUERY portion)
```

---

### RETRIEVAL_GENERATION_IMPLEMENTATION.md (GENERATION sections)

**Organizational sections:**

| Lines | Section |
|-------|---------|
| 1–22 | Document header (adapt title, spec references to GENERATION only) |
| 24–82 | File Structure (GENERATION files only — see file list below) |
| 85–158 | Dependency Graph (GENERATION tasks only) |
| 160–182 | Task-to-Requirement Mapping (GENERATION reqs only) |

**Phase 0 — Contract Definitions (GENERATION contracts):**

| Lines | Section | Notes |
|-------|---------|-------|
| 185–191 | Phase 0 header | adapt |
| 193–410 | Task 0.1: Guardrail Types (GENERATION portion: PostGuardrailAction, PostGuardrailResult, evaluate_answer()) | exclude RiskLevel/GuardrailAction/GuardrailResult/validate_query() |
| 412–628 | Task 0.2: Confidence Types and Scoring | full section |
| 631–786 | Task 0.3: Pipeline State and Retry (RAGPipelineState + with_retry()) | full section (REQ-706, REQ-605 → GENERATION) |
| 789–1013 | Task 0.4: Formatting Types and Observability | full section |

**Phase A — Tests (GENERATION test tasks):**

| Lines | Section |
|-------|---------|
| 1160–1172 | Phase A header + preamble |
| 1247–1305 | Task A-1.2: Post-Generation Guardrail Tests |
| 1307–1341 | Task A-1.3: Retry Logic Tests (REQ-605 → GENERATION) |
| 1343–1393 | Task A-2.1: Confidence Scoring Tests |
| 1395–1433 | Task A-2.2: Pipeline Routing Tests |
| 1465–1490 | Task A-3.1: Document Formatter Tests |
| 1492–1519 | Task A-3.2: Version Conflict Tests |
| 1521–1545 | Task A-3.3: Prompt Template Tests |
| 1650–1676 | Task A-4.4: Observability Tests (REQ-801–803 → GENERATION) |

**Phase B — Implementation (GENERATION impl tasks):**

| Lines | Section |
|-------|---------|
| 1787–1792 | Phase B header |
| 1824–1851 | Task B-1.2: Post-Generation Guardrail |
| 1853–1874 | Task B-1.3: Retry Logic (REQ-605 → GENERATION) |
| 1876–1899 | Task B-2.1: Confidence Scoring Engine |
| 1901–1930 | Task B-2.2: Full-Pipeline LangGraph Routing |
| 1955–1979 | Task B-3.1: Structured Document Formatter |
| 1981–2003 | Task B-3.2: Version Conflict Detection Integration |
| 2005–2029 | Task B-3.3: PromptTemplate Integration |
| 2135–2160 | Task B-4.4: Observability Instrumentation (REQ-801–803 → GENERATION) |

**Phase C/D/E (GENERATION portions):**

| Lines | Section |
|-------|---------|
| 2269–2286 | Phase C header |
| 2288–2300 | Task C-1: Guardrail Layer Module Doc |
| 2302–2312 | Task C-2: Confidence Engine Module Doc |
| 2314–2324 | Task C-3: Document Formatting Module Doc |
| 2326–2336 | Task C-4: Prompt Loading Module Doc |
| 2338–2348 | Task C-5: Observability Module Doc |
| 2362–2372 | Task C-7: Utilities Module Doc |
| 2374–2398 | Task C-cross: Assemble Engineering Guide |
| 2401–2416 | Phase D header |
| 2436–2452 | Task D-1.2: Post-Generation Guardrail Coverage Tests |
| 2454–2470 | Task D-2.1: Confidence Engine Coverage Tests |
| 2490–2506 | Task D-3.1: Document Formatter Coverage Tests |
| 2508–2524 | Task D-3.2: Version Conflicts Coverage Tests |
| 2526–2542 | Task D-3.3: Prompt Template Coverage Tests |
| 2544–2560 | Task D-4.4: Observability Coverage Tests |
| 2574–2593 | Phase E: Full Suite Verification (reference GENERATION test suite) |
| 2595–2612 | Document Chain (adapt to GENERATION companion refs) |

**GENERATION source files (for File Structure section):**

```
src/retrieval/guardrails/__init__.py
src/retrieval/guardrails/post_generation.py
src/retrieval/guardrails/types.py (GENERATION types only)
src/retrieval/confidence/__init__.py
src/retrieval/confidence/types.py
src/retrieval/confidence/scoring.py
src/retrieval/confidence/engine.py
src/retrieval/formatting/__init__.py
src/retrieval/formatting/types.py
src/retrieval/formatting/formatter.py
src/retrieval/formatting/conflicts.py
src/retrieval/observability/__init__.py
src/retrieval/observability/types.py
src/retrieval/observability/tracing.py
src/retrieval/pipeline_state.py
src/retrieval/retry.py
src/retrieval/prompt_loader.py
src/retrieval/pipeline.py (MODIFY existing)
config/guardrails.yaml (GENERATION portion)
```
