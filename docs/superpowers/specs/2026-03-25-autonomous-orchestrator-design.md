# Autonomous Orchestrator — Design Specification

> **For agentic workers:** This is a design spec for a Claude Code skill. Implementation uses the skill-creator workflow + write-skill-eval for quality gates.

**Goal:** Fully autonomous development pipeline that takes a goal, orchestrates existing skills through brainstorming → specs → design → implementation → docs, gated by stakeholder-reviewer at every transition. Human only intervenes on ESCALATE.

**Use case:** Kick off overnight, wake up to a working product + a list of provisional decisions to review.

---

## 1. Core Design Principles

1. **Agent is the expert** — makes decisions, explains reasoning, shows alternatives
2. **Smell-test every decision** — challenge assumptions, probe alternatives, question the obvious choice (taste). Before accepting any recommendation, ask: "does this feel over-engineered? under-explored? inelegant? is there a simpler version I'm not seeing?"
3. **Stakeholder-reviewer gates every transition** — iterative APPROVE/REVISE/ESCALATE loop at each stage boundary
4. **ESCALATE = queue and branch** — make best-effort provisional decision, tag downstream work, keep going. Human reviews provisionals on return.
5. **Checkpoint persistence** — crash-resilient state file. Session dies → resumes from last completed gate.
6. **Pipeline is a swappable port** — v1 uses predefined templates. Future versions swap in skill registry + router, eventual migration to LangGraph where each stage is a node. v1 itself becomes a node in LangGraph — additive migration, not a rewrite.

---

## 2. Relationship to Existing Skills

### Coexistence

- `superpowers:brainstorming` remains available for hands-on, human-in-the-loop brainstorming
- `autonomous-orchestrator` is the default path — fully autonomous with stakeholder gating
- User explicitly chooses `superpowers:brainstorming` when they want to steer directly

### Skills Orchestrated

The orchestrator is the conductor, not the orchestra. Each existing skill does its own job:

| Skill | Role in Pipeline |
|-------|-----------------|
| `stakeholder-reviewer` | Gates every stage transition (APPROVE/REVISE/ESCALATE) |
| `write-spec` | Produces formal requirements specification (Layer 3) |
| `write-spec-summary` | Produces concise spec digest (Layer 2) |
| `write-design` | Produces technical design with task decomposition (Layer 4) |
| `write-implementation` | Produces implementation plan (Layer 5) |
| `subagent-driven-development` | Executes implementation plan as code |
| `write-module-tests` | White-box tests for implemented modules |
| `write-engineering-guide` | Post-implementation documentation |

If any individual skill improves, the pipeline automatically benefits.

---

## 3. Pipeline Architecture

### Default Stage Sequence

```
┌─────────────┐     ┌────────────┐     ┌───────────────┐     ┌──────────────┐
│  Brainstorm  │────▶│    spec    │────▶│ spec-summary  │────▶│    design    │
│  (built-in)  │     │  (skill)   │     │   (skill)     │     │   (skill)    │
└─────────────┘     └────────────┘     └───────────────┘     └──────────────┘
       │                   │                   │                     │
       ▼                   ▼                   ▼                     ▼
  [gate: S-R]         [gate: S-R]         [gate: S-R]          [gate: S-R]
                                                                     │
                                                                     ▼
┌──────────────┐     ┌──────────────┐     ┌───────────────┐    ┌─────────────┐
│     impl     │────▶│     code     │────▶│   eng-guide   │───▶│    tests    │
│   (skill)    │     │   (skill)    │     │   (skill)     │    │   (skill)   │
└──────────────┘     └──────────────┘     └───────────────┘    └─────────────┘
       │                   │                     │                    │
       ▼                   ▼                     ▼                    ▼
  [gate: S-R]         [gate: S-R]           [gate: S-R]         [gate: S-R]
```

### Gate Logic (Every Transition)

```
Stage produces output
  → Self-critique ("smell test")
  → Stakeholder-reviewer evaluates
    → APPROVE → next stage
    → REVISE (+ FEEDBACK) → stage fixes → re-submit to gate (max 3 REVISE iterations)
    → ESCALATE → log question, make provisional call, tag downstream, continue
```

**REVISE loop bound:** If a stage receives 3 consecutive REVISE verdicts without reaching APPROVE, the gate escalates to the human. Three failed revisions means the stage is stuck — continuing to loop won't help.

