---
name: write-design
description: Writes a technical design document with task breakdown, contracts, and code appendix. Use when you have a spec and need to design the architecture before implementation. Triggered by requests like "write a design doc", "design this system", "break down the tasks", "create design document".
user-invocable: true
argument-hint: "[system/subsystem name] [optional: spec file path] [optional: output path]"
---

## Layer Context

This skill produces a **Layer 4 — Design Document** in the 5-layer doc hierarchy:

```
Layer 1: Platform Spec          (manual)
Layer 2: Spec Summary           ← write-spec-summary
Layer 3: Authoritative Spec     ← write-spec (required input — must exist)
Layer 4: Design Document        ← YOU ARE HERE (write-design)
Layer 5: Implementation Plan    ← write-implementation (consumes this document)
```

**Before writing, verify:**
- The companion spec (Layer 3) exists — read it completely before writing anything
- Every task must trace to at least one spec requirement (no orphan tasks)
- Every spec requirement must be covered by at least one task (no uncovered requirements)
- Task dependency graph must be a valid DAG — verify no circular dependencies before finalising

---

# Design Document Skill

**Announce at start:** "I'm using the write-design skill to create a technical design document."

You are writing a technical design document with task decomposition and a contract-grade code appendix. This document answers HOW to architect what the spec defines — component boundaries, data flow, schemas, and task ordering. It does NOT contain execution steps, test specifications, or Phase 0/A/B structure — that belongs in the downstream `write-implementation` skill.

**Output file naming:** `<SUBSYSTEM>_DESIGN.md` (e.g., `DOCUMENT_PROCESSING_DESIGN.md`)

**Downstream contract:** The `write-implementation` skill extracts this document's Part B contract entries verbatim into Phase 0. Contract entries must be complete enough that `write-implementation` can build the shared type surface without guessing or inventing fields.

## Scope Check

One design document per pipeline/subsystem. If the spec covers multiple independent subsystems (e.g., Document Processing and Embedding Pipeline), produce separate design documents. Each should be self-contained.

## Input Gathering

Before writing, you MUST have:

1. **A specification document** — Either a companion spec (written with `/write-spec` or similar) or inline requirements from the user.
2. **Architecture context** — Understanding of the system's components, data flow, and technology stack.
3. **Current state** — What exists today? What is being built from scratch vs. modified?

If the user provides `$ARGUMENTS`, treat the first argument as the system/subsystem name, the second (if provided) as the spec file path to read, and the third (if provided) as the output file path.

If a spec file path is provided, read it first to extract requirement IDs.

## Document Structure

The design document MUST follow the two-part structure defined in [template.md](template.md):

1. **Part A: Task-Oriented Overview** — Phased tasks with descriptions, requirements, dependencies, complexity, subtasks. Ends with dependency graph and task-to-requirement mapping table.
2. **Part B: Code Appendix** — Split into two subsection types:
   - **Contract entries** — complete, exact TypedDicts, dataclasses, stubs (consumed by `write-implementation` Phase 0)
   - **Pattern entries** — illustrative code snippets showing approach and key logic

Read the template file before writing to ensure exact formatting compliance.

## Task Format

Every task MUST use this exact format:

```markdown
### Task X.Y: [Descriptive Task Name]

**Description:** What to build. 1-2 sentences. Focus on the deliverable.

**Requirements Covered:** REQ-xxx, REQ-yyy, REQ-zzz

**Dependencies:** [Task references or "None"]

**Complexity:** S / M / L

**Subtasks:**
1. [Specific, actionable step]
2. [Specific, actionable step]
3. ...
```

### Example — Well-Written Task

### Task 2.1: Input Validation Guard

**Description:** Build a validation layer that rejects malformed requests before they reach the processing pipeline.

**Requirements Covered:** REQ-101, REQ-105

**Dependencies:** Task 1.2

**Complexity:** M

**Subtasks:**
1. Define a `ValidationResult` dataclass with `is_valid`, `error_code`, and `error_message` fields
2. Implement length checks (reject inputs exceeding 10,000 characters per REQ-101)
3. Implement encoding validation (reject non-UTF-8 input per REQ-105)
4. Wire validator as the first stage in the request pipeline
5. Return structured error response for rejected inputs

**Risks:** Edge cases in encoding detection for mixed-encoding payloads → mitigate with strict UTF-8 enforcement and explicit rejection.

**Testing Strategy:** Unit test each validation rule with boundary inputs (0, 9999, 10000, 10001 chars); integration test with the pipeline to verify rejected requests never reach downstream stages.

