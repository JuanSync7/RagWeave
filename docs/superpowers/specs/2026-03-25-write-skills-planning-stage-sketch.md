# Design Sketch: write-* Skills Planning Stage Refactoring

**Date:** 2026-03-25
**Run:** 2026-03-25-write-skills-planning-stage
**Status:** Pending design_approval gate

---

## Goal Statement

Each write-* skill currently instructs a single agent to read all sources and write the full document in one pass. This causes context drift: sections written late in the document degrade in quality as the accumulated context grows. The fix is a two-stage model: a **Planning Stage** that reads all sources once and produces a `section_context_map` (dependency graph + inlined source + pre-constructed prompts), followed by an **Execution Stage** that drives section agents wave-by-wave using parallel-agents-dispatch. `write-implementation` and `write-module-tests` already follow this pattern and serve as reference implementations.

---

## Chosen Approach

**Approach A: Full Planning Stage + SDD loop for write-spec, write-design, write-engineering-guide (standalone); lightweight Planning Stage (scoped source, single-agent section-by-section) for write-spec-summary.**

Reasoning: Directly serves Correctness (fixes validated context drift) and Agent-Parallelizability (pre-constructed section prompts are complete handoff docs). write-spec-summary's short target length (150-250 lines) does not justify per-section dispatch overhead.

---

## Key Decisions

### 1. Planning Stage is non-skippable

Enforced via an explicit warning block at the top of each skill's Execution Stage: "Do not begin writing any section until the Planning Stage is complete and the `section_context_map` exists."

### 2. `section_context_map` is the Planning → Execution contract

Schema per section:
```
{
  id: string,                  # unique section identifier (e.g., "sec_scope", "sec_req_query")
  title: string,               # section title
  wave: int,                   # execution wave (1 = first)
  depends_on: [id, ...],       # section IDs that must be approved before this section starts
  model_tier: haiku|sonnet|opus,
  source_content: string,      # inlined source text (NOT a file path — agents never read files)
  prior_slots: [id, ...],      # which completed section outputs to inject into the prompt
  prompt: string               # pre-constructed prompt with {{slot_id}} markers for prior sections
}
```

The map is held in-session. Execution stage agents receive only their entry's `prompt` (with slots filled) — they never read source files.

### 3. Section dependency graphs are skill-specific

Each skill defines its own section ordering and wave groupings. These reflect the structural logic of each document type and are hardcoded in the skill (not configurable).

### 4. write-spec-summary gets Planning Stage without dispatch

The document is too short (150-250 lines) to justify per-section subagent overhead. The Planning Stage scopes what to read per section; a single agent executes section-by-section following the plan.

### 5. write-engineering-guide's parallel mode (Phase C from write-implementation) is unchanged

The Planning Stage is added only to standalone invocation. Phase C already has correct isolation with the right inputs. Adding a duplicate planning step would create confusion.

---

## Component / Module List

| Component | Where | Responsibility |
|-----------|-------|----------------|
| `PLANNING_STAGE` block | Each SKILL.md (new section) | Read sources once, produce `section_context_map` |
| `section_context_map` schema | Inline in each Planning Stage | Per-section: inlined source, dep graph, pre-constructed prompt |
| Per-skill section dependency graphs | Inline in each Planning Stage | Wave assignments specific to each document type |
| `EXECUTION_STAGE` protocol | Each SKILL.md (replaces "Writing Process") | Drive agents wave-by-wave via parallel-agents-dispatch |
| Non-skippable enforcement warning | Top of each Execution Stage | Prevent agents from skipping Planning Stage |

---

## Section Dependency Graphs

### write-spec

```
Wave 1 (foundation, parallel):
  - sec_scope:     Section 1 — Scope & Definitions
                   source: user-provided context + existing architecture docs
  - sec_overview:  Section 2 — System Overview
                   source: same as sec_scope

Wave 2 (requirement domains, parallel — one agent per functional domain):
  - sec_req_N:     Section 3+ — Requirement sections
                   source: scoped to each domain only
                   depends_on: [sec_scope, sec_overview]

Wave 3 (NFR):
  - sec_nfr:       Non-Functional Requirements
                   source: NFR-relevant context only
                   depends_on: [all Wave 2 sections]

Wave 4 (synthesis):
  - sec_matrix:    Traceability Matrix
                   source: list of all REQ-IDs from prior sections
                   depends_on: [all Wave 2 + Wave 3]
```

### write-design

```
Wave 1 (Part A — parallel per dependency tier from task graph):
  - task_tier_1_N: Tasks with no dependencies
                   source: relevant FRs + relevant codebase snippets (inlined)
  → review each → Wave 2 tasks can reference Wave 1 outputs

Wave 2 (Part A — next dependency tier, parallel):
  - task_tier_2_N: Tasks depending on Wave 1 outputs
                   depends_on: [relevant tier-1 tasks]

(Continue until all Part A tasks complete)

Wave N (Part B):
  - contracts:     Part B contract entries
                   source: Part A task list + relevant FRs
                   depends_on: [all Part A]
  - patterns:      Part B pattern entries
                   source: same

Wave Final:
  - traceability:  Task-to-FR traceability table
                   depends_on: [all Part A + all Part B]
```

