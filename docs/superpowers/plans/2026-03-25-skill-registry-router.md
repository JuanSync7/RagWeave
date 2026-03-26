# Skill Registry v2 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the flat `SKILLS_REGISTRY.md` and hardcoded pipeline templates with a hierarchical YAML registry and a goal-driven router in the autonomous-orchestrator.

**Architecture:** A recursive YAML tree (`SKILLS_REGISTRY.yaml`) stores all skill metadata including pipeline declarations. The autonomous-orchestrator's Phase 0 loads the tree and uses a 7-step router to assemble pipelines dynamically from the goal rather than from hardcoded templates. Presets survive as named fast-path shortcuts.

**Tech Stack:** YAML (registry), Markdown (skill SKILL.md files), no code changes — all changes are to Claude-read skill definition files.

**Spec:** `docs/superpowers/specs/2026-03-25-skill-registry-router-design.md`

---

## File Map

| File | Action | What changes |
|---|---|---|
| `.claude/skills/SKILLS_REGISTRY.yaml` | **Create** | New registry replacing SKILLS_REGISTRY.md |
| `.claude/skills/autonomous-orchestrator/SKILL.md` | **Modify** | Phase 0 + router algorithm replace template inference |
| `.claude/skills/autonomous-orchestrator/pipeline-templates.md` | **Modify** | Remove stage registry + preset definitions; keep contracts |
| `.claude/skills/autonomous-orchestrator/stage-interface.md` | **Modify** | Rewrite "How to Add a New Stage" to point to YAML |
| `.claude/skills/skill-creator/SKILL.md` | **Modify** | Add pipeline registration step after Phase 2 |
| `.claude/skills/SKILLS_REGISTRY.md` | **Delete** | Replaced by YAML |

---

## Task 1: Create SKILLS_REGISTRY.yaml

**Files:**
- Create: `.claude/skills/SKILLS_REGISTRY.yaml`

- [ ] **Step 1: Write the registry file**

Create `.claude/skills/SKILLS_REGISTRY.yaml` with the following content:

