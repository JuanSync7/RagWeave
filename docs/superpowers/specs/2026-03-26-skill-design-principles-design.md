# Skill Design Principles — Design Specification

## Problem Statement

Skills are the primary mechanism for extending Claude Code agent behavior. As the skill ecosystem grows (18+ skills currently, with the v2 registry enabling dynamic routing), there is no codified theory of what makes a skill effective. skill-creator teaches the workflow (phases 1-7) and file structure (SKILL.md, companion folders) but doesn't teach the underlying design principles that determine whether a skill actually changes agent behavior or just adds token noise.

improve-skill evaluates skills against a structural checklist (description format, body limits, progressive disclosure) but lacks criteria for the deeper quality signals: Is there a mental model? Does the description route correctly? Does every instruction trace to a failure mode?

## Goals

1. Codify 10 skill design principles as a companion reference file in skill-creator
2. Surface those principles during authoring via a summary section in skill-creator's SKILL.md
3. Derive measurable evaluation criteria in improve-skill's structural pass from the same principles
4. Establish a single source of truth (skill-creator's reference file) with improve-skill as a downstream consumer

## Non-Goals

- Rewriting existing skills to conform to the new principles (they get evaluated, not bulk-rewritten)
- Changing skill-creator's workflow phases (1 through 7 stay as-is)
- Changing improve-skill's behavioral pass (Pass 2) — only Pass 1 structural gets new criteria
- Updating SKILLS_REGISTRY.yaml (neither skill is pipeline-routable)
- Regenerating EVAL.md files for skill-creator or improve-skill

## The 10 Principles

### 1. A skill is a context injection, not a program

It runs in the agent's mind, competing for the same context window the agent needs to reason about the actual task. Only include what the agent can't derive from general training. You don't teach Claude to write Python — you teach it where to apply judgment in this specific domain.

**Consequence of ignoring:** Token bloat. The skill consumes context that the agent needs for reasoning about the user's actual task, degrading output quality on complex problems.

### 2. Mental model before mechanics

Start with a one-paragraph conceptual framing: what this skill accomplishes and why it matters. The agent that understands the spirit handles edge cases the rules don't cover. The agent that only has rules breaks on the first situation you didn't anticipate.

**Consequence of ignoring:** Brittle compliance. The agent follows rules literally but fails on edge cases because it doesn't understand the intent behind the rules.

### 3. The description is a routing contract

The frontmatter `description:` determines when the skill fires. It specifies trigger conditions, not a workflow summary. Test: if the description could replace reading the SKILL.md body, it's too broad — the agent will follow the description as a shortcut and skip the body entirely.

**Consequence of ignoring:** The agent either never invokes the skill (description too narrow/vague) or follows the description instead of the body (description summarizes workflow), bypassing the actual instructions.

### 4. Scope boundaries are explicit

A skill answers three questions: What triggers this? What does this NOT do? What sibling handles the adjacent case? Without crisp scope, skills under-fire (never invoked) or over-fire (polluting unrelated tasks).

**Consequence of ignoring:** Ambiguous routing. The orchestrator or agent loads a skill for a task it wasn't designed for, wasting context and producing wrong-shaped output.

### 5. Policy over procedure

"When you encounter X, prioritize Y over Z because..." teaches judgment. "Step 1: do X. Step 2: do Y" teaches mechanics. Judgment composes across varied contexts. Procedures only work when context exactly matches the template. Use procedures for truly mechanical sequences; use policy for everything else.

**Consequence of ignoring:** The skill works on the exact scenario the author imagined but breaks on variations. The agent can't adapt because it was taught steps, not reasoning.

### 6. Every instruction traces to a failure mode

"Why is this instruction here?" must have an answer: "Without it, the agent does X which causes Y." Instructions without a traceable failure mode are noise — they consume tokens and dilute signal. This is the per-instruction version of the baseline test.

**Consequence of ignoring:** Instruction bloat. The skill accumulates "good advice" that doesn't change behavior, pushing real signal below the noise floor.

### 7. Progressive disclosure

SKILL.md carries always-on information needed throughout execution. Companion files carry on-demand information loaded at specific decision points. The token budget determines the boundary. If you only need it during one phase, it belongs in a companion file.

**Consequence of ignoring:** Either the skill is too long (everything inline, token waste) or too sparse (everything in companion files, agent lacks the mental model to know when to load them).

### 8. Restriction when discipline demands it

Most skills guide judgment without restricting it. But discipline-enforcement skills (TDD, design-before-code) exist to override the agent's default behavior. For these, use explicit gates and hard constraints. The restriction IS the value.

**Consequence of ignoring:** The agent rationalizes its way around soft guidance and reverts to default behavior (e.g., skipping design and jumping straight to code), which is exactly what the skill was supposed to prevent.

### 9. Loud failure on preconditions

If a skill requires input (a spec, a design doc, a codebase), check the precondition and surface a clear failure. Never proceed silently with bad or missing input — the output will look plausible but be wrong.

**Consequence of ignoring:** The skill produces confident-looking output from bad input. The error surfaces much later (during review or production), when it's expensive to fix.

### 10. Concrete over abstract

Show filled-in examples, not empty templates. Show good/bad contrasts for non-obvious patterns. The agent needs to see what "right" looks like to calibrate its output.

**Consequence of ignoring:** The agent interprets abstract guidance in unexpected ways. "Write clear descriptions" means different things to different invocations; a concrete good/bad pair anchors the interpretation.

## File Changes

### 1. Create: `skill-creator/references/skill-design-principles.md`

New companion reference file. Contains all 10 principles, each with:
- Principle statement (one sentence, bold)
- Why it matters (2-3 sentences, the consequence of ignoring it)
- Good example (concrete, from real skill patterns)
- Bad example (concrete, showing the failure mode)

Estimated ~150-200 lines. Each principle gets ~15-20 lines; good/bad examples should be concise (2-4 lines each). If the line budget and example quality conflict, prioritize example quality — a clear example is worth more than staying under 200 lines.

### 2. Modify: `skill-creator/SKILL.md`

Two insertions:

**A. New `## Core Principles` section** — inserted after `## Progress Tracking` and before `## Workflow` (same `##` heading level as its siblings). Contains:
- A one-line framing sentence
- A numbered list of all 10 principles as bold title + one-line description

Estimated ~15 lines added. This is always-on — it gives the agent the conceptual framework before entering the workflow.

**B. Read-trigger in Phase 2 body** — inside the existing `### Phase 2: Write the Skill` section, add a pointer:
```markdown
> **Read [`references/skill-design-principles.md`](references/skill-design-principles.md)** before writing the SKILL.md body — full reasoning and examples for each principle.
```

This loads the full reference on-demand when the agent is actively writing, not at skill-load time. The summary in Core Principles gives the mental model early; the reference file loads the examples and reasoning when they're needed during Phase 2. This is progressive disclosure applied to skill-creator itself.

### 3. Modify: `improve-skill/SKILL.md`

Add a "Principles Alignment" checklist block after the existing "Extended Criteria" section. Contains 7 structural checklist items derived from the 10 principles:

- Mental model present (from principle 2)
- Description is trigger-only (from principle 3)
- Scope boundary stated (from principle 4)
- Instructions are traceable (from principle 6)
- Policy/procedure balance (from principle 5)
- Preconditions checked (from principle 9)
- Progressive disclosure practiced (from principle 7)

Three principles are not separate checklist items:
- **Principle 1** (context injection) — covered by existing baseline criterion "SKILL.md body is under 500 lines" and extended criterion "no internal redundancy." The token economy concern is enforced through these proxies.
- **Principle 8** (restriction for discipline) — this is a design-time authoring decision, not a structural property. Whether a skill is discipline-enforcing or guidance-giving depends on its purpose (semantic judgment), not its structure. skill-creator teaches the author when to use restriction; improve-skill cannot determine this from structure alone.
- **Principle 10** (concrete over abstract) — covered by existing baseline criterion "concrete examples present" and extended criterion "good/bad contrast examples."

Relationship to source of truth: improve-skill's criteria are derived from skill-creator's principles but self-contained — the evaluator doesn't read skill-design-principles.md at evaluation time. The Principles Alignment section includes a source-of-truth comment:

```markdown
#### Principles Alignment
<!-- Source of truth: skill-creator/references/skill-design-principles.md
     Update these criteria when the source principles change. -->
```

This cross-reference ensures the maintenance obligation is visible at the point of use, not buried in a separate design doc.

## What This Does NOT Change

- skill-creator workflow phases (1 through 7) — unchanged
- skill-creator companion folder conventions — unchanged
- skill-creator Phase 2.5 pipeline registration — unchanged
- improve-skill behavioral pass (Pass 2) — unchanged
- improve-skill baseline checklist — unchanged (new block is additive)
- SKILLS_REGISTRY.yaml — unchanged (neither skill is pipeline-routable)
- Other skills — not modified (they get evaluated against new criteria, not rewritten)
- EVAL.md files — not regenerated
