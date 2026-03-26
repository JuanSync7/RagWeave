# Skill Design Principles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Codify 10 skill design principles into skill-creator (authoring) and improve-skill (evaluation) so new skills are written with principled guidance and existing skills can be evaluated against those principles.

**Architecture:** A single reference file (`skill-design-principles.md`) in skill-creator's `references/` folder is the source of truth. skill-creator's SKILL.md gets a summary section pointing to it. improve-skill gets derived checklist items with a cross-reference comment.

**Tech Stack:** Markdown only. No code, no configs, no YAML changes.

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `~/.claude/skills/skill-creator/references/skill-design-principles.md` | Full principles reference — 10 principles with reasoning + good/bad examples |
| Modify | `~/.claude/skills/skill-creator/SKILL.md` | Insert Core Principles summary (before Workflow) + read-trigger (in Phase 2) |
| Modify | `~/.claude/skills/improve-skill/SKILL.md` | Insert Principles Alignment checklist (after Extended Criteria) |

---

### Task 1: Create the skill design principles reference file

**Files:**
- Create: `~/.claude/skills/skill-creator/references/skill-design-principles.md`

This is the largest task — the full reference file with all 10 principles. Each principle gets: statement, consequence, good example, bad example.

- [ ] **Step 1: Create the references/ directory**

```bash
mkdir -p ~/.claude/skills/skill-creator/references
```

- [ ] **Step 2: Write the reference file**

Create `~/.claude/skills/skill-creator/references/skill-design-principles.md` with this content:

````markdown
# Skill Design Principles

These principles determine whether a skill changes agent behavior or just adds token noise. Each one traces to a specific failure mode — if you're tempted to skip one, read the consequence first.

---

## 1. A skill is a context injection, not a program

**Every token in a skill competes with tokens the agent needs to reason about the user's actual task.** Only include what the agent can't derive from general training. You don't teach Claude to write Python — you teach it where to apply judgment in this specific domain.

**Consequence:** Token bloat degrades output quality on complex problems. The agent spends context budget on instructions it would have followed anyway.

**Good:**
```markdown
When the user's goal maps to a named preset (bugfix, docs-only), use the preset
directly — skip traversal. Presets are trusted sequences that bypass dependency
resolution.
```
*Teaches a non-obvious judgment call the agent wouldn't know from training.*

**Bad:**
```markdown
Read the YAML file using PyYAML. Parse each entry. Check that fields are present.
Iterate over the children array. For each child, check if it has a pipeline block.
```
*Teaches mechanical Python/YAML operations the agent already knows.*

---

## 2. Mental model before mechanics

**Start with a conceptual framing paragraph before any rules or workflow steps.** The agent that understands the spirit handles edge cases the rules don't cover. The agent that only has rules breaks on the first situation you didn't anticipate.

**Consequence:** Brittle compliance. The agent follows rules literally but fails on edge cases because it doesn't understand the intent.

**Good:**
```markdown
# Stakeholder Reviewer

Evaluates decisions against a stakeholder persona. The reviewer acts as a
domain-expert proxy — catching misalignment early rather than after
implementation, when changes are expensive.
```
*The agent understands WHY this skill exists and can reason about novel situations.*

**Bad:**
```markdown
# Stakeholder Reviewer

## Steps
1. Read the persona file
2. Read the artifact
3. Evaluate against criteria
4. Return APPROVE, REVISE, or ESCALATE
```
*The agent knows the mechanics but not the purpose. It can't judge ambiguous cases.*

---

## 3. The description is a routing contract

**The frontmatter `description:` determines when the skill fires — it specifies trigger conditions, not a workflow summary.** Test: if the description could replace reading the SKILL.md body, it's too broad. The agent will follow the description as a shortcut and skip the body.

**Consequence:** The agent either never invokes the skill (too narrow) or follows the description instead of the body (too broad), bypassing actual instructions.

**Good:**
```yaml
description: "Use when asked to create a new skill, build a skill for X, or write a skill."
```
*Trigger conditions only. You must read the body to know HOW.*

