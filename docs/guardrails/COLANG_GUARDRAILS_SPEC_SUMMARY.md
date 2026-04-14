## 1) Generic System Overview

### Purpose

The declarative policy layer provides structured decision-making for a retrieval-augmented generation pipeline's safety and quality subsystem. Without it, policy decisions -- what to block, when to hedge, how to escalate -- would be scattered across ad-hoc conditionals in computational code, making policies hard to audit, modify, or extend. The layer separates *what to decide* from *how to compute*, giving operators a single surface where all guardrail policies are expressed as composable, ordered flows.

### How It Works

A user message enters a single-pass pipeline that executes three phases sequentially: input validation, generation, and output governance.

During input validation, the message passes through an ordered sequence of eleven checks. Fast deterministic checks run first: length bounds, language detection, clarity heuristics, and abuse-rate tracking. Next come safety policy checks: bulk-extraction pattern matching, role-boundary enforcement, jailbreak-escalation tracking (with per-session state that escalates from warning to blocking after repeated violations), and sensitive-topic flagging. Content-relevance checks follow: off-topic detection and ambiguity detection, the latter prompting the user to disambiguate before retrieval. Finally, a bridge action delegates to a separate computational executor that runs machine-learning-based checks (injection detection, personally identifiable information redaction, toxicity filtering, topic safety). Any check can halt the pipeline and return a policy response directly.

If input validation passes, standalone dialog flows intercept non-search intents -- greetings, farewells, help requests, follow-up continuations, feedback, scope questions -- and respond with canned messages without entering retrieval. Unmatched queries proceed to retrieval-augmented generation.

During output governance, seven checks run in fixed order. The computational executor runs first (faithfulness verification, output-side redaction and toxicity filtering). Then lighter policy checks apply: disclaimer prepending for sensitive topics flagged at input time, no-results and low-confidence handling with hedging language, citation presence verification, length governance, and scope enforcement.

### Tunable Knobs

Operators can control query acceptance bounds (minimum and maximum lengths), the rate-limiting window and threshold for abuse detection, and the escalation thresholds that determine when repeated policy violations shift from warnings to session blocks. On the output side, answer length bounds, the confidence threshold below which hedging language is applied, and per-category toggles for individual computational checks (injection, redaction, toxicity, faithfulness) are all configurable. A master toggle can deactivate the entire subsystem, making it inert. Each of these dimensions defaults to a conservative value documented in the design guide.

### Design Rationale

The architecture enforces a strict separation: declarative flows express policy decisions while computational actions perform detection and scoring. This prevents policy logic from being buried in detection code and makes policies auditable by non-ML engineers. The ordered pipeline places cheap deterministic checks before expensive model-based checks, so most illegitimate queries are rejected without invoking heavyweight computation. Every computational action is wrapped in a fail-open decorator so that a failing dependency never blocks the pipeline -- the system degrades to reduced protection rather than total failure. Session state is kept in-memory rather than externalized, accepting the trade-off that escalation counters reset on worker restarts in exchange for zero external state dependencies.

### Boundary Semantics

The system is triggered when a user message enters the pipeline's single asynchronous entry point. It receives the raw user query as input. It produces a final response message after all output governance checks complete -- either the generation result (potentially modified with hedges, disclaimers, or redactions) or a policy-generated rejection message. Context variables bridge input and output phases (e.g., a sensitive-topic flag set during input is consumed during output to prepend a disclaimer). The system hands off the final response to the calling retrieval chain. No state is persisted beyond the worker process lifetime; session-scoped counters exist only in memory.

---

# Colang 2.0 Guardrails Subsystem -- Specification Summary

**Companion document to:** `COLANG_GUARDRAILS_SPEC.md` (v1.0.0)
**Purpose:** Requirements-level digest for stakeholders, reviewers, and implementers.
**See also:** COLANG_DESIGN_GUIDE.md (design reference), COLANG_GUARDRAILS_IMPLEMENTATION.md (implementation guide), NEMO_GUARDRAILS_SPEC.md (parent NeMo integration spec)

---

## 2) Scope and Boundaries

**Entry point:** A user message enters the pipeline's single asynchronous call, triggering input rail flows in registered order.
**Exit points:**

- Final response message after all output rail flows complete
- Early rejection message when any rail halts the pipeline

### In scope