```yaml
# SKILLS_REGISTRY.yaml — v2
# Complete inventory of all skills. Single source of truth for pipeline metadata.
# Skills without a pipeline: block are present for inventory purposes only.
# Files without version: 2 are rejected by the autonomous-orchestrator with a clear error.

version: 2

# Built-in stages: executed directly by the orchestrator, not dispatched as skills.
# Only stage_name and output_type are required — input_type is absent (no predecessor).
# Listed here so the dependency resolver can find them when walking requires chains.
# context_types for brainstorm (approach_selection, design_approval) are defined
# in brainstorm-phase.md, not here — built_ins entries are for the dependency resolver only.
built_ins:
  - stage_name: brainstorm
    output_type: design_sketch

registry:
  - name: engineering
    summary: "Plan and build software: specs, design, implementation, code execution, documentation"
    children:
      - name: planning
        summary: "Pre-code artifacts that define what to build and how"
        children:
          - name: requirements
            summary: "Capture and formalize what the system must do"
            skills:
              - name: write-spec
                description: "Formal requirements spec with FRs, NFRs, acceptance criteria"
                pipeline:
                  stage_name: spec
                  input_type: design_sketch
                  output_type: formal_spec
                  context_type: spec_review
                  requires_all: [brainstorm]
                  skippable: true
              - name: write-spec-summary
                description: "Concise spec digest synced with companion spec"
                pipeline:
                  stage_name: spec-summary
                  input_type: formal_spec
                  output_type: spec_digest
                  context_type: spec_review
                  requires_all: [spec]
                  skippable: true
          - name: design
            summary: "Decompose requirements into tasks, contracts, and implementation plans"
            skills:
              - name: write-design-docs
                description: "Technical design with task decomposition and code contracts"
                pipeline:
                  stage_name: design
                  input_type: formal_spec
                  output_type: technical_design
                  context_type: design_approval
                  requires_all: [spec]
                  skippable: true
              - name: write-implementation-docs
                description: "Phased implementation plan from design doc (canonical impl stage)"
                pipeline:
                  stage_name: impl
                  input_type: technical_design
                  output_type: implementation_plan
                  context_type: design_approval
                  requires_all: [design]
                  skippable: true
              - name: write-implementation
                description: "Legacy implementation plan skill — superseded by write-implementation-docs for pipeline use; retained for direct invocation"
                # No pipeline block — not router-selectable

      - name: execution
        summary: "Run implementations via parallel and subagent-driven development"
        skills:
          - name: parallel-agents-dispatch
            description: "Execute implementation plan via parallel subagents (code stage)"
            pipeline:
              stage_name: code
              input_type: implementation_plan | technical_design
              output_type: source_code
              context_type: code_review
              requires_any: [impl, design]    # impl preferred; design accepted if impl skipped
              skippable: false

      - name: documentation
        summary: "Document what was built: engineering guides"
        skills:
          - name: write-engineering-guide
            description: "Post-implementation engineering guide"
            pipeline:
              stage_name: eng-guide
              input_type: source_code | spec_digest
              output_type: engineering_guide
              context_type: doc_review
              requires_any: [code, spec-summary]   # code in normal flow; spec-summary in docs-only
              skippable: true

  - name: quality
    summary: "Verify correctness: test planning, test implementation"
    children:
      - name: testing
        summary: "Write and implement tests from engineering artifacts"
        skills:
          - name: write-test-docs
            description: "Test planning document from engineering guide and spec"
            pipeline:
              stage_name: test-docs
              input_type: engineering_guide
              output_type: test_plan
              context_type: doc_review
              requires_all: [eng-guide]
              skippable: true
          - name: write-module-tests
            description: "Pytest test code from test plan (per-module)"
            pipeline:
              stage_name: tests
              input_type: test_plan
              output_type: test_files
              context_type: code_review
              requires_all: [test-docs]
              skippable: true

  - name: meta
    summary: "Skills about skills: create, evaluate, improve, orchestrate, animate"
    children:
      - name: skill-lifecycle
        summary: "Build and maintain skills"
        skills:
          - name: skill-creator
            description: "Creates new skills with EVAL.md and registry entry"
          - name: improve-skill
            description: "Karpathy-style score-fix-rescore loop for skill quality"
          - name: write-skill-eval
            description: "Generates EVAL.md with output criteria and test prompts"
          - name: generate-output-criteria
            description: "Generates binary pass/fail output criteria as impartial judge"
          - name: generate-test-prompts
            description: "Generates diverse test prompts blind to SKILL.md body"
          - name: doc-authoring
            description: "Router: directs to write-spec-summary, write-spec, or write-engineering-guide"
            # Not pipeline-routable: function subsumed by the v2 router for pipeline use.
            # Retained as a direct-invocation skill for single-artifact documentation requests.
      - name: orchestration
        summary: "Coordinate multi-skill workflows"
        skills:
          - name: autonomous-orchestrator
            description: "Fully autonomous dev pipeline with stakeholder gates"
          - name: stakeholder-reviewer
            description: "Evaluates decisions against stakeholder persona (APPROVE/REVISE/ESCALATE)"
      - name: creative
        summary: "Non-pipeline creative and visualization tools"
        skills:
          - name: create-animation-page
            description: "Single-page interactive animation as one HTML file with embedded CSS/JS"

presets:
  # Presets are trusted stage sequences — used as-is, bypassing dependency resolution
  # and type validation. This allows presets to intentionally skip stages whose
  # requires chain would otherwise force inclusion (e.g., bugfix skips spec despite
  # design.requires_all: [spec]).
  full:     [brainstorm, spec, spec-summary, design, impl, code, eng-guide, test-docs, tests]
  feature:  [brainstorm, spec, design, impl, code, eng-guide, test-docs, tests]
  bugfix:   [brainstorm, design, code]
  # bugfix drops tests vs v1 — inline tests produced by the code stage suffice for scoped fixes.
  # test-docs requires eng-guide which is not in bugfix scope.
  docs-only: [brainstorm, spec, spec-summary, eng-guide]
  # docs-only intentionally excludes test-docs — produces no test artifacts.
  # v2 change: full and feature now include test-docs before tests (new in v2).
  # v1 full was: [brainstorm, spec, spec-summary, design, impl, code, eng-guide, tests]
```

- [ ] **Step 2: Verify YAML structure**