### Anti-Pattern — What NOT to Write

### Task 1: Setup

**Description:** Set up the project and get everything working.

**Requirements Covered:** All

**Dependencies:** None

**Complexity:** L

**Subtasks:**
1. Set up the project
2. Make it work
3. Test everything

**Problems:** Vague description (no deliverable), "All" is not traceable, subtasks are not actionable or verifiable, complexity is inflated because scope is undefined.

### Field Guidelines

- **Description**: What the task produces. Not how — the subtasks cover that.
- **Requirements Covered**: List the REQ-xxx IDs from the companion spec that this task satisfies.
- **Dependencies**: Reference other tasks by number (e.g., "Task 2.1"). If a task can start independently, write "None".
- **Complexity**:
  - **S** (Small) — Single module, straightforward logic, <1 day of work
  - **M** (Medium) — Multiple components or non-trivial logic, 1-3 days
  - **L** (Large) — Cross-cutting concern, multiple integrations, >3 days
- **Subtasks**: 3-6 specific steps. Each should be independently verifiable. Use imperative voice ("Implement...", "Define...", "Wire...").

### Optional Task Fields

Include these fields when they add value — omit when not applicable:

- **Risks:** For M and L tasks, note what could go wrong and the mitigation. Keep to 1-2 bullet points.
- **Testing Strategy:** Brief note on what kind of testing the task needs (unit, integration, end-to-end, load). Not test code — just the approach.
- **Migration Notes:** For tasks that modify existing behavior, note backward compatibility considerations, rollback steps, or feature flag requirements.

## Phase Organization

Group tasks into phases based on logical dependencies and delivery order:

1. **Foundation phases first** — Infrastructure, guardrails, validation, resilience
2. **Intelligence/logic phases next** — Scoring, routing, classification
3. **Quality improvement phases** — Formatting, conflict detection, template integration
4. **Performance & observability phases** — Caching, pooling, tracing
5. **Security hardening phases** — Data protection, injection patterns, PII filtering

Each phase should have:
- A descriptive name (not just "Phase 1")
- A 1-2 sentence description of its goal
- 2-5 tasks (avoid phases with a single task — merge or split)

## Task Dependency Graph

Include an ASCII dependency graph showing:
- All phases and their tasks
- Dependency arrows between tasks
- Which tasks can be parallelized
- **Critical path** — mark the longest dependency chain with `[CRITICAL]` annotation.

## Task-to-Requirement Mapping Table

At the end of Part A, include a complete mapping:

```markdown
| Task | Requirements Covered |
|------|---------------------|
| 1.1 Config Loader | REQ-903 |
| 1.2 Input Validation Guard | REQ-101, REQ-105 |
```

Verify completeness against the Cross-Verification Checklist.

## Code Appendix (Part B)

### Purpose

The code appendix serves two audiences:
1. **Developers** — understand the architecture, interfaces, and key patterns
2. **The `write-implementation` skill** — extracts contracts from Part B to build Phase 0 (the shared type surface that both test and implementation agents work against)

Because of audience #2, the code appendix has two subsection types:

### B.x: Contract Entries (TypedDicts, Dataclasses, Stubs)

Contract entries must be **complete and exact** — every field, every type annotation, every default value. The `write-implementation` skill copies these verbatim into Phase 0 of the execution plan. Incomplete contracts propagate errors into both test and implementation phases.