**Bad:**
```yaml
description: "Creates skills by understanding intent, building SKILL.md with
companion files, generating EVAL.md, and running improve-skill validation loops."
```
*This IS the workflow. The agent can follow this without reading the body.*

---

## 4. Scope boundaries are explicit

**A skill answers: What triggers this? What does this NOT do? What sibling handles the adjacent case?** Without crisp scope, skills under-fire (never invoked) or over-fire (polluting unrelated tasks).

**Consequence:** Ambiguous routing. The orchestrator loads a skill for a task it wasn't designed for, wasting context and producing wrong-shaped output.

**Good:**
```markdown
## Wrong-Tool Detection

**Redirect to `superpowers:brainstorming`** when the user explicitly asks for
interactive brainstorming. Tell the user: "This sounds like an interactive
session rather than an autonomous pipeline."
```
*Names the sibling and the trigger boundary between them.*

**Bad:**
```markdown
This skill helps with development tasks and planning.
```
*No boundary. Overlaps with half the skill ecosystem.*

---

## 5. Policy over procedure

**"When you encounter X, prioritize Y over Z because..." teaches judgment. "Step 1: do X. Step 2: do Y" teaches mechanics.** Judgment composes across contexts. Procedures break when context varies. Use procedures only for truly mechanical sequences.

**Consequence:** The skill works on the author's imagined scenario but breaks on variations. The agent can't adapt.

**Good:**
```markdown
When a stage is skipped, the next stage receives the most recent available
artifact. If the predecessor was skipped, walk backward through the pipeline
to find the most recent completed stage's output.
```
*Policy: handles any skip pattern without enumerating every combination.*

**Bad:**
```markdown
If spec is skipped, pass brainstorm output to design.
If design is skipped, pass spec output to impl.
If impl is skipped, pass design output to code.
```
*Procedure: covers 3 cases but breaks on the 4th. Doesn't scale.*

---

## 6. Every instruction traces to a failure mode

**"Why is this instruction here?" must have an answer: "Without it, the agent does X which causes Y."** Instructions without a traceable failure mode are noise. This is the per-instruction version of the baseline test.

**Consequence:** Instruction bloat. The skill accumulates "good advice" that doesn't change behavior, pushing signal below the noise floor.

**Good:**
```markdown
Presets bypass dependency resolution entirely. This allows `bugfix` to
intentionally skip `spec` despite `design.requires_all: [spec]`.
```
*Without this instruction, the resolver would force `spec` into every bugfix pipeline.*

**Bad:**
```markdown
Always write clean, well-organized YAML files with proper indentation.
```
*Claude already writes clean YAML. This instruction changes nothing.*

---

## 7. Progressive disclosure

**SKILL.md carries always-on information. Companion files carry on-demand information loaded at specific decision points.** The token budget determines the boundary. If you only need it during one phase, it's a companion file.

**Consequence:** Either the skill is too long (everything inline, token waste) or too sparse (agent lacks the mental model to know when to load companion files).

**Good:**
```markdown
> **Read [`brainstorm-phase.md`](brainstorm-phase.md)** when entering the
brainstorming stage.
```
*Brainstorm details loaded only when needed. SKILL.md stays focused on orchestration.*

**Bad:**
A 400-line SKILL.md that inlines the full brainstorm protocol, stakeholder review
protocol, and escalation handler — all always loaded even when the agent is in
Phase 0 initialization.

---

## 8. Restriction when discipline demands it

**Most skills guide judgment. Discipline-enforcement skills override the agent's default behavior.** For these, use explicit gates and hard constraints. Soft guidance gets rationalized away.

**Consequence:** The agent rationalizes around soft guidance and reverts to default behavior — skipping design, jumping to code — which is exactly what the skill was supposed to prevent.

**Good:**
```markdown
<HARD-GATE>
Do NOT invoke any implementation skill or write any code until you have
presented a design and the user has approved it.
</HARD-GATE>
```
*Explicit, unambiguous restriction. The agent can't rationalize past it.*

**Bad:**
```markdown
It's generally a good idea to present the design before starting implementation.
Consider discussing the approach with the user first.
```
*"Generally" and "consider" are escape hatches. The agent will skip this under pressure.*

