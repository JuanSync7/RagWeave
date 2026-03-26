# Design: Skill Registry v2 — Hierarchical Registry & Dynamic Pipeline Router

**Date:** 2026-03-25
**Topic:** Replace flat `SKILLS_REGISTRY.md` with a recursive YAML tree and upgrade the autonomous-orchestrator to use a goal-driven router instead of hardcoded templates.

---

## Problem Statement

The current `autonomous-orchestrator` uses a fixed set of templates (`full`, `feature`, `bugfix`, `docs-only`) to assemble pipelines. This breaks down at scale:

1. **Template explosion** — 100 skills cannot be covered by a handful of templates.
2. **No skill self-declaration** — skills don't declare pipeline metadata; the registry is a separate markdown table that drifts.
3. **Context cost** — loading all skill descriptions at once is expensive and grows linearly with skill count.
4. **No extensibility** — adding a new routable skill requires manually editing `pipeline-templates.md` and `SKILLS_REGISTRY.md`.

---

## Goals

- Every skill can be pipeline-routable by declaring metadata once.
- The orchestrator assembles pipelines dynamically from the goal, not from a hardcoded template list.
- Context cost stays flat regardless of skill count (hierarchical traversal).
- `skill-creator` enforces registration at creation time.
- Templates survive as named presets (fast path), not as the primary mechanism.

---

## Non-Goals

- Changing individual skill `SKILL.md` files (pipeline metadata lives in the registry, not the skills).
- LangGraph or runtime graph execution (that is v3).
- Auto-generating the registry from file system structure.

---

## Architecture

### 1. `SKILLS_REGISTRY.yaml` — Recursive Tree

Replaces `SKILLS_REGISTRY.md`. Complete inventory of all skills (pipeline-routable and non-routable alike). Single source of truth for skill metadata.

**Schema:**

Each node is either a **branch** (has `children`) or a **leaf** (has `skills`). Depth is unconstrained. Files without `version: 2` are rejected with a clear error message.

```yaml
version: 2

# Built-in stages: executed directly by the orchestrator, not dispatched as skills.
# Only stage_name and output_type are required — input_type is absent (no predecessor).
# Listed here so the dependency resolver can find them when walking `requires` chains.
built_ins:
  - stage_name: brainstorm
    output_type: design_sketch
    # context_types for brainstorm (approach_selection, design_approval) are defined
    # in brainstorm-phase.md, not here — built_ins entries are used only by the
    # dependency resolver, not for gate dispatch.

registry:
  - name: <domain>
    summary: "<one-line description used by the router>"
    children:
      - name: <group>
        summary: "<one-line description>"
        skills:
          - name: <skill-name>
            description: "<one-line description>"
            pipeline:                              # omit entirely if not pipeline-routable
              stage_name: <canonical-id>           # used in --stages, state.yaml, presets
              input_type: <type> [| <type>]        # consumed artifact; | = OR (any one satisfies)
              output_type: <type>                  # produced artifact (always a single type)
              context_type: <type>                 # must be one of the allowed types (see below)
              requires_all: [<stage_name>, ...]    # ALL must be completed before this stage
              requires_any: [<stage_name>, ...]    # AT LEAST ONE must be completed (OR-semantics)
              skippable: true | false
              # A stage may declare both requires_all and requires_any.
              # requires_all is resolved first. A stage_name already in requires_all
              # automatically satisfies a requires_any constraint that includes it.

presets:
  # Presets are trusted stage sequences. They are used as-is — dependency resolution
  # and type validation (Steps 5–6) are skipped when a preset is selected.
  # This allows presets to intentionally skip stages whose requires chain would otherwise
  # force their inclusion (e.g., bugfix skips spec despite design.requires_all=[spec]).
  full:     [brainstorm, spec, spec-summary, design, impl, code, eng-guide, test-docs, tests]
  feature:  [brainstorm, spec, design, impl, code, eng-guide, test-docs, tests]
  bugfix:   [brainstorm, design, code]
  # Note: v1 bugfix included `tests`; v2 drops it. Rationale: bugfixes are scoped enough
  # that inline tests produced by the code stage suffice. test-docs requires eng-guide
  # which is not in bugfix scope.
  docs-only:[brainstorm, spec, spec-summary, eng-guide]
  # Note: full and feature include test-docs (new in v2) before tests.
  # v1 full was: [brainstorm, spec, spec-summary, design, impl, code, eng-guide, tests]
  # docs-only intentionally excludes test-docs — docs-only produces no test artifacts.
```

**`context_type` allowlist** (must be one of; defined authoritatively in `stage-interface.md`):
`qa_answer`, `approach_selection`, `design_approval`, `spec_review`, `code_review`, `doc_review`

**`requires_all` vs `requires_any`:**
- `requires_all: [A, B]` — both A and B must be completed. Dependency resolver adds all missing entries.
- `requires_any: [A, B]` — at least one must be completed. Resolver adds the leftmost (highest-priority) missing dependency only if none of the listed stages are already selected.
- Both may be declared on the same stage. `requires_all` is satisfied first. If a stage appears in both, its presence in `requires_all` is sufficient to satisfy the `requires_any` constraint.
- **Presets bypass these rules** — presets are taken as-is without dependency resolution.