Read the file back and check:
- All 4 presets reference only stage names that exist in `built_ins` or as `pipeline.stage_name` values in the tree
- No stage appears in two different `pipeline.stage_name` values (no duplicate stage names)
- All `requires_all`/`requires_any` values resolve to a known `stage_name` or `built_in`
- Walk the dependency graph mentally: brainstorm → spec → design → impl → code → eng-guide → test-docs → tests. Verify each stage's `requires` is satisfied by the preceding stages.

Expected: no gaps, no dangling references, no cycles.

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/SKILLS_REGISTRY.yaml
git commit -m "feat(skills): add SKILLS_REGISTRY.yaml — hierarchical skill registry v2"
```

---

## Task 2: Update autonomous-orchestrator/SKILL.md

**Files:**
- Modify: `.claude/skills/autonomous-orchestrator/SKILL.md`

This is the most complex change. The goal is to replace the hardcoded template inference block and the static Phase 0 with the new router algorithm (Steps 0–7) that reads `SKILLS_REGISTRY.yaml`.

- [ ] **Step 1: Replace the Template Inference section**

In `.claude/skills/autonomous-orchestrator/SKILL.md`, replace the entire **Template inference** block (lines 69-78, the section that reads `"When no --template or --stages is specified, infer the template from goal content before defaulting to full:"`) with the new Router Algorithm section. The full replacement:

Find this block:
```markdown
**Template inference:** When no `--template` or `--stages` is specified, infer the template from goal content before defaulting to `full`:
- Goal mentions "fix", "bug", "patch", "hotfix", or describes a defect → use `bugfix`
- Goal mentions "document", "docs only", "write docs" with no implementation intent → use `docs-only`
- Otherwise → use `full`
```

Replace with:
```markdown
**Router:** When no `--template` or `--stages` is specified, the router assembles the pipeline dynamically from `SKILLS_REGISTRY.yaml`. See **Router Algorithm** section below. `--template <name>` selects a named preset directly (fast path, skips traversal).
```

- [ ] **Step 2: Replace the --stages Validation block**

Find:
```markdown
**Validation:** If `--stages` is provided, check required predecessors:
- `code` requires at least one of: `impl`, `design`
- `tests` requires: `eng-guide`
- `spec-summary` requires: `spec`
- If validation fails, report the missing dependency and ask for confirmation before proceeding.
```

Replace with:
```markdown
**Validation:** If `--stages` is provided, run Steps 5–6 of the Router Algorithm (dependency resolution + type validation) against the explicit stage list. Do not run traversal (Steps 2–4). If dependency resolution adds stages the user did not list, surface the additions and ask for confirmation.
```

- [ ] **Step 3: Update Phase 0 to load the registry**

Find the Phase 0 section:
```markdown
### Phase 0: Initialize

1. Parse input (goal + template/stages + `--from` if present)
2. Generate run-id: `<YYYY-MM-DD>-<topic-slug>` where topic-slug is 2-4 lowercase hyphenated words derived from the goal (e.g., `2026-03-25-api-caching`, `2026-03-25-login-bug-fix`)
3. Create run directory: `.autonomous/runs/<run-id>/`
4. Write initial `state.yaml` — apply mid-pipeline injection rules from Input Parsing if triggered; otherwise set all stages to `pending`
5. Read stakeholder persona (global + project-level)

> **Read [`stage-interface.md`](stage-interface.md)** when adding a new stage or understanding the stage contract.
> **Read [`pipeline-templates.md`](pipeline-templates.md)** when resolving templates or looking up the stage registry.
```

Replace with:
```markdown
### Phase 0: Initialize

1. **Load registry** — Read `.claude/skills/SKILLS_REGISTRY.yaml`. Reject if `version` is missing or not `2`. Scan plugin directories for `REGISTRY_ENTRY.yaml` files; merge into the in-memory tree (in-memory only — never written back). On `stage_name` collision between plugins or with core registry, reject the colliding plugin entry and surface the conflict to the user.
2. **Assemble pipeline** — Run the Router Algorithm (see below) to determine the stage sequence for this run.
3. **Parse input** — goal + `--from` if present.
4. **Generate run-id** — `<YYYY-MM-DD>-<topic-slug>` where topic-slug is 2-4 lowercase hyphenated words derived from the goal.
5. **Create run directory** — `.autonomous/runs/<run-id>/`
6. **Write initial `state.yaml`** — apply mid-pipeline injection rules from Input Parsing if triggered; otherwise set all stages to `pending`.
7. **Read stakeholder persona** — global + project-level.