- Input rail flows (query validation, safety policy, content-relevance checks, computational executor bridge)
- Standalone dialog flows (greetings, farewells, administrative help, follow-ups, feedback, scope questions, topic drift)
- Generation action bridging the pipeline to retrieval-augmented generation
- Output rail flows (response quality, citation enforcement, confidence hedging, length governance, scope enforcement, computational executor bridge)
- Python action wrappers bridging declarative flows to computational executors
- Runtime integration (singleton lifecycle, configuration loading, master toggle, graceful degradation)

### Out of scope

**Out of scope -- this spec:**

- Python rail class internals (injection detection layers, PII entity recognition, toxicity scoring, faithfulness checking) -- covered by the parent NeMo spec
- Rail orchestration scheduling (parallel input rails, sequential output rails, merge gate priority) -- covered by the parent NeMo spec
- Metrics and tracing instrumentation -- covered by the parent NeMo spec

**Out of scope -- this project:**

- Training custom intent models
- Multi-language flow definitions (English-only)
- Persistent session state across worker restarts
- User-configurable flows at runtime (flows are deployment-time configuration)

---

## 3) Architecture / Pipeline Overview

```
    User Message
         |
         v
    INPUT RAILS (11 flows, registered order):
    +------------------------------------------+
    |  [1]  Query length check                 |
    |  [2]  Language detection                 |
    |  [3]  Query clarity check                |
    |  [4]  Abuse rate limiting                |
    |  [5]  Exfiltration detection             |
    |  [6]  Role boundary enforcement          |
    |  [7]  Jailbreak escalation               |
    |  [8]  Sensitive topic flagging        *  |
    |  [9]  Off-topic detection                |
    |  [10] Ambiguity detection                |
    |  [11] Computational executor bridge      |
    +------------------------------------------+
         |  (if not halted)
         v
    STANDALONE DIALOG FLOWS (auto-discovered):
    +------------------------------------------+
    |  greeting / farewell / admin / follow-up |
    |  feedback / scope / topic drift          |
    +------------------------------------------+
         |
         v
    GENERATION:
    +------------------------------------------+
    |  Retrieval + generation action           |
    +------------------------------------------+
         |
         v
    OUTPUT RAILS (7 flows, registered order):
    +------------------------------------------+
    |  [1]  Computational executor bridge      |
    |  [2]  Disclaimer prepend             *   |
    |  [3]  No-results handling                |
    |  [4]  Confidence hedging                 |
    |  [5]  Citation verification              |
    |  [6]  Length governance                  |
    |  [7]  Scope enforcement                  |
    +------------------------------------------+
         |
         v
    Final Response

    * = conditional / context-dependent
```

All flows share context variables for cross-phase communication (e.g., sensitive-topic flags bridge input to output). Any rail can halt the pipeline via an abort mechanism, returning a policy response directly. Deterministic checks are ordered before expensive computational checks.

---

## 4) Requirement Framework

- **ID convention:** `COLANG-xxx` prefix, distinguishing from the parent NeMo spec's `REQ-xxx`. Nine requirement sections with ID ranges from COLANG-1xx to COLANG-9xx.
- **Priority scheme:** RFC 2119 keywords (MUST, SHOULD, MAY). 54 MUST, 6 SHOULD, 0 MAY out of 60 total requirements.
- **Requirement structure:** Each requirement includes description, rationale, and acceptance criteria.
- **Traceability:** A full traceability matrix maps each COLANG requirement to its parent REQ requirement where applicable.

---

## 5) Functional Requirement Domains

The spec defines 60 functional and non-functional requirements across nine domains:

- **File Structure & Syntax** (`COLANG-1xx`) -- Flow file layout, naming conventions, syntax version, action-result invocation pattern
- **Python Actions** (`COLANG-2xx`) -- 26 action wrappers, fail-open decorator, lazy initialization, session state, executor bridges, environment toggles
- **Input Rails** (`COLANG-3xx`) -- Query length, language, clarity, abuse rate, computational executor bridge, execution ordering
- **Conversation Management** (`COLANG-4xx`) -- Greetings, farewells, administrative help, follow-up detection, off-topic blocking, topic drift
- **Output Rails** (`COLANG-5xx`) -- Computational executor bridge, disclaimers, no-results, confidence hedging, citations, length, scope, execution ordering
- **Safety & Compliance** (`COLANG-6xx`) -- Sensitive topic flagging, exfiltration prevention, role boundary enforcement, jailbreak escalation
- **RAG Dialog Patterns** (`COLANG-7xx`) -- Ambiguity disambiguation, scope explanation, feedback collection
- **Runtime Integration** (`COLANG-8xx`) -- Singleton lifecycle, idempotent initialization, fail-fast on syntax errors, auto-disable on runtime failures, master toggle, action registration, LLM provider configuration
- **Non-Functional** (`COLANG-9xx`) -- Configuration externalization, inert-when-disabled, test coverage, graceful degradation, latency budgets, logging constraints