**`input_type` union:** `|` means OR — any predecessor whose `output_type` matches any listed type satisfies the constraint.

**Skill naming (v1 → v2 renames):**

| v1 name (SKILLS_REGISTRY.md) | v2 name (filesystem directory) |
|---|---|
| `write-design` | `write-design-docs` |
| `write-implementation` | `write-implementation-docs` |

`write-implementation` and `write-implementation-docs` are two distinct skills in the filesystem. `write-implementation-docs` supersedes `write-implementation` as the canonical `impl` stage. `write-implementation` is retained in the registry as a non-pipeline skill (no `pipeline:` block) for direct invocation only.

**Initial tree layout (all current skills):**

```yaml
version: 2

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
                # No pipeline: block — not router-selectable
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
  full:     [brainstorm, spec, spec-summary, design, impl, code, eng-guide, test-docs, tests]
  feature:  [brainstorm, spec, design, impl, code, eng-guide, test-docs, tests]
  bugfix:   [brainstorm, design, code]
  docs-only:[brainstorm, spec, spec-summary, eng-guide]
```

---

### 2. Router Algorithm (Phase 0 of autonomous-orchestrator)

Replaces hardcoded template lookup. Runs before any pipeline stage begins.

#### Step 0 — Load registry (in-memory merge)

At the very start of Phase 0:
1. Read `SKILLS_REGISTRY.yaml`. Reject if `version` is missing or not `2`.
2. Scan plugin directories for `REGISTRY_ENTRY.yaml` files. Validate each against the schema. Merge into the in-memory tree at the declared `domain`/`group`. **Plugin entries are never written back to `SKILLS_REGISTRY.yaml`** — merge is in-memory only.
3. **Collision rule:** If a plugin declares a `stage_name` that already exists in the core registry or was claimed by a previously merged plugin, reject the plugin entry with an error naming the conflict. First-registered wins; the user must resolve the collision manually.
4. Validate merged tree: verify all `context_type` values are in the allowlist; verify all `requires_all`/`requires_any` entries resolve to a known `stage_name` or `built_in`; detect cycles (see Step 5).

#### Step 1 — Preset check (fast path)

Before traversing, use LLM judgment to check whether the goal obviously maps to a preset:
- Strong fix/defect signal with no new-feature scope → `bugfix`
- Documentation intent with no implementation scope → `docs-only`

If matched, present to user: *"This looks like a `bugfix` pipeline: `brainstorm → design → code`. Proceed or customize?"*

**On preset confirmation: use the preset stage list as-is. Skip Steps 2–6 entirely (no traversal, no dependency resolution, no type validation).** Presets are trusted sequences. If the user customizes (drops or adds stages), exit the fast path and validate the custom list through Steps 5–6 only (no traversal needed since stages are explicit).

If goal is ambiguous, fall through to the slow path.

#### Step 2 — Domain traversal (slow path)

Load only top-level `name` + `summary` fields from `registry`. Reason over the goal: which domains are relevant? Output: list of domain names.

The `meta` domain is a **hard filter** — never selected by the router regardless of goal content. `meta` skills are internal infrastructure, not user pipeline stages. A goal like "build me a new skill" redirects to `skill-creator` directly, it does not run through the pipeline router.

#### Step 3 — Group drill-down

For each selected domain, load its children's `name` + `summary` fields. Select relevant groups.

#### Step 4 — Skill selection

For each selected group, load individual skill entries (`name` + `description` + `pipeline:` block only — not full SKILL.md). Select pipeline-routable skills (those with a `pipeline:` block) based on goal relevance.

#### Step 5 — Dependency resolution

**Cycle detection:** Before resolving, build the full dependency graph and check for cycles (A requires B, B requires A). If a cycle is detected, surface the cycle path and abort with an error.

Walk the dependency graph for all selected skills. Resolve:
- For `requires_all`: add all listed stages not yet selected.
- For `requires_any`: if none of the listed stages are selected, add the leftmost one.

Recurse until no new dependencies are added. Topological sort on the full set. **Tie-breaking:** when multiple stages have no unmet dependencies, sort by their declaration order in the YAML (top-to-bottom). This is deterministic and preserves the intended left-to-right flow within each group.

```
selected:  [design, code, eng-guide]

round 1:
  design.requires_all=[spec]              → add spec
  code.requires_any=[impl, design]        → design already selected, no-op
  eng-guide.requires_any=[code, spec-summary] → code already selected, no-op

round 2:
  spec.requires_all=[brainstorm]          → brainstorm is a built_in, add it

round 3: no new additions

topological sort (declaration order tie-break):
  brainstorm → spec → design → code → eng-guide
```

#### Step 6 — Type validation