---

## 9. Loud failure on preconditions

**If a skill requires input, check the precondition and surface a clear failure.** Never proceed silently with bad or missing input.

**Consequence:** Plausible-looking output from bad input. The error surfaces during review or production, when it's expensive to fix.

**Good:**
```markdown
Load registry. Reject if `version` is missing or not `2`.
```
*Fails fast with a clear signal. No ambiguity about what went wrong.*

**Bad:**
```markdown
Load the registry file and use its contents to assemble the pipeline.
```
*If the file is malformed or missing, the skill proceeds with garbage data and produces confident-looking but wrong output.*

---

## 10. Concrete over abstract

**Show filled-in examples, not empty templates. Show good/bad contrasts for non-obvious patterns.** The agent needs to see what "right" looks like to calibrate its output.

**Consequence:** Abstract guidance gets interpreted differently across invocations. A concrete good/bad pair anchors the interpretation.

**Good:**
```markdown
**Good:** "Recommendation: per-user cache isolation. Counter: global cache is
simpler. Defense: multi-tenant auth already scopes per-user, so isolation is
consistent."

**Bad:** "Recommendation: per-user cache isolation. Counter: we could not cache
at all. Defense: caching is obviously better." *(straw-man counter-argument)*
```
*Shows exactly what a strong vs weak self-critique looks like.*

**Bad:**
```markdown
Write a self-critique that considers alternatives and defends the recommendation.
```
*The agent's idea of "considers alternatives" may be very different from yours.*
````

- [ ] **Step 3: Verify line count and structure**

Run: `wc -l ~/.claude/skills/skill-creator/references/skill-design-principles.md`
Expected: 150-210 lines (budget is ~150-200, slight variance is OK)

Verify the file has exactly 10 `## N.` headings:
Run: `grep -c '^## [0-9]' ~/.claude/skills/skill-creator/references/skill-design-principles.md`
Expected: `10`

- [ ] **Step 4: Commit**

```bash
git add ~/.claude/skills/skill-creator/references/skill-design-principles.md
git commit -m "feat(skill-creator): add skill design principles reference file

10 principles with reasoning and good/bad examples for each.
Source of truth for skill authoring guidance."
```

---

### Task 2: Add Core Principles section and read-trigger to skill-creator

**Files:**
- Modify: `~/.claude/skills/skill-creator/SKILL.md:45-62`

Two insertions in the same file.

- [ ] **Step 1: Insert Core Principles section**

Insert the following **after line 45** (the closing of the Progress Tracking agent-dispatch paragraph) and **before line 47** (`## Workflow`):

```markdown
## Core Principles

Before building a skill, internalize these — they determine whether the skill actually changes agent behavior or just adds noise.

1. **Context injection, not a program** — only include what the agent can't derive from training
2. **Mental model before mechanics** — conceptual framing before rules
3. **Description is a routing contract** — trigger conditions, not workflow summary
4. **Explicit scope boundaries** — what this does, doesn't do, and what sibling handles instead
5. **Policy over procedure** — teach judgment, not mechanical steps
6. **Every instruction traces to a failure mode** — if removing it wouldn't change output, remove it
7. **Progressive disclosure** — always-on in SKILL.md, on-demand in companion files
8. **Restriction when discipline demands it** — some skills must override defaults
9. **Loud failure on preconditions** — check inputs, surface failures, never proceed silently
10. **Concrete over abstract** — filled-in examples, good/bad contrasts
```

This adds ~14 lines. The `## Core Principles` heading is at the same level as `## Progress Tracking` and `## Workflow`.

- [ ] **Step 2: Insert read-trigger in Phase 2**

Inside `### Phase 2: Write the Skill` (currently line 62), insert the following **after the opening line** (`### Phase 2: Write the Skill`) and **before** the "Build the skill directory:" paragraph:

```markdown
> **Read [`references/skill-design-principles.md`](references/skill-design-principles.md)** before writing the SKILL.md body — full reasoning and examples for each principle.
```