### write-engineering-guide (standalone mode only)

```
Wave 1 (Module Reference — all parallel, isolated):
  - module_N:      One section per module
                   source: that module's source file(s) + spec FR numbers only
                   MUST NOT receive: other modules' source, test files

Wave 2 (cross-cutter — single agent, sequential):
  - cross_cut:     System Overview, Arch Decisions, Data Flow, Integration
                   Contracts, Testing Guide, Operational Notes, Known
                   Limitations, Extension Guide
                   source: all Wave 1 module section docs + spec only
                   MUST NOT receive: source files directly
                   depends_on: [all module_N]
```

### write-spec-summary (single-agent, plan-guided)

```
Phase 1:   §1 Generic System Overview
           source: full spec (synthesized — written from scratch)

Phase 2:   §2 Header, §3 Scope, §4 Architecture, §5 Requirements Framework,
           §6 Functional Domains, §7 NFR+Security, §8 Design Principles,
           §9 Key Decisions, §10 Acceptance/Evaluation, §11 External Dependencies
           source: scoped to relevant spec sections per §
           (single agent, executed sequentially with §1 output in context)

Phase 3:   §12 Companion Documents, §13 Sync Status
           source: document references section of spec
           (lightweight — no isolation needed)
```

---

## Scope Boundary

**In scope:**
- Adding Planning Stage to write-spec/SKILL.md
- Adding Planning Stage to write-design/SKILL.md
- Adding Planning Stage to write-engineering-guide/SKILL.md (standalone mode only)
- Adding lightweight Planning Stage to write-spec-summary/SKILL.md
- Defining `section_context_map` schema in each skill (inline, not shared file)
- Defining per-skill section dependency graphs
- Adding non-skippable enforcement warnings

**Out of scope:**
- write-implementation — already has correct pattern, not touched
- write-module-tests — already has correct pattern, not touched
- Changing the output format of any skill document
- Creating a shared Planning Stage library or base skill
- Modifying autonomous-orchestrator or parallel-agents-dispatch
- Adding configuration options to skills (section graphs are structural, not behavioral config)

---

## Reference Implementation Guide (for code agents)

**Before implementing any skill, code agents MUST read `/home/juansync7/.claude/skills/write-implementation/SKILL.md` as the structural reference.** The Planning Stage pattern added here mirrors write-implementation's agent isolation model exactly — same isolation contract format, same "Must NOT receive" clauses, same pre-constructed prompt discipline.

### Planning Stage section heading pattern

Add as a top-level `##` section, before the existing "Writing Process" or "Progress Tracking" section:

```markdown
## Planning Stage (NON-SKIPPABLE)
```

### Non-skippable enforcement block (use verbatim at top of Execution Stage)

Place this block at the very start of the Execution Stage section, before any dispatch instructions:

```markdown
> **NON-SKIPPABLE:** Do not write any section until the Planning Stage is complete
> and the `section_context_map` exists in session. If you are tempted to skip ahead
> because the system seems small or the sections seem obvious, resist. The map is
> the isolation guarantee — without it, agents receive unscoped context and context
> drift will degrade late sections.
```

### Example: pre-constructed prompt template inside a section_context_map entry

The `prompt` field in each section_context_map entry is a complete, self-contained string the agent receives as its full task. It must inline the source content — agents never read files:

```markdown
section_context_map entry for "sec_req_query":
  id: sec_req_query
  title: "Section 3.1 — Query Processing Requirements"
  wave: 2
  depends_on: [sec_scope, sec_overview]
  model_tier: sonnet
  source_content: |
    [INLINE: relevant spec sections and codebase excerpts for query processing,
     copied verbatim from the source docs during Planning Stage — NOT a file path]
  prior_slots: [sec_scope, sec_overview]
  prompt: |
    You are writing Section 3.1 — Query Processing Requirements for a formal spec.

    ## Your context (do NOT read any other files)

    ### Prior sections (already approved):
    {{sec_scope}}
    {{sec_overview}}

    ### Source material for this section:
    [source_content inlined here]

    ## Your task
    Write Section 3.1 covering [domain-specific instructions].
    Follow the REQ-xxx blockquote format. Every requirement needs Description,
    Rationale, and Acceptance Criteria.

    ## Constraints
    - You may ONLY write Section 3.1
    - Do NOT read any files — all context is above
    - Do NOT reference implementation details (HOW) — only requirements (WHAT/WHY)
```

### Structural consistency rule

All 4 skill files must produce Planning Stage sections that:
1. Use `## Planning Stage (NON-SKIPPABLE)` as the heading
2. Define `section_context_map` using the exact schema from Key Decision #2 above
3. List the per-skill dependency graph from the Section Dependency Graphs section above
4. End with "→ Proceed to Execution Stage once all entries have `prompt` fields populated"

The Execution Stage section replaces or wraps the existing "Writing Process" section and begins with the non-skippable enforcement block above.

---

## Open Questions

None — all resolved by prior conversation context and reference implementation (write-implementation) study.