**Failure handling:** If a stage throws an error (skill invocation fails, file not found, etc.):
- Status set to `failed` in checkpoint state
- Pipeline pauses and logs the failure with full context
- On resume: the failed stage restarts from scratch
- If the same stage fails 2 times consecutively, escalate to human

### Stage Interface (Swappable Port)

Every stage declares:

```yaml
stage:
  name: string            # canonical stage name (see Stage Registry below)
  skill: string | null    # skill to invoke (null for built-in stages)
  input_from: string      # which prior stage's output to consume
  output_type: string     # what this stage produces (see Inter-Stage Contracts below)
  output_path: string     # where the stage writes its artifact
  context_type: string    # stakeholder-reviewer context type for this gate
  skippable: bool         # can this stage be omitted via config?
  requires: list[string]  # stages that must have completed before this one runs
```

**Built-in stages** (like `brainstorm`) set `skill: null`. The orchestrator handles them directly rather than dispatching a skill. This is the only exception to the "every stage is a skill" pattern — it exists because brainstorming is the orchestrator's core capability, not a separable concern.

### Stage Registry (Canonical Name → Skill Mapping)

| Stage Name | Skill | Context Type | Output Type | Skippable |
|------------|-------|-------------|-------------|-----------|
| `brainstorm` | *(built-in)* | `approach_selection` (4b), `design_approval` (4c) | design sketch (markdown) | no |
| `spec` | `write-spec` | `spec_review` | formal spec (markdown) | yes |
| `spec-summary` | `write-spec-summary` | `spec_review` | spec digest (markdown) | yes |
| `design` | `write-design` | `design_approval` | technical design (markdown) | yes |
| `impl` | `write-implementation` | `design_approval` | implementation plan (markdown) | yes |
| `code` | `subagent-driven-development` | `code_review` | source code + tests | no |
| `eng-guide` | `write-engineering-guide` | `doc_review` | engineering guide (markdown) | yes |
| `tests` | `write-module-tests` | `code_review` | test files | yes |

**New context types for stakeholder-reviewer:**

- `code_review` — evaluates implementation output (source code, test results). Checks: does the code match the plan? Are tests passing? Does it introduce red flags (tight coupling, hardcoded values, silent error swallowing)?
- `doc_review` — evaluates post-implementation documentation (engineering guides). Checks: is the guide complete? Does it cover architecture, decision rationale, and component interactions? Is it standalone?

### Inter-Stage Contracts

Each stage produces a typed artifact that the next stage consumes:

| Producer → Consumer | Contract |
|---------------------|----------|
| `brainstorm` → `spec` | Design sketch: goal, chosen approach, key decisions, scope boundary, component list |
| `spec` → `spec-summary` | Formal spec document path (spec-summary reads and summarizes it) |
| `spec` → `design` | Formal spec document path (design reads spec to produce task decomposition) |
| `design` → `impl` | Technical design document path (impl reads design to produce implementation steps) |
| `impl` → `code` | Implementation plan document path (code executes the plan) |
| `code` → `eng-guide` | List of implemented source files + design doc path |
| `eng-guide` → `tests` | Engineering guide sections (error behavior, test guide) + Phase 0 contracts. `write-module-tests` derives tests from the guide, not from source files — deliberate isolation. |

**Fallback when stages are skipped:** When a stage is skipped, the next stage receives the most recent available artifact. For example, if `spec` is skipped, `design` receives the `brainstorm` output directly. The stage must handle this gracefully — a design sketch is less formal than a spec, and the stage should note the reduced input quality.

**Special case — `docs-only` template:** The `eng-guide` stage normally receives implemented source files from `code`. In the `docs-only` template (no `code` stage), `eng-guide` receives the spec/spec-summary output instead and writes a prospective engineering guide based on the specification rather than implemented code. The guide documents architecture, decisions, and component interactions as designed — not as built.

### Predefined Templates (v1)

| Template | Stages (canonical names) |
|----------|--------|
| `full` (default) | brainstorm → spec → spec-summary → design → impl → code → eng-guide → tests |
| `feature` | brainstorm → spec → design → impl → code → eng-guide → tests |
| `bugfix` | brainstorm → design → code → tests |
| `docs-only` | brainstorm → spec → spec-summary → eng-guide |

Overridable per-invocation: `--template bugfix` or `--stages brainstorm,design,code`

**Stage skip rules:** When using `--stages`, the orchestrator validates that required predecessors are present. If `code` is in the list, at least one of `impl` or `design` must also be present (code needs a plan). If validation fails, the orchestrator reports the missing dependency and asks for confirmation.

### Pipeline Evolution Path

