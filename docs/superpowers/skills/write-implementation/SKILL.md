---
name: write-implementation
description: Use when you have a spec AND a design document and need a bias-free implementation plan with isolated test and implementation phases, before touching code
user-invocable: true
argument-hint: "[path to spec] [path to design document]"
---

# Write Implementation Plan

## Overview

Generate three-phase implementation plans that prevent test bias through agent context isolation. The plan separates contract definition, test writing, and implementation into phases with explicit information barriers — the test agent never sees implementation code, and the implementation agent works against pre-written tests it didn't author.

This skill extends the `writing-plans` pattern (checkboxes, exact file paths, bite-sized steps, TDD) with a structural guarantee: **no single agent context ever holds both the test logic and the implementation logic for the same component.**

**Why this matters:** When the same agent writes both test and implementation, it writes tests that validate its own mental model — not the spec's requirements. Separating them forces the test agent to derive test cases from the contract and spec alone, producing tests that are an independent verification rather than a mirror of the implementation.

**Announce at start:** "I'm using the write-implementation skill to create a bias-free implementation plan."

**Input requirements:**
1. A spec document (or spec summary) — the source of truth for requirements
2. A design document (from `write-design` or equivalent) — task decomposition, contracts, dependencies

**Save plans to:** `docs/superpowers/plans/YYYY-MM-DD-<feature-name>.md`
- User preferences for plan location override this default.

## Layer Context

```
Layer 1: Platform Spec          (manual)
Layer 2: Spec Summary           ← write-spec-summary
Layer 3: Authoritative Spec     ← write-spec (required input)
Layer 4: Design Document        ← write-design (required input)
Layer 5: Implementation Plan    ← YOU ARE HERE (write-implementation)
```

## When to Use This vs. writing-plans

| | `write-implementation` (this skill) | `writing-plans` |
|---|---|---|
| **Input** | Spec + design document pair | Spec or requirements alone |
| **Output** | Three-phase plan (Phase 0/A/B) with isolation | Interleaved test+implement per task |
| **Agent model** | Multi-agent with context barriers | Single-agent TDD |
| **Best for** | Larger systems, when bias prevention matters | Small features, quick tasks |

The discriminator: **do you have a design document from `write-design`?** If yes → this skill. If just a spec or feature request → `writing-plans`.

## Scope Check

One plan per pipeline/subsystem. If the input covers multiple independent subsystems, produce separate plans.

## The Three Phases

```
Phase 0: Contracts ──► [REVIEW GATE] ──► Phase A: Tests ──► Phase B: Implementation
     │                      │                   │                    │
     │ Defines:             │ Human reviews     │ Agent receives:    │ Agent receives:
     │ • TypedDicts         │ schemas before    │ • Spec reqs only   │ • Task description
     │ • Dataclasses        │ proceeding        │ • Phase 0 contracts│ • Phase A test file
     │ • Function stubs     │                   │ • Task description │ • Phase 0 contracts
     │ • Exceptions         │                   │                    │
     │                      │                   │ Must NOT receive:  │ Must NOT receive:
     │                      │                   │ • Any impl code    │ • Other task tests
     │                      │                   │ • Code appendix    │
     └──────────────────────┘                   └────────────────────┘
```

### Phase 0 — Contract Definitions

Extract contracts from the design document's Code Appendix (Part B, Contract entries) and organize them into implementable files. This is the shared type surface both test and implementation agents work against.

**What it contains:**
- State TypedDicts — copied from design doc contract entries
- Config dataclasses — copied from design doc contract entries
- Exception types — copied from design doc contract entries
- Function signature stubs — bodies are `raise NotImplementedError("Task B-X.Y")`
- Pure utility functions — copied fully implemented from design doc

**Phase 0 code is complete, copy-pasteable Python.** It comes from the design doc's contract entries — the plan organizes them into file-by-file creation steps.

**Review gate:** Phase 0 must be human-reviewed before Phase A begins.

### Phase A — Tests (Isolated from Implementation)

Write test specifications that verify spec requirements using only contracts and spec — never implementation knowledge.

**The isolation contract — include verbatim at the top of Phase A:**

```markdown
**Agent isolation contract:** The test agent receives ONLY:
1. The spec requirements (FR numbers + acceptance criteria)
2. The contract files from Phase 0 (TypedDicts, signatures, exceptions)
3. The task description from the design document

**Must NOT receive:** Any implementation code, any pattern entries from the
design doc's code appendix, any source files beyond Phase 0 stubs.
```

Each Phase A task specifies:
1. **"Agent input (ONLY these):"** — exact FR numbers with brief descriptions, exact contract file paths
2. **"Must NOT receive:"** — explicit list of forbidden files/directories
3. **"Files:" → Create:** — exact test file path
4. **Test cases** — bulleted list tagged with FR numbers
5. **Pytest command** with expected FAIL outcome