> **Read [`stage-interface.md`](stage-interface.md)** for field semantic definitions (input_from, output_path, context_type allowlist).
> **Read [`pipeline-templates.md`](pipeline-templates.md)** for fallback rules and inter-stage contracts.
```

- [ ] **Step 4: Add the Router Algorithm section**

Add a new `## Router Algorithm` section immediately before `## Checkpoint & Resume`. Full content:

```markdown
## Router Algorithm

Assembles the pipeline stage sequence from the goal. Runs during Phase 0 Step 2.

### Step 1 — Preset check (fast path)

Check whether the goal maps to a named preset using LLM judgment (not keyword matching alone):
- Strong fix/defect signal with no new-feature scope → `bugfix`
- Documentation intent with no implementation scope → `docs-only`

If matched, present to user: *"This looks like a `bugfix` pipeline: `brainstorm → design → code`. Proceed or customize?"*

**On preset confirmation: use the preset stage list as-is. Skip Steps 2–6 entirely.** Presets are trusted sequences — dependency resolution and type validation are skipped. If the user customizes (drops/adds stages), exit fast path and validate the custom list through Steps 5–6 only.

If goal is ambiguous, fall through to Step 2.

### Step 2 — Domain traversal (slow path)

Load only top-level `name` + `summary` fields from the registry. Reason over the goal: which domains are relevant?

The `meta` domain is a **hard filter** — never selected regardless of goal. `meta` skills are internal infrastructure. A goal like "build me a new skill" redirects to `skill-creator` directly rather than running through the pipeline router.

### Step 3 — Group drill-down

For each selected domain, load its children's `name` + `summary` fields. Select relevant groups.

### Step 4 — Skill selection

For each selected group, load individual skill entries (`name` + `description` + `pipeline:` block only — not full SKILL.md). Select pipeline-routable skills (those with a `pipeline:` block) based on goal relevance.

**Empty selection:** If Steps 2–4 produce zero pipeline-routable skills, inform the user that no matching stages were found and offer to fall back to a preset or accept a custom `--stages` list.

### Step 5 — Dependency resolution

**Cycle detection:** Before resolving, build the full dependency graph and check for cycles. If a cycle is detected, surface the cycle path and abort with an error.

Resolve missing dependencies:
- For `requires_all`: add all listed stages not yet selected.
- For `requires_any`: if none of the listed stages are selected, add the leftmost one only.
- A stage appearing in both `requires_all` and `requires_any` is satisfied by its `requires_all` presence.

Recurse until no new dependencies are added. Topological sort — tie-breaking by declaration order in the YAML (top-to-bottom).

**Example:**
```
selected:  [design, code, eng-guide]

round 1:
  design.requires_all=[spec]                  → add spec
  code.requires_any=[impl, design]            → design already selected, no-op
  eng-guide.requires_any=[code, spec-summary] → code already selected, no-op

round 2:
  spec.requires_all=[brainstorm]              → brainstorm is a built_in, add it

round 3: no new additions

sort: brainstorm → spec → design → code → eng-guide
```

### Step 6 — Type validation

For each stage in the sorted sequence, find its **feeding stage**: the most recently completed stage whose `output_type` matches any type in this stage's `input_type` (per the requires graph, not necessarily the immediately preceding position). On mismatch where no predecessor produces a matching type, surface a warning and ask for confirmation.

### Step 7 — Present and confirm

```
Assembled pipeline for "add Redis caching":
  brainstorm → spec → design → impl → code → eng-guide

Matches preset `feature`. Proceed, or adjust stages?
```

User can drop stages, add stages, or confirm. `--stages` bypasses the router entirely; the explicit list goes through Steps 5–6 only.
```

- [ ] **Step 5: Update Core Principle #6 and Pipeline Evolution**

Find:
```markdown
6. **Pipeline is a swappable port** — predefined templates now, registry/LangGraph later
```