Contract entries include:
- **State TypedDicts** — every field with type and FR-tagged comment (e.g., `source_key: str  # FR-107`)
- **Config dataclasses** — frozen, with all defaults
- **Metadata/schema dataclasses** — all fields
- **Exception types** — with docstrings explaining when each is raised
- **Function signature stubs** — complete docstrings (args, returns, raises) with `raise NotImplementedError("Task B-X.Y")` bodies
- **Pure utility functions** — hash generators, ID derivation — fully implemented (no bias risk since they're deterministic)

Contract entries have NO line limit — completeness over brevity.

### B.x: Pattern Entries (Illustrative Code)

Pattern entries are **illustrative reference implementations** showing approach, interfaces, and key logic for complex components. These follow the existing guidelines:
- Target 50-120 lines per snippet
- Self-contained, understandable without reading other snippets
- Show the design pattern, not a full implementation

### Format for Each Appendix Entry

```markdown
## B.X: [Component Name — Contract|Pattern]

[1-2 sentence description of what this code does]

**Tasks:** Task X.Y, Task X.Z
**Requirements:** REQ-xxx, REQ-yyy
**Type:** Contract (exact) | Pattern (illustrative)
```

### Code Quality Standards

- **Match the project's language/stack** — adapt to the system's language
- Use **type annotations** throughout
- Use **structured types** for data (dataclasses, TypedDict, interfaces)
- Include **docstrings/comments** for classes and public functions
- Show **imports/dependencies** at the top of each snippet
- Use **realistic field names and values** from the domain
- Keep snippets **self-contained**
- Contract entries must have every field tagged with the spec requirement it satisfies (e.g., `# FR-107`)

### What to Include as Appendix Entries

Create an appendix entry for each of these (when applicable):
- **State TypedDicts with all fields** (contract entry)
- **Config and metadata dataclasses with defaults** (contract entry)
- **Exception type hierarchy** (contract entry)
- **Function signature stubs for all nodes/components** (contract entry)
- Major new classes/modules being introduced (pattern entry)
- Non-obvious algorithms or scoring functions (pattern entry)
- Pipeline/workflow graph definitions (pattern entry)
- Configuration file formats (pattern entry)
- Wrapper/decorator patterns (pattern entry)

### What NOT to Include

- Trivial CRUD operations
- Standard library usage that doesn't need illustration
- Test code (that belongs in `write-implementation` Phase A, not the design document)
- Phase 0/A/B execution structure (that belongs in `write-implementation`, not here)
- Checkbox steps, pytest commands, or commit instructions (execution concerns, not design)

## File Path Convention

The design document SHOULD reference concrete file paths for the target implementation layout. Unlike a pure architecture doc, this document feeds directly into `write-implementation`, which needs exact paths for Phase 0 contract files, Phase A test files, and Phase B source files.

- DO specify target file paths (e.g., `src/ingest/pipeline_types.py`, `src/ingest/nodes/chunking.py`)
- DO reference the companion spec by requirement IDs (REQ-xxx / FR-xxx)
- DO NOT reference current codebase internals that will be replaced — describe the target state
- A developer unfamiliar with the current codebase should be able to understand the design

## Cross-Verification Checklist

Before finalizing the document, verify:

- [ ] Every requirement from the spec is covered by at least one task
- [ ] Every task references at least one requirement
- [ ] Task dependencies form a valid DAG (no circular dependencies)
- [ ] The dependency graph matches the textual dependency fields
- [ ] Phase ordering respects dependencies (no phase depends on a later phase)
- [ ] Code appendix entries cover all L and M complexity tasks
- [ ] Code snippets are syntactically valid and match the project's language
- [ ] The task-to-requirement mapping table is complete
- [ ] Critical path is identified in the dependency graph
- [ ] Risks are noted for all L complexity tasks
- [ ] Contract entries (TypedDicts, dataclasses) include every field from the spec
- [ ] Every contract field has an FR-tagged comment
- [ ] Function stubs have complete docstrings (args, returns, raises)
- [ ] Pure utility functions are fully implemented, not stubs

## Additional Guidelines

- Use horizontal rules (`---`) between tasks and between phases
- Keep the tone technical and direct — no marketing language
- If a task is a subtask of another (broken out for clarity), note this explicitly
- If the system has an existing codebase, acknowledge what exists but frame tasks in terms of what needs to be built
- Consider adding a "Configuration Reference" appendix entry showing the full config file structure
- If the system involves a pipeline/workflow, include a graph definition appendix

## Integration

**Upstream (required before this skill):**
- `write-spec` — the companion spec must exist before writing a design document

**Downstream (invoke after this skill):**
- `write-implementation` — generates the Phase 0/A/B execution plan from this document

**Companion skills (use hand-in-hand during execution):**
- `superpowers:brainstorming` — if the user hasn't settled on an architecture yet, brainstorm first
- `superpowers:verification-before-completion` — before claiming the design doc is complete, verify the cross-verification checklist with evidence
- `superpowers:requesting-code-review` — dispatch a reviewer for the design document before handoff

**Chain handoff:** After saving the design document and completing the cross-verification checklist:

> "Design document complete and saved to `[path]`. Next step: invoke `/write-implementation [spec path] [this design doc path]` to generate the bias-free execution plan. Ready to proceed?"

## Document Chain

This skill is part of a 4-skill documentation chain. Each skill can be used independently, but they compose into a full pipeline:

```
write-spec  →  write-spec-summary  →  write-design  →  write-implementation
 _SPEC.md      _SPEC_SUMMARY.md       _DESIGN.md       _IMPLEMENTATION.md
```