**Why test cases are listed but not pre-coded:** The plan specifies *what* to test (from spec). The test agent writes *how*. Pre-coded tests would reflect the plan author's bias from having read the design doc's pattern entries.

**All Phase A tasks can run in parallel.**

### Phase B — Implementation (Against Tests)

Each Phase B task specifies:
1. **"Agent input:"** — task description from design doc, specific Phase A test file, Phase 0 contracts, FR numbers
2. **"Must NOT receive:"** — test files for OTHER tasks
3. **"Files:" → Modify:** — exact source file path
4. **Implementation steps** — bite-sized, FR-tagged
5. **Pytest command** with expected ALL PASS
6. **Commit step**

Phase B follows the dependency graph from the design document.

## Plan Document Format

### Header

```markdown
# [Feature Name] — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** [One sentence]

**Architecture:** [2-3 sentences]

**Tech Stack:** [Key technologies]

---
```

### File Structure Section

> **Read [`templates/plan-template.md`](templates/plan-template.md)** for the complete template.

Map all files organized by phase:

```markdown
## File Structure

### Contracts (Phase 0)
[files with CREATE/MODIFY annotations]

### Source (Phase B — stubs become implementations)
[source files]

### Tests (Phase A)
[test files with CREATE annotations]
```

### Dependency Graph

ASCII graph showing Phase 0 → review gate → Phase A (parallel) → Phase B (critical path + parallel).

### Task-to-Requirement Mapping Table

Table mapping each task to: Phase 0 contracts, Phase A test file, Phase B source file, FR numbers.

## Deriving Phase 0 from the Design Document

The design document's Part B contains two types of entries:
- **Contract entries** (TypedDicts, dataclasses, stubs) → copy verbatim into Phase 0
- **Pattern entries** (illustrative code) → do NOT copy; these inform Phase B but must not leak to Phase A

If the design doc lacks contract entries, derive them from task descriptions and spec requirements.

## Review Loop

After writing, dispatch a reviewer:

> **Read [`references/reviewer-prompt.md`](references/reviewer-prompt.md)** for the dispatch template.

The reviewer checks:
- Every spec requirement in at least one Phase A test task
- Every Phase A task has "Must NOT receive" clause
- Every Phase B task references its Phase A test file
- Phase 0 contracts match the design doc's contract entries
- Dependency graph matches the design doc

Max 3 iterations before surfacing to human.

## Execution Handoff

**"Plan complete. Three execution phases:**

**Phase 0:** Implement contracts in this session (human review before proceeding).

**Phase A:** Dispatch one test agent per task in parallel. Each receives ONLY its listed 'Agent input'.

**Phase B:** Dispatch implementation agents following the dependency graph. Each receives ONLY its task + test file + contracts.

**Ready to start with Phase 0?"**

## Common Mistakes

| Mistake | Consequence | Fix |
|---------|------------|-----|
| Phase A agent receives pattern entries | Tests mirror reference implementation | Only pass FR numbers + contract entries |
| Phase 0 stubs have implementation hints | Implementation agent biased | Stubs: signature + docstring + NotImplementedError only |
| Phase A test cases lack FR tags | Can't verify spec coverage | Every bullet references an FR number |
| Phase B task receives other tasks' tests | Shaped by unrelated expectations | Each agent gets ONLY its own test file |
| Phase 0 skips review gate | Bad contracts propagate | Always announce review gate |
| Pure utilities left as stubs | Block both phases | Copy fully implemented from design doc |

## Integration

**Upstream (required before this skill):**
- `write-spec` — the companion spec must exist (source of FR numbers for Phase A)
- `write-design` — the design document must exist (source of tasks, contracts, dependencies)

**Companion skills (use hand-in-hand during execution):**
- `superpowers:subagent-driven-development` — dispatches Phase A test agents and Phase B implementation agents with two-stage review (spec compliance then code quality)
- `superpowers:verification-before-completion` — Phase B agents must show pytest evidence before claiming "ALL PASS"
- `superpowers:using-git-worktrees` — Phase B agents should work in isolated worktrees
- `superpowers:requesting-code-review` — dispatch a final reviewer after all Phase B tasks complete
- `superpowers:finishing-a-development-branch` — after all tasks pass, handle merge/PR/cleanup

**Agent dispatch guidance:** When dispatching Phase A/B subagents, provide full task text in the prompt — do not make agents read the plan file. The controller curates exactly what each agent sees, which is how the isolation contract is enforced.

## Document Chain

This skill is part of a 4-skill documentation chain. Each skill can be used independently, but they compose into a full pipeline:

```
write-spec  →  write-spec-summary  →  write-design  →  write-implementation
 _SPEC.md      _SPEC_SUMMARY.md       _DESIGN.md       _IMPLEMENTATION.md
```