Replace with:
```markdown
6. **Pipeline is a swappable port** — hierarchical skill registry now, LangGraph later
```

Find:
```markdown
```
v1:  Predefined templates + flat stage list
v2:  Skill registry + router/grouping
v3:  LangGraph — each stage is a node, orchestrator becomes a subgraph
```
```

Replace with:
```markdown
```
v1:  Predefined templates + flat stage list          [done]
v2:  Hierarchical skill registry + dynamic router    [current]
v3:  LangGraph — each stage is a node, orchestrator becomes a subgraph
```
```

- [ ] **Step 6: Verify the updated SKILL.md**

Read the file and check:
- Phase 0 Step 1 references `SKILLS_REGISTRY.yaml`
- Router Algorithm section exists with all 7 steps
- No remaining references to hardcoded template inference logic
- `pipeline-templates.md` reference now says "fallback rules and inter-stage contracts" only

- [ ] **Step 7: Commit**

```bash
git add .claude/skills/autonomous-orchestrator/SKILL.md
git commit -m "feat(orchestrator): replace template inference with SKILLS_REGISTRY.yaml router (v2)"
```

---

## Task 3: Slim pipeline-templates.md

**Files:**
- Modify: `.claude/skills/autonomous-orchestrator/pipeline-templates.md`

Remove the Stage Registry table and Predefined Templates section (now in `SKILLS_REGISTRY.yaml`). Keep: Inter-Stage Contracts, Fallback Rules, Stage Skip Validation.

- [ ] **Step 1: Remove the Stage Registry and Predefined Templates sections**

The current file has these sections to remove:
- `## Stage Registry` (the table mapping stage names to skills)
- `## Predefined Templates` (the table + "When to Use Each Template" subsection)

Replace the entire file header + those two sections with:

```markdown
# Pipeline Contracts & Fallback Rules

Stage metadata (stage names, skill mappings, pipeline declarations, presets) is now in
`.claude/skills/SKILLS_REGISTRY.yaml`. This file contains only:
- Inter-stage artifact contracts (what each stage produces and what the next expects)
- Fallback rules for skipped stages
- Stage skip validation rules (superseded by SKILLS_REGISTRY.yaml `requires` — kept for reference)
```

Keep the remaining sections unchanged:
- `## Inter-Stage Contracts` (the producer → consumer table)
- `## Fallback Rules`
- `## Stage Skip Validation`

- [ ] **Step 2: Verify**

Read the slimmed file and confirm:
- No stage registry table remains
- No predefined templates table remains
- Inter-Stage Contracts table is intact
- Fallback Rules section is intact

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/autonomous-orchestrator/pipeline-templates.md
git commit -m "refactor(orchestrator): remove stage registry and presets from pipeline-templates.md (now in SKILLS_REGISTRY.yaml)"
```

---

## Task 4: Update stage-interface.md

**Files:**
- Modify: `.claude/skills/autonomous-orchestrator/stage-interface.md`

Rewrite the "How to Add a New Stage" section. Keep all other sections (field definitions, Built-In Stage Exception, context_type list).

- [ ] **Step 1: Rewrite "How to Add a New Stage"**

Find the current section:
```markdown
## How to Add a New Stage

1. **Define the stage declaration** using the YAML contract above
2. **Add it to the Stage Registry** in `pipeline-templates.md`
3. **Define the inter-stage contract** — what does it receive and what does it produce?
4. **Add it to relevant templates** — or create a new template that includes it
5. **Ensure the skill exists** — the stage's `skill` value must be a valid, installed skill
6. **Add the context_type** — if using a new context type, define its evaluation semantics in stakeholder-reviewer

No changes to SKILL.md or the orchestrator logic are needed — the pipeline reads from templates and the stage registry. This is the "swappable port" principle in action.
```

Replace with:
```markdown
## How to Add a New Stage