```
v1: Predefined templates + flat stage list (now)
v2: Skill registry + router/grouping (tens of skills)
v3: LangGraph with dynamic routing, state, persistence (hundreds of skills)
```

v1 orchestrator becomes a node in v3 — migration is additive, not a rewrite.

---

## 4. Autonomous Brainstorming Phase

The built-in first stage. Replaces human Q&A with self-answering + validation.

### 4a. Context Gathering (no gate)

- Read project README, directory structure, recent commits
- Read codebase summaries (`@summary` blocks)
- Read existing docs in `docs/`
- Read stakeholder persona (global + project-level)
- Parse the input goal/brief

### 4b. Exploration & Approach Selection (gated)

```
Generate clarifying questions the brainstormer would normally ask a human
  → Self-answer each from context + persona + codebase
  → For each self-answer, smell-test:
      "Is this the obvious choice? What's the case against it?"
  → Produce 2-3 approaches with:
      - Recommendation + reasoning
      - Devil's advocate case for each non-recommended option
      - Explicit trade-offs
  → Stakeholder-reviewer evaluates (context_type: approach_selection)
    → APPROVE / REVISE / ESCALATE loop
```

### 4c. Design Sketch Production (gated)

The brainstorming phase produces a **design sketch** — not a full technical design. The sketch captures: the chosen approach, key architectural decisions, scope boundary, and component list. It is a lightweight artifact that feeds into the `write-spec` stage (or `write-design` if spec is skipped).

The full technical design with task decomposition, dependency graphs, and code appendix is produced later by the `write-design` skill. The brainstorm sketch is the "what and why," the design doc is the "how."

```
Write design sketch:
  → Goal statement + chosen approach
  → Key decisions with reasoning
  → Component/module list with responsibilities
  → Scope boundary (in/out)
  → Smell-test the overall sketch:
      "Does this feel over-engineered? Under-explored? Is there a simpler version?"
  → Stakeholder-reviewer evaluates (context_type: design_approval)
    → APPROVE / REVISE / ESCALATE loop
```

### Self-Critique Protocol

Before every stakeholder-reviewer submission, the brainstormer must:

1. State its recommendation
2. State the strongest counter-argument
3. Explain why it still recommends its choice despite the counter-argument

This is the "taste" mechanism — forces the brainstormer to earn its recommendation rather than rubber-stamp the first thing it generates.

---

## 5. ESCALATE Handling & Provisional Branching

### On ESCALATE

1. **Log the escalation:**
   - Which stage, which iteration
   - The ESCALATE_REASON (the question for the human)
   - Full context of what was being evaluated

2. **Make best-effort provisional call:**
   - Brainstormer picks the option most aligned with persona
   - Tags it as provisional with reasoning

3. **Continue the pipeline:**
   - All downstream work inherits the provisional tag
   - Checkpoint state records the branch point

4. **On human return:**
   - Present list of provisional decisions
   - For each: the question, the provisional call, the reasoning
   - Human APPROVE → remove provisional tag
   - Human OVERRIDE → discard downstream from that branch point, re-run from there

### Provisional State

```yaml
provisional_decisions:
  - stage: brainstorm
    iteration: 2
    question: "Should caching be per-user or global? Persona marks this as high-stakes infra."
    provisional_choice: "per-user — aligns with multi-tenant architecture in existing codebase"
    reasoning: "Codebase already has per-user scoping in auth layer, extending to cache is consistent"
    downstream_affected: [spec, design, impl, code]
```

### Max Provisional Limit

If the pipeline accumulates more than 3 unresolved ESCALATEs, it pauses. Too many provisional decisions stacking means the goal was likely under-specified — better to wait for human input than build on a shaky foundation.

---

## 6. Checkpoint Persistence

### State File

```yaml
# .autonomous/runs/<run-id>/state.yaml
run_id: "2026-03-25-api-caching"
template: full
input: "add caching to the API layer"
started: "2026-03-25T22:00:00Z"
provisional_decisions: []
stages:
  brainstorm:
    status: completed      # pending | in_progress | completed | failed | escalated
    output: "docs/superpowers/specs/2026-03-25-api-caching-design.md"
    verdict: APPROVE
    iterations: 2
    provisional: false
  spec:
    status: in_progress
    iterations: 1
```

### Status Transitions

```
pending → in_progress → completed
                     → failed (error during execution)
                     → escalated (3 REVISE loops exhausted or max provisionals hit)
```

### Resume Logic