---

## 6) Non-Functional and Security Themes

### Non-functional areas (`COLANG-9xx`)

- **Configuration externalization** -- all thresholds and toggles configurable at deployment time
- **Inert-when-disabled** -- zero imports or side effects when the master toggle is off
- **Graceful degradation** -- six defined failure modes, each with a tested recovery path
- **Test coverage** -- three-tier test strategy (unit, integration, end-to-end)
- **Latency** -- deterministic actions under 10ms; aggregate input rail overhead under 100ms at P95
- **Logging** -- action failures logged at WARNING without exposing user content

### Security/compliance (`COLANG-6xx`)

- Exfiltration prevention (bulk data extraction pattern matching)
- Role boundary enforcement (role-play and instruction-override detection)
- Jailbreak escalation (per-session violation tracking with progressive response)
- Sensitive topic handling (domain-appropriate disclaimers without blocking)

---

## 7) Design Principles

- **Declarative Decides, Computational Computes**: Policy flows express decisions; action functions perform computation. Neither layer duplicates the other.
- **Fail-Open by Default**: Every action catches exceptions and returns a safe default. A failing action never blocks the pipeline.
- **Deterministic Before Expensive**: Fast checks (string length, regex) run before ML-based checks (injection models, faithfulness scoring).
- **Modular Per-Category**: One flow file per category. Adding a category means adding a file, not modifying existing ones.
- **Lazy Initialization**: Executor singletons are created on first use, not at import time, avoiding failures from missing optional dependencies.

---

## 8) Key Decisions Captured by the Spec

- Replace all built-in runtime safety flows with custom computational executor bridges, preferring multi-layer detection over built-in single-prompt checks
- Use context variables to bridge input-phase detection to output-phase modification (sensitive topic flag, low-confidence flag, topic drift flag)
- Keep session state in-memory (no external persistence), accepting counter resets on worker restarts
- Order input rails deterministic-first (11-flow sequence) and output rails executor-first (7-flow sequence)
- Require conditional import and no-op decorator fallback so the action module is importable without the runtime SDK installed
- Auto-disable the entire subsystem on runtime crash rather than retrying, with the caller receiving an empty response

---

## 9) Acceptance, Evaluation, and Feedback

The spec defines seven system-level acceptance criteria covering: flow file parse validity, action return-type correctness, input/output rail ordering, pipeline resilience across six failure modes, master toggle deactivation, and deterministic action latency budgets. A full traceability matrix links each requirement to its parent specification. Three open questions remain regarding session state persistence, LLM-based action stub completion, and threshold configurability.

---

## 10) External Dependencies

**Required:** Guardrails runtime SDK (flow compilation and pipeline execution), LLM endpoint (intent matching and LLM-based actions)
**Optional:** Language detection library, NLP entity recognition models, transformer-based classification models
**Downstream contract:** The retrieval chain consumes the pipeline's async output as a role/content message dict. The runtime auto-discovers action functions in the configuration directory.

---

## 11) Companion Documents

| Document | Role |
|----------|------|
| `COLANG_GUARDRAILS_SPEC.md` | Authoritative requirements baseline (60 requirements, v1.0.0) |
| `COLANG_GUARDRAILS_IMPLEMENTATION.md` | Implementation guide |
| `COLANG_DESIGN_GUIDE.md` | Design reference for syntax, conventions, and patterns |
| `NEMO_GUARDRAILS_SPEC.md` | Parent NeMo integration spec (REQ-1xx through REQ-9xx) |
| `COLANG_GUARDRAILS_SPEC_SUMMARY.md` | This document -- requirements digest |

---

## 12) Sync Status

Aligned to `COLANG_GUARDRAILS_SPEC.md` v1.0.0 as of 2026-04-09.