1. **Create the skill** — run `/skill-creator` to build the skill directory and SKILL.md.
2. **Register in SKILLS_REGISTRY.yaml** — `skill-creator` prompts for pipeline metadata and appends the entry. If adding manually, declare a `pipeline:` block under the correct domain/group with: `stage_name`, `input_type`, `output_type`, `context_type`, `requires_all`/`requires_any`, `skippable`.
3. **Define the inter-stage contract** in `pipeline-templates.md` — what artifact does it receive, what does it produce?
4. **Add to presets if appropriate** — update the `presets:` section in `SKILLS_REGISTRY.yaml` for any named pipeline that should include this stage.
5. **Verify** — confirm `stage_name` is unique in the registry, `requires` references resolve, and at least one preset or goal type would route to it.

No changes to orchestrator SKILL.md are needed — the router reads from `SKILLS_REGISTRY.yaml` dynamically.
```

- [ ] **Step 2: Add plugin registration schema**

Append a new section at the end of `stage-interface.md` so plugin authors know how to declare routable stages:

```markdown
## Plugin Stage Registration

Skills from external plugins (outside `.claude/skills/`) may declare a `REGISTRY_ENTRY.yaml`
in their skill directory to make themselves routable by the autonomous-orchestrator:

```yaml
version: 2           # required; rejected if absent or mismatched
name: my-custom-skill
description: "Does X for Y"
domain: engineering  # top-level domain to merge into
group: planning      # group within that domain
pipeline:
  stage_name: custom-stage
  input_type: formal_spec
  output_type: custom_artifact
  context_type: design_approval
  requires_all: [spec]
  skippable: true
```

The orchestrator merges plugin entries in-memory during Phase 0. They are **never written
back to `SKILLS_REGISTRY.yaml`**. If a plugin declares a `stage_name` that collides with
an existing registry entry, the plugin entry is rejected and the user is notified.

Plugin skills without a `REGISTRY_ENTRY.yaml` are not routable — no error, they simply
won't appear in assembled pipelines.
```

- [ ] **Step 3: Verify**

Read the file. Confirm:
- "How to Add a New Stage" no longer references `pipeline-templates.md` for stage registration
- Field definitions section (stage declaration YAML) is still present
- Built-In Stage Exception section is still present
- Plugin Stage Registration section is present at the end

- [ ] **Step 4: Commit**

```bash
git add .claude/skills/autonomous-orchestrator/stage-interface.md
git commit -m "docs(orchestrator): update stage-interface.md — new stage process + plugin REGISTRY_ENTRY.yaml schema"
```

---

## Task 5: Update skill-creator/SKILL.md

**Files:**
- Modify: `.claude/skills/skill-creator/SKILL.md`

Add a pipeline registration step after Phase 2 (Write the Skill). This is a new Phase 2.5.

- [ ] **Step 1: Add Phase 2.5 — Pipeline Registration**

In `.claude/skills/skill-creator/SKILL.md`, after the Phase 2 section (which ends with the SKILL.md Frontmatter and Writing Principles subsections), insert a new section:

```markdown
### Phase 2.5: Pipeline Registration

After writing the SKILL.md, determine if the skill should be pipeline-routable:

> "Is this skill a pipeline stage — should it appear in assembled pipelines when the orchestrator routes goals? (yes/no)"

If **no**: skip this phase. The skill will appear in `SKILLS_REGISTRY.yaml` without a `pipeline:` block (inventory only, not router-selectable).

If **yes**, collect the following and append the entry to `SKILLS_REGISTRY.yaml` under the correct domain/group:

| Field | Prompt | Notes |
|---|---|---|
| `domain` | Which top-level domain? (engineering/quality/meta) | Create a new domain if none fits |
| `group` | Which group within that domain? | Create a new group with a summary if none fits |
| `stage_name` | Short canonical ID used in `--stages` and presets | Must be unique across the entire registry |
| `input_type` | What artifact does this stage consume? | Use `\|` for union (any one satisfies) |
| `output_type` | What artifact does this stage produce? | Single type only |
| `context_type` | Stakeholder-reviewer gate type | Must be one of: `qa_answer`, `approach_selection`, `design_approval`, `spec_review`, `code_review`, `doc_review` |
| `requires_all` | Stage names that ALL must complete before this one | Use for hard sequential dependencies |
| `requires_any` | Stage names where AT LEAST ONE must complete | Use when multiple upstream paths are valid |
| `skippable` | Can this stage be omitted from a pipeline? | `false` for stages that produce core artifacts |