This adds 2 lines (the pointer + a blank line). It loads the full reference on-demand when the agent enters Phase 2.

- [ ] **Step 3: Verify line count**

Run: `wc -l ~/.claude/skills/skill-creator/SKILL.md`
Expected: ~262 lines (was 246, added ~16)

Verify the Core Principles section is between Progress Tracking and Workflow:
Run: `grep -n '## ' ~/.claude/skills/skill-creator/SKILL.md | head -5`
Expected output shows `## Progress Tracking`, `## Core Principles`, `## Workflow` in order.

- [ ] **Step 4: Verify read-trigger is inside Phase 2**

Run: `grep -n 'skill-design-principles' ~/.claude/skills/skill-creator/SKILL.md`
Expected: one match, with a line number between Phase 2 heading and the directory tree.

- [ ] **Step 5: Commit**

```bash
git add ~/.claude/skills/skill-creator/SKILL.md
git commit -m "feat(skill-creator): add Core Principles section and Phase 2 read-trigger

Summary of 10 design principles always loaded before workflow.
Full reference file loaded on-demand during Phase 2 writing."
```

---

### Task 3: Add Principles Alignment checklist to improve-skill

**Files:**
- Modify: `~/.claude/skills/improve-skill/SKILL.md:100-102`

Single insertion between the Extended Criteria section and the `---` separator.

- [ ] **Step 1: Insert Principles Alignment block**

Insert the following **after line 100** (the last Extended Criteria item: `All format examples have concrete filled-in content...`) and **before line 102** (the `---` separator):

```markdown

#### Principles Alignment
<!-- Source of truth: skill-creator/references/skill-design-principles.md
     Update these criteria when the source principles change. -->

When doing a deep improvement pass, also evaluate against skill design principles:

- [ ] Mental model present — skill opens with a conceptual framing paragraph before any rules or workflow steps
- [ ] Description is trigger-only — frontmatter description contains trigger conditions/keywords, not a workflow summary or capability list
- [ ] Scope boundary stated — skill explicitly says what it does NOT do, or names the sibling skill that handles the adjacent case
- [ ] Instructions are traceable — each major instruction can be linked to a failure mode (what goes wrong without it); flag instructions with no apparent failure consequence
- [ ] Policy/procedure balance — workflow steps that involve judgment use policy framing ("when X, prioritize Y because...") rather than rigid mechanical sequences
- [ ] Preconditions checked — if the skill requires input artifacts, there is an explicit check-and-fail instruction, not silent assumption
- [ ] Token-budget boundary correct — detail needed only at one decision point lives in a companion file, not inline in SKILL.md body (distinct from the baseline "progressive disclosure" check which verifies companion files exist; this checks the always-on vs on-demand split is right)
```

Note: The last item (principle 7) is intentionally worded to differentiate from the existing baseline checklist item "Progressive disclosure: essential content in SKILL.md, detail in companion files" on line 84. The baseline checks that companion files are used; this checks that the boundary between always-on and on-demand content is correctly placed.

- [ ] **Step 2: Verify structural placement**

Run: `grep -n '####' ~/.claude/skills/improve-skill/SKILL.md`
Expected: Shows `#### Description`, `#### Body`, `#### Structure`, `#### Progress & Visibility`, `#### Principles Alignment` — the new block is the last `####` heading in Pass 1.

- [ ] **Step 3: Verify checklist count**

Run: `grep -c '^\- \[ \]' ~/.claude/skills/improve-skill/SKILL.md`
Expected: 25 total (was 18 baseline + extended, now 18 + 7 = 25)

- [ ] **Step 4: Verify source-of-truth comment is present**

Run: `grep 'Source of truth' ~/.claude/skills/improve-skill/SKILL.md`
Expected: One match showing `skill-creator/references/skill-design-principles.md`

- [ ] **Step 5: Commit**

```bash
git add ~/.claude/skills/improve-skill/SKILL.md
git commit -m "feat(improve-skill): add Principles Alignment checklist block

7 structural criteria derived from skill-creator's design principles.
Cross-references source of truth for maintenance sync."
```