For each stage in the sorted sequence, identify its **feeding stage**: the most recently completed stage in the sequence (per the requires graph, not necessarily the immediately preceding position) whose `output_type` matches any type in this stage's `input_type`. Verify the match.

Example (`docs-only`): `eng-guide` follows `spec-summary` (no `code` stage). Its feeding stage is `spec-summary` (output: `spec_digest`). `eng-guide.input_type = source_code | spec_digest` — `spec_digest` satisfies the union. Valid.

On mismatch where no predecessor in the sequence produces a matching type, surface a warning and ask for user confirmation before proceeding.

**Empty selection:** If Steps 2–4 produce zero pipeline-routable skills (no domain matched or no skills within matched groups), inform the user that no matching stages were found and offer to fall back to a preset or accept a custom `--stages` list.

#### Step 7 — Present and confirm

Show the assembled plan before running:

```
Assembled pipeline for "add Redis caching":
  brainstorm → spec → design → impl → code → eng-guide

Matches preset `feature`. Proceed, or adjust stages?
```

User can drop stages, add stages, or confirm. The `--stages` flag bypasses the router entirely (existing behavior preserved); custom `--stages` lists go through Steps 5–6 only.

---

### 3. Plugin Skill Registration

Skills from external plugins (e.g. `superpowers:*`, `ralph-loop:*`) live outside `.claude/skills/`. They may declare a `REGISTRY_ENTRY.yaml` in their skill directory:

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

Merged in-memory during Phase 0 Step 0. Plugin skills without a `REGISTRY_ENTRY.yaml` are not routable — no error, they simply won't appear in assembled pipelines.

---

### 4. `skill-creator` Integration

`skill-creator` gains one new step after generating `SKILL.md`:

> "Is this skill pipeline-routable? (yes/no)"

If yes, prompt for: `stage_name`, `input_type`, `output_type`, `requires_all`/`requires_any`, `skippable`, `context_type`. Then:
1. Determine which domain + group in `SKILLS_REGISTRY.yaml` this skill belongs to (create a new group if needed).
2. Append the entry under the correct node.
3. Confirm the addition with the user.

This ensures the registry never drifts from the installed skill set.

---

## Files Changed

| File | Change |
|---|---|
| `.claude/skills/SKILLS_REGISTRY.yaml` | **New** — complete skill inventory; replaces `SKILLS_REGISTRY.md` |
| `.claude/skills/SKILLS_REGISTRY.md` | **Deleted** (only after orchestrator update is verified in rollout Step 5) |
| `.claude/skills/autonomous-orchestrator/pipeline-templates.md` | **Slimmed** — remove stage registry rows (now in YAML) and preset definitions (now in YAML); keep fallback rules and inter-stage contracts only |
| `.claude/skills/autonomous-orchestrator/stage-interface.md` | **Updated** — rewrite "How to Add a New Stage" section to point to `SKILLS_REGISTRY.yaml`; retain field semantic definitions (`input_from`, `output_path`, `context_type` allowlist) as authoritative runtime contract |
| `.claude/skills/autonomous-orchestrator/SKILL.md` | **Updated** — Phase 0 reads `SKILLS_REGISTRY.yaml`; add router algorithm (Steps 0–7) |
| `.claude/skills/skill-creator/SKILL.md` | **Updated** — add pipeline registration step |

No changes to individual pipeline skill `SKILL.md` files.

---

## Dependency Graph

```
SKILLS_REGISTRY.yaml
        │
        ├── read by → autonomous-orchestrator (Phase 0 router, Step 0)
        ├── written by → skill-creator (registration step)
        └── merged with (in-memory only) → plugin REGISTRY_ENTRY.yaml files

pipeline-templates.md (slimmed)
        │
        └── fallback rules + inter-stage contracts only

stage-interface.md
        │
        └── runtime field semantics (input_from, output_path, context_type allowlist)
            "How to Add a New Stage" section rewritten to reference SKILLS_REGISTRY.yaml
```

---

## Rollout Sequence

1. **Create `SKILLS_REGISTRY.yaml`** — migrate all skills from `SKILLS_REGISTRY.md` + stage registry from `pipeline-templates.md`. *Verify: parse the YAML and confirm all 4 presets list valid stage names; confirm cycle detection finds no cycles in the dependency graph.*
2. **Update `autonomous-orchestrator/SKILL.md`** — Phase 0 router (Steps 0–7). *Verify: dry-run with sample goal "add Redis caching" and confirm assembled stages match `feature` preset.*
3. **Update `pipeline-templates.md`** — remove stage registry rows and preset definitions; keep fallback rules and inter-stage contracts.
4. **Update `stage-interface.md`** — rewrite "How to Add a New Stage" to reference `SKILLS_REGISTRY.yaml`; retain field semantic definitions.
5. **Update `skill-creator/SKILL.md`** — add pipeline registration step. *Verify: create a test skill and confirm the entry appears correctly in `SKILLS_REGISTRY.yaml`.*
6. **Delete `SKILLS_REGISTRY.md`** — only after all above steps verified.