**YAML entry to append:**
```yaml
          - name: <skill-name>
            description: "<one-line description>"
            pipeline:
              stage_name: <stage-name>
              input_type: <type>
              output_type: <type>
              context_type: <type>
              requires_all: [<stage>, ...]   # omit if empty
              requires_any: [<stage>, ...]   # omit if empty
              skippable: true | false
```

After appending, verify:
- `stage_name` is unique (no collision with existing entries)
- All `requires_all`/`requires_any` values resolve to a known `stage_name` or `built_in`
- The `context_type` is in the allowed list

Show the user the appended entry and confirm.
```

Also update the Progress Tracking task list at the top of `skill-creator/SKILL.md` to include the new phase:

Find:
```markdown
TaskCreate: "Phase 1: Understand — capture intent, triggers, output, siblings"
TaskCreate: "Phase 1.5: Baseline test"
TaskCreate: "Phase 2: Write the skill"
TaskCreate: "Phase 3: Generate test prompts"
TaskCreate: "Phase 4: Generate output criteria"
TaskCreate: "Phase 5: Assemble EVAL.md"
TaskCreate: "Phase 6-7: Validate and iterate"
```

Replace with:
```markdown
TaskCreate: "Phase 1: Understand — capture intent, triggers, output, siblings"
TaskCreate: "Phase 1.5: Baseline test"
TaskCreate: "Phase 2: Write the skill"
TaskCreate: "Phase 2.5: Pipeline registration — add to SKILLS_REGISTRY.yaml"
TaskCreate: "Phase 3: Generate test prompts"
TaskCreate: "Phase 4: Generate output criteria"
TaskCreate: "Phase 5: Assemble EVAL.md"
TaskCreate: "Phase 6-7: Validate and iterate"
```

- [ ] **Step 2: Verify**

Read the updated file. Confirm:
- Phase 2.5 section exists between Phase 2 and Phase 3
- Task list includes Phase 2.5
- The YAML template in Phase 2.5 is syntactically valid
- The context_type allowlist is correct

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/skill-creator/SKILL.md
git commit -m "feat(skill-creator): add Phase 2.5 — pipeline registration in SKILLS_REGISTRY.yaml"
```

---

## Task 6: Delete SKILLS_REGISTRY.md

**Files:**
- Delete: `.claude/skills/SKILLS_REGISTRY.md`

Only run this task after verifying Tasks 1–5 are complete.

- [ ] **Step 1: Final cross-check before deletion**

Verify:
- `.claude/skills/SKILLS_REGISTRY.yaml` exists and contains all 16 skills from the old `SKILLS_REGISTRY.md` plus `write-test-docs` (the old file has 16 rows in its Skills Table)
- `autonomous-orchestrator/SKILL.md` Phase 0 references `SKILLS_REGISTRY.yaml` (not `SKILLS_REGISTRY.md`)
- No other skill files reference `SKILLS_REGISTRY.md` by name

Run:
```
grep -r "SKILLS_REGISTRY.md" .claude/skills/
```
Expected: zero results (or only the file itself).

- [ ] **Step 2: Delete the file**

```bash
git rm .claude/skills/SKILLS_REGISTRY.md
git commit -m "chore(skills): delete SKILLS_REGISTRY.md — replaced by SKILLS_REGISTRY.yaml"
```

---

## Verification Checklist

After all tasks complete:

- [ ] `SKILLS_REGISTRY.yaml` parses as valid YAML with no duplicate `stage_name` values
- [ ] All 4 presets in YAML resolve to known stage names
- [ ] Dependency walk: brainstorm → spec → design → impl → code → eng-guide → test-docs → tests — each stage's `requires` satisfied by the chain
- [ ] `autonomous-orchestrator/SKILL.md` contains Router Algorithm section with Steps 1–7
- [ ] `pipeline-templates.md` contains no stage registry table and no preset definitions
- [ ] `stage-interface.md` "How to Add a New Stage" points to `SKILLS_REGISTRY.yaml`
- [ ] `skill-creator/SKILL.md` contains Phase 2.5 and updated task list
- [ ] `SKILLS_REGISTRY.md` is deleted
- [ ] Dry-run: trace through a goal of "add Redis caching" — router should assemble `feature` preset stages