Session dies → new session reads state file → resumes from first non-completed stage. Completed stages are not re-run. In-progress stages restart from the beginning of that stage (not mid-iteration). Failed stages retry from scratch on resume.

### Human Return UX

When the human returns (new session or responds to a paused pipeline):

1. Orchestrator reads the checkpoint state file
2. Presents a summary:
   - Stages completed, stages remaining
   - Provisional decisions (if any) — each with: the question, the provisional call, reasoning
   - Escalations awaiting input (if pipeline paused)
3. For each provisional decision, human responds: APPROVE or OVERRIDE
   - APPROVE → remove provisional tag, keep downstream work
   - OVERRIDE → discard downstream from that branch point, human provides direction, re-run from there
4. For escalations awaiting input, human answers the question, pipeline resumes

---

## 7. Stakeholder-Reviewer Enhancement

### Alternative Probing (new sub-step)

Add between existing step 3 (Decision Heuristics) and step 4 (Red Flags) in stakeholder-reviewer's evaluation sequence:

```
### 3b. Alternative Probing (approach_selection only)

When context_type is approach_selection and multiple options are presented:
- For each non-recommended option, check if any Decision Heuristic or Priority favors it
- If yes, REVISE with feedback: "Option [X] better matches [heuristic/priority].
  Justify why recommended option is still preferred, or switch."
- If no heuristic favors an alternative, proceed to step 4
```

This is targeted — only fires for `approach_selection`. All other context types behave exactly as before. Backward-compatible.

### New Context Types

The orchestrator introduces two new context types that stakeholder-reviewer must support:

| Context Type | When Used | Evaluation Focus |
|-------------|-----------|-----------------|
| `code_review` | After `code` and `tests` stages | Does code match the plan? Tests passing? Red flags (tight coupling, hardcoded values, silent failures)? |
| `doc_review` | After `eng-guide` stage | Is the guide complete? Covers architecture, decisions, component interactions? Standalone? |

These supplement the existing four types (`qa_answer`, `approach_selection`, `design_approval`, `spec_review`). The stakeholder-reviewer evaluation sequence applies identically — the context type only affects what the reviewer is looking at, not how it evaluates.

---

## 8. Input Contract

### Free Text

```
/autonomous-orchestrator "add caching to the API layer"
```

The orchestrator infers everything from context + codebase + persona.

### Structured Brief

```yaml
goal: "Add a caching layer to the API"
constraints:
  - Must support per-user cache isolation
  - Must not require Redis in dev environment
scope_boundary:
  entry: "API request handler"
  exit: "cached response returned"
stages: [brainstorm, spec, design, impl, code, tests]
template: feature  # or override with explicit stages list
```

Either input is accepted. The brief gives more control for higher-stakes overnight runs.

**Precedence:** `stages` and `template` are mutually exclusive. If both are provided, `stages` takes precedence (explicit override wins). If neither is provided, defaults to the `full` template.

---

## 9. Skill File Structure

```
~/.claude/skills/autonomous-orchestrator/
├── SKILL.md                    # Main skill — orchestrator logic, <500 lines
├── brainstorm-phase.md         # Companion: autonomous brainstorming sub-phases
├── pipeline-templates.md       # Companion: predefined templates + stage interface
├── stage-interface.md          # Companion: stage declaration contract + adding new stages
├── escalation-handler.md       # Companion: provisional branching + human review flow
├── brief-template.md           # Companion: structured brief template for rich input
└── EVAL.md                     # Generated later via write-skill-eval
```

SKILL.md is the conductor's score — high-level flow and decision points. Each companion file is a deep-dive read only when that phase is active. This keeps SKILL.md under 500 lines.

---

## 10. Implementation Scope

### In Scope (v1)

- Autonomous brainstorming phase with self-answering + smell-test
- Predefined pipeline templates (full, feature, bugfix, docs-only)
- Stakeholder-reviewer gating at every transition
- Provisional branching on ESCALATE (max 3)
- Checkpoint persistence + resume
- Stakeholder-reviewer enhancement (alternative probing for approach_selection)
- Free text + structured brief input

### Out of Scope (future)

- Skill registry with dynamic discovery
- Router/grouping for 100+ skills
- LangGraph migration
- Dynamic pipeline assembly (planner)
- Parallel stage execution
- Multi-project orchestration

### Dependencies

- `stakeholder-reviewer` skill (exists, needs alternative probing enhancement)
- `~/.claude/stakeholder.md` (exists, fully populated)
- All doc-authoring skills (exist)
- `subagent-driven-development` (superpowers plugin, exists)
