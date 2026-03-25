> **Document type:** Authoritative requirements specification (Layer 3)
> **Upstream:** NEMO_GUARDRAILS_SPEC.md (parent NeMo integration spec)
> **Downstream:** COLANG_GUARDRAILS_DESIGN.md, COLANG_GUARDRAILS_IMPLEMENTATION.md
> **Last updated:** 2026-03-25

# Colang 2.0 Guardrails Subsystem -- Specification (v1.0.0)

## Document Information

> **Document intent:** This is a formal specification for the **Colang 2.0 Guardrails Subsystem** -- the declarative policy layer that complements the Python executor rail classes within the NeMo Guardrails integration. This spec defines the Colang flow files, Python action wrappers, runtime integration, and the single `generate_async()` pipeline architecture.
> For the parent NeMo Guardrails integration requirements (REQ-1xx through REQ-9xx covering injection, PII, toxicity, faithfulness, and rail orchestration), see `docs/retrieval/NEMO_GUARDRAILS_SPEC.md`.

| Field | Value |
|-------|-------|
| System | AION RAG Guardrails -- Colang 2.0 Subsystem |
| Document Type | Subsystem Specification -- Colang Declarative Policy Layer |
| Companion Documents | NEMO_GUARDRAILS_SPEC.md (Parent NeMo Spec), COLANG_DESIGN_GUIDE.md (Design Reference), COLANG_GUARDRAILS_IMPLEMENTATION.md (Implementation Guide) |
| Version | 1.0.0 |
| Status | Draft |

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0.0 | 2026-03-25 | AI Assistant | Initial draft -- 9 requirement sections, 60 requirements |

---

## 1. Scope & Definitions

### 1.1 Problem Statement

The parent NeMo Guardrails integration (NEMO_GUARDRAILS_SPEC.md) defines the rail categories and their Python executor implementations: injection detection, PII redaction, toxicity filtering, faithfulness checking, and intent classification. These Python executors perform the computational heavy lifting but lack a declarative policy layer to express:

1. **Query validation policies** -- Length, language, clarity, and abuse rate limits are simple deterministic checks that do not belong in heavy executor classes.
2. **Conversational UX** -- Greetings, farewells, follow-up detection, and administrative queries need structured dialog management, not ad-hoc conditionals in pipeline code.
3. **Safety policy responses** -- Exfiltration prevention, role boundary enforcement, and jailbreak escalation require policy-level decisions about *what to say* and *when to escalate*, distinct from the *detection* logic in Python.
4. **Output quality governance** -- Citation enforcement, confidence-based hedging, length governance, and scope enforcement are policy decisions best expressed declaratively.
5. **RAG-specific dialog patterns** -- Disambiguation, scope explanation, feedback collection, and no-results handling are dialog-level concerns that the Python executor layer does not address.

Colang 2.0 provides a flow-based declarative language that integrates with the NeMo Guardrails runtime, enabling these policy decisions to be expressed as composable, ordered flows that call Python actions for computation and branch on results.

### 1.2 Scope

This specification defines the requirements for the **Colang 2.0 declarative policy layer** within the AION RAG guardrails subsystem. The boundary is:

- **Entry point:** A user message enters the NeMo `generate_async()` pipeline, triggering input rail flows in registered order.
- **Exit point:** The final `$bot_message` value after all output rail flows complete is returned by `generate_async()` to the caller.

Everything between these two points -- input rail flows, standalone dialog flows, generation action, output rail flows, and the Python action wrappers that bridge Colang to Python executors -- is in scope.

### 1.3 Terminology

| Term | Definition |
|------|-----------|
| **Colang 2.0** | NVIDIA's second-generation domain-specific language for defining guardrail flows, using `flow`, `await`, `abort`, and variable assignment syntax |
| **Flow** | A named Colang procedure that executes a sequence of actions, conditionals, and bot responses. Flows follow naming conventions that determine their role (rail vs. dialog) |
| **Input Rail Flow** | A flow named `input rails *` that is registered in `config.yml` and runs before generation. Can `abort` to block the query |
| **Output Rail Flow** | A flow named `output rails *` that is registered in `config.yml` and runs after generation. Can `abort` to replace the response or modify `$bot_message` |
| **Standalone Dialog Flow** | A flow that does not follow the `input rails *` / `output rails *` naming convention. Auto-discovered by NeMo and matched by intent before the rail pipeline |
| **Action** | A Python async function decorated with `@action()` that is callable from Colang flows via `await action_name(...)`. Returns a dict for Colang variable assignment |
| **Action-Result Pattern** | The dual-layer design where Colang calls a Python action, receives a dict result, and branches on the result fields to make policy decisions |
| **Fail-Open** | Error handling strategy where an action that raises an exception returns a default passing/no-op result rather than blocking the pipeline |
| **`$user_message`** | NeMo context variable containing the current user query text, readable and writable by input rail flows |
| **`$bot_message`** | NeMo context variable containing the generated response text, readable and writable by output rail flows |
| **`abort`** | Colang keyword that stops the current rail pipeline and returns the most recent `bot say` message as the response |
| **Python Executor** | The `InputRailExecutor` or `OutputRailExecutor` class that runs multiple Python rail checks (injection, PII, toxicity, faithfulness) in a coordinated execution |
| **Rail Merge Gate** | The `RailMergeGate` class that combines query processing results with input rail verdicts into a single routing decision |

### 1.4 Requirement Priority Levels

This document uses RFC 2119 language:

- **MUST** -- Absolute requirement. The system is non-conformant without it.
- **SHOULD** -- Recommended. May be omitted only with documented justification.
- **MAY** -- Optional. Included at the implementor's discretion.

### 1.5 Requirement Format

Each requirement follows this structure:

> **COLANG-xxx** | Priority: MUST/SHOULD/MAY
> **Description:** What the system shall do.
> **Rationale:** Why this requirement exists.
> **Acceptance Criteria:** How to verify conformance.

Requirements use the **COLANG-xxx** prefix to distinguish from the parent NeMo spec (which uses REQ-xxx). Where a Colang requirement traces to a parent NeMo requirement, the traceability is noted.

Requirements are grouped by section with the following ID ranges:

| Section | ID Range | Component |
|---------|----------|-----------|
| Section 3 | COLANG-1xx | File Structure & Syntax |
| Section 4 | COLANG-2xx | Python Actions |
| Section 5 | COLANG-3xx | Input Rails |
| Section 6 | COLANG-4xx | Conversation Management |
| Section 7 | COLANG-5xx | Output Rails |
| Section 8 | COLANG-6xx | Safety & Compliance |
| Section 9 | COLANG-7xx | RAG Dialog Patterns |
| Section 10 | COLANG-8xx | Runtime Integration |
| Section 11 | COLANG-9xx | Non-Functional Requirements |

### 1.6 Assumptions & Constraints

| ID | Assumption / Constraint | Impact if Violated |
|----|------------------------|--------------------|
| A-1 | Python 3.10+ runtime with `nemoguardrails>=0.21.0` installed | Colang 2.0 syntax will not parse; `@action()` decorator unavailable |
| A-2 | Ollama or compatible LLM endpoint available for LLM-based actions (`check_query_ambiguity`, `check_source_scope`) | LLM-based actions return stub/default results via fail-open |
| A-3 | The `config/guardrails/` directory is the NeMo configuration directory | NeMo will not auto-discover `.co` files or `actions.py` |
| A-4 | The NeMo runtime is initialized once at worker startup (per REQ-701) | Per-query initialization adds 2-5s overhead, violating latency budgets |
| A-5 | Session state for abuse/jailbreak tracking is in-memory and not persisted across worker restarts | Escalation counters reset on restart; determined acceptable for current scale |
| A-6 | The `langdetect` library is available for language detection | `detect_language` action fails open, treating unknown languages as supported |

### 1.7 Design Principles

| Principle | Description |
|-----------|-------------|
| **Colang Decides, Python Computes** | Colang flows express policy decisions (block, modify, hedge, escalate). Python actions perform computation (regex matching, rate counting, executor delegation). Neither layer duplicates the other's responsibility. |
| **Fail-Open by Default** | Every Python action catches exceptions and returns a default passing result. A failing action never blocks the pipeline. This matches the parent spec's fail-safe principle (REQ-902). |
| **Deterministic Before Expensive** | Input rails are ordered so fast deterministic checks (length, language, clarity) run before expensive Python executor calls. Output rails run the Python executor first, then apply lightweight Colang policy checks. |
| **Modular Per-Category** | Each `.co` file covers one flow category. Adding a new flow category means adding a new file, not modifying existing ones. |
| **Lazy Initialization** | Rail class instances and executor singletons are created on first action call, not at module import time. This avoids import-time failures when optional dependencies are unavailable. |

### 1.8 Out of Scope

**Out of scope -- this spec:**
- Python rail class internals (injection detection layers, PII entity recognition, toxicity scoring, faithfulness checking) -- covered by `NEMO_GUARDRAILS_SPEC.md` REQ-2xx through REQ-6xx
- Rail orchestration scheduling (parallel input rails, sequential output rails, merge gate priority) -- covered by `NEMO_GUARDRAILS_SPEC.md` REQ-7xx
- Prometheus metrics and OpenTelemetry spans -- covered by `NEMO_GUARDRAILS_SPEC.md` REQ-904, REQ-905

**Out of scope -- this project:**
- Training custom Colang intent models
- Multi-language flow definitions (English-only)
- Persistent session state across worker restarts
- User-configurable Colang flows at runtime (flows are deployment-time configuration)

---

## 2. System Overview

### 2.1 Architecture Diagram

```
User Message
    |
    v
+=========================================================+
| NeMo generate_async() [single call]                     |
|                                                         |
|  INPUT RAILS (registered order):                        |
|  +---------------------------------------------------+  |
|  | [1] check query length     (input_rails.co)       |  |
|  | [2] check language         (input_rails.co)       |  |
|  | [3] check query clarity    (input_rails.co)       |  |
|  | [4] check abuse            (input_rails.co)       |  |
|  | [5] check exfiltration     (safety.co)            |  |
|  | [6] check role boundary    (safety.co)            |  |
|  | [7] check jailbreak escal. (safety.co)            |  |
|  | [8] check sensitive topic  (safety.co)            |  |
|  | [9] check off topic        (conversation.co)      |  |
|  | [10] check ambiguity       (dialog_patterns.co)   |  |
|  | [11] run python executor   (input_rails.co)       |  |
|  +---------------------------------------------------+  |
|           |                                             |
|           v  (if not aborted)                           |
|  STANDALONE DIALOG FLOWS (auto-discovered):             |
|  +---------------------------------------------------+  |
|  | greeting / farewell / admin / follow-up / feedback |  |
|  | topic drift / scope question                      |  |
|  +---------------------------------------------------+  |
|           |                                             |
|           v                                             |
|  GENERATION:                                            |
|  +---------------------------------------------------+  |
|  | rag_retrieve_and_generate() action                |  |
|  +---------------------------------------------------+  |
|           |                                             |
|           v                                             |
|  OUTPUT RAILS (registered order):                       |
|  +---------------------------------------------------+  |
|  | [1] run python executor    (output_rails.co)      |  |
|  | [2] prepend disclaimer     (output_rails.co)      |  |
|  | [3] check no results       (output_rails.co)      |  |
|  | [4] check confidence       (output_rails.co)      |  |
|  | [5] check citations        (output_rails.co)      |  |
|  | [6] check length           (output_rails.co)      |  |
|  | [7] check scope            (output_rails.co)      |  |
|  +---------------------------------------------------+  |
|                                                         |
+=========================================================+
    |
    v
Final Response ($bot_message)
```

### 2.2 Data Flow Summary

| Stage | Input | Output |
|-------|-------|--------|
| Input Rails (11 flows) | `$user_message` (raw user query) | `abort` with rejection message, or `$user_message` (possibly modified by PII redaction) |
| Standalone Dialog Flows | `$user_message` (after input rails) | Canned bot response (greeting, farewell, help, feedback) or `$user_message` augmented with context |
| Generation | `$user_message` (validated query) | `$bot_message` (generated answer with sources and confidence) |
| Output Rails (7 flows) | `$bot_message` (raw generated answer) | `abort` with replacement message, or `$bot_message` (modified with hedges, disclaimers, citation reminders, length adjustments) |

### 2.3 File Layout

| File | Purpose | Rail Flows | Dialog Flows | Actions |
|------|---------|------------|--------------|---------|
| `input_rails.co` | Query validation + Python executor bridge | 5 | 0 | -- |
| `conversation.co` | Multi-turn: greetings, farewells, follow-ups, off-topic, admin | 1 | 9 | -- |
| `output_rails.co` | Response quality + Python executor bridge | 7 | 0 | -- |
| `safety.co` | Exfiltration, role boundary, jailbreak escalation, sensitive topic | 4 | 0 | -- |
| `dialog_patterns.co` | Disambiguation, scope explanation, feedback | 1 | 6 | -- |
| `actions.py` | Python action wrappers (NeMo auto-discovered) | -- | -- | 26 |
| `config.yml` | NeMo runtime configuration, rail registration | -- | -- | -- |

---

## 3. File Structure & Syntax

> **COLANG-101** | Priority: MUST
>
> **Description:** All Colang flow definitions MUST use Colang 2.0 syntax as specified by `nemoguardrails>=0.21.0`. The `config.yml` MUST declare `colang_version: "2.x"`.
>
> **Rationale:** Colang 1.0 syntax (`define user/bot/flow`) is incompatible with 2.0 features (parallel flows, event-driven architecture, `await`/`abort` keywords). Declaring the version explicitly ensures the NeMo parser uses the correct grammar. Traces to parent REQ-102 (Colang 2.0 flow definitions).
>
> **Acceptance Criteria:** The `config.yml` file contains `colang_version: "2.x"`. All `.co` files parse without `SyntaxError` when loaded by `RailsConfig.from_path()`. No Colang 1.0 `define` keywords appear in any `.co` file.

> **COLANG-103** | Priority: MUST
>
> **Description:** The guardrails configuration directory MUST contain exactly five `.co` flow files (`input_rails.co`, `conversation.co`, `output_rails.co`, `safety.co`, `dialog_patterns.co`), one `actions.py` file, and one `config.yml` file.
>
> **Rationale:** The modular per-category file layout ensures each flow category is independently maintainable. NeMo auto-discovers all `.co` files and the `actions.py` in the configuration directory. Traces to parent REQ-704 (dedicated configuration directory).
>
> **Acceptance Criteria:** The `config/guardrails/` directory contains all seven files. Removing any `.co` file causes the corresponding flows to become unavailable. The `actions.py` file is auto-discovered by NeMo at runtime initialization.

> **COLANG-105** | Priority: MUST
>
> **Description:** Rail flows MUST follow the NeMo naming convention `input rails <name>` for input rails and `output rails <name>` for output rails. Flows that do not follow this convention MUST be treated as standalone dialog flows.
>
> **Rationale:** NeMo uses the naming convention to distinguish between rail flows (executed in registered order, can `abort`) and dialog flows (matched by intent, auto-discovered). Incorrect naming causes flows to be wired into the wrong execution path.
>
> **Acceptance Criteria:** All 18 rail flows (11 input, 7 output) follow the `input rails *` / `output rails *` naming convention. All 15 standalone dialog flows do not use these prefixes. NeMo correctly wires rail flows from `config.yml` registration and auto-discovers dialog flows.

> **COLANG-107** | Priority: MUST
>
> **Description:** The flow file distribution MUST match the following counts: `input_rails.co` contains 5 flows, `conversation.co` contains 10 flows, `output_rails.co` contains 7 flows, `safety.co` contains 4 flows, and `dialog_patterns.co` contains 7 flows, totaling 33 flows.
>
> **Rationale:** The flow counts reflect the implemented category decomposition. Deviation indicates missing or duplicated flow definitions.
>
> **Acceptance Criteria:** Each `.co` file contains the specified number of `flow` definitions. The total count across all files is 33.

> **COLANG-109** | Priority: MUST
>
> **Description:** Colang flows MUST call Python actions using the `await` keyword (e.g., `$result = await action_name(param=$variable)`) and MUST assign action results to Colang context variables for conditional branching.
>
> **Rationale:** The `await` keyword is required by Colang 2.0 for action invocation. Assigning results to context variables enables the action-result pattern where Colang decides and Python computes.
>
> **Acceptance Criteria:** Every action call in every `.co` file uses the `await` keyword. Every action result is assigned to a `$variable` and used in a subsequent `if` condition or variable assignment.

> **COLANG-111** | Priority: SHOULD
>
> **Description:** Each `.co` file SHOULD include a comment header describing the file's purpose, the flow category it covers, and whether its flows are rails or standalone dialog flows.
>
> **Rationale:** Comment headers provide orientation for maintainers reading flow files without needing to cross-reference the spec or config.yml.
>
> **Acceptance Criteria:** Each `.co` file begins with a comment block (lines starting with `#`) that states the file's purpose and flow type (rail vs. dialog).

---

## 4. Python Actions

> **COLANG-201** | Priority: MUST
>
> **Description:** The `actions.py` file MUST contain exactly 26 Python action functions, each decorated with `@action()` from `nemoguardrails.actions`. The 26 actions MUST consist of: 8 actions wrapping existing rail classes (`check_injection`, `detect_pii`, `check_toxicity`, `check_topic_safety`, `check_faithfulness`, `run_input_rails`, `run_output_rails`, `rag_retrieve_and_generate`) and 18 lightweight deterministic or rule-based actions.
>
> **Rationale:** The action count reflects the implemented bridge between Colang policy flows and Python computation. Each action serves a specific flow. Missing actions cause Colang flows to fail at runtime.
>
> **Acceptance Criteria:** The `actions.py` file contains exactly 26 functions decorated with `@action()`. Each function is callable from Colang flows by name. No action name collides with NeMo built-in action names.

> **COLANG-203** | Priority: MUST
>
> **Description:** Every Python action MUST return a `dict` (not a dataclass, TypedDict, or other structured type). The dict keys MUST match the field names referenced by the calling Colang flow's conditional logic.
>
> **Rationale:** NeMo serializes action results into Colang context variables. Only plain dicts are reliably deserialized. A key mismatch between the action return and the Colang flow's `$result.field` access causes a runtime `AttributeError`.
>
> **Acceptance Criteria:** Every `@action()` function has a return type annotation of `dict`. Every key in the returned dict is referenced by at least one Colang flow's `$result.key` expression. No action returns a non-dict type.

> **COLANG-205** | Priority: MUST
>
> **Description:** Every Python action MUST be decorated with `@_fail_open(default)` where `default` is a dict representing a safe/passing result. When the action raises any exception, the decorator MUST catch the exception, log a warning, and return the default dict.
>
> **Rationale:** A failing action must not block the pipeline. The fail-open decorator ensures that transient errors (import failures, network timeouts, missing dependencies) degrade gracefully rather than crashing the NeMo pipeline. Supports the fail-open design principle and traces to parent REQ-902.
>
> **Acceptance Criteria:** Every `@action()` function also has the `@_fail_open(...)` decorator with a non-empty default dict. Given an action that raises `RuntimeError`, the decorator returns the default dict and the pipeline continues. A warning-level log entry is emitted containing the action name and error message.

> **COLANG-207** | Priority: MUST
>
> **Description:** The `actions.py` module MUST use conditional import for the `nemoguardrails` package. When `nemoguardrails` is not installed, the module MUST define a no-op `@action()` decorator that passes through the decorated function unchanged.
>
> **Rationale:** The actions module is imported in test environments where `nemoguardrails` may not be installed (e.g., when `RAG_NEMO_ENABLED=false`). A hard import failure would prevent testing deterministic actions in isolation. Traces to parent REQ-907 (inert when disabled).
>
> **Acceptance Criteria:** Importing `config.guardrails.actions` succeeds when `nemoguardrails` is not installed. All deterministic actions (`check_query_length`, `check_exfiltration`, etc.) are callable without the NeMo runtime.

> **COLANG-209** | Priority: MUST
>
> **Description:** Actions wrapping existing rail classes (`run_input_rails`, `run_output_rails`) MUST use lazy initialization for executor singletons. Rail class instances MUST be created on first action call, not at module import time.
>
> **Rationale:** Eager initialization at import time fails when optional dependencies (spaCy models, YAML pattern files, model classifiers) are unavailable. Lazy initialization defers these costs to the first actual invocation, by which time the runtime environment is fully configured.
>
> **Acceptance Criteria:** Importing `actions.py` does not instantiate any rail class. The first call to `run_input_rails()` triggers `InputRailExecutor` construction. Subsequent calls reuse the singleton. The `_rail_instances` dict is empty immediately after import.

> **COLANG-211** | Priority: MUST
>
> **Description:** Actions requiring per-session state (`check_abuse_pattern`, `check_jailbreak_escalation`) MUST use in-memory dicts keyed by session ID. The session ID MUST be obtained from the `context` parameter provided by the NeMo runtime.
>
> **Rationale:** Session-scoped escalation requires tracking state across multiple queries from the same user session. In-memory storage is sufficient for single-worker deployments and avoids external state dependencies.
>
> **Acceptance Criteria:** `check_abuse_pattern` tracks query timestamps per session and flags sessions exceeding 20 queries per minute. `check_jailbreak_escalation` tracks violation counts per session and escalates from `"none"` to `"warn"` (1-2 violations) to `"block"` (3+ violations). Different session IDs maintain independent state.

> **COLANG-213** | Priority: MUST
>
> **Description:** The `run_input_rails` action MUST delegate to the `InputRailExecutor` and `RailMergeGate`, executing all Python input rails (injection, PII, toxicity, topic safety) and returning a dict with keys: `action` (`"pass"` | `"reject"` | `"modify"`), `intent`, `redacted_query`, `reject_message`, and `metadata`.
>
> **Rationale:** This action is the bridge between Colang's declarative input rail pipeline and the full Python executor stack. It must preserve the merge gate's priority logic (injection overrides all, toxicity overrides intent, PII is non-blocking). Traces to parent REQ-707 (merge gate priority).
>
> **Acceptance Criteria:** When called with a clean query, returns `action: "pass"`. When called with an injection attempt, returns `action: "reject"` with a non-empty `reject_message`. When called with a query containing PII, returns `action: "modify"` with `redacted_query` containing placeholder tokens.

> **COLANG-215** | Priority: MUST
>
> **Description:** The `run_output_rails` action MUST delegate to the `OutputRailExecutor`, executing all Python output rails (faithfulness, PII, toxicity) and returning a dict with keys: `action` (`"pass"` | `"reject"` | `"modify"`), `redacted_answer`, `reject_message`, and `metadata`.
>
> **Rationale:** This action bridges Colang output rails to the Python executor stack. Faithfulness rejection must be distinguished from PII/toxicity modification so the Colang flow can emit the appropriate bot response.
>
> **Acceptance Criteria:** When called with a faithful answer, returns `action: "pass"`. When called with an unfaithful answer (faithfulness score below threshold), returns `action: "reject"` with a fallback message. When called with an answer containing PII, returns `action: "modify"` with redacted content.

> **COLANG-217** | Priority: MUST
>
> **Description:** The `rag_retrieve_and_generate` action MUST call the RAG retrieval+generation pipeline and return a dict with keys: `answer`, `sources`, and `confidence`. This action MUST replace NeMo's default LLM call as the generation step.
>
> **Rationale:** The RAG pipeline's retrieval+generation is the core value of the system. Using NeMo's default LLM call would bypass retrieval entirely, producing ungrounded answers. The action bridges NeMo's flow-based architecture to the existing RAG chain.
>
> **Acceptance Criteria:** When called with a valid query, the action returns a non-empty `answer` with `sources` listing retrieved document identifiers. When the RAG chain reference is not set (e.g., during tests), the action returns empty defaults via the fail-open decorator.

> **COLANG-219** | Priority: MUST
>
> **Description:** Actions wrapping existing rail classes MUST respect the existing environment variable toggles. When a rail's toggle is set to `false` (e.g., `RAG_NEMO_INJECTION_ENABLED=false`), the corresponding action MUST return an immediate passing result without instantiating the rail class.
>
> **Rationale:** Per-rail toggles (REQ-705) must propagate through the Colang action layer. If an operator disables injection detection, the Colang flow calling `check_injection` must receive a pass verdict.
>
> **Acceptance Criteria:** With `RAG_NEMO_INJECTION_ENABLED=false`, calling `run_input_rails()` skips injection detection. The `InputRailExecutor` is constructed with `injection_detector=None`. The returned dict has `action: "pass"`.

> **COLANG-221** | Priority: SHOULD
>
> **Description:** Each lightweight deterministic action SHOULD include boundary value handling: `check_query_length` SHOULD handle empty strings and whitespace-only input. `check_answer_length` SHOULD handle empty strings. `check_citations` SHOULD handle empty strings.
>
> **Rationale:** Edge-case inputs are common in pipeline scenarios (empty responses from failed generation, whitespace queries from UI autofill). Actions must produce valid dicts regardless of input quality.
>
> **Acceptance Criteria:** `check_query_length("")` returns `valid: false`. `check_answer_length("")` returns `valid: false`. `check_citations("")` returns `has_citations: false`. No action raises an exception on empty or whitespace input.

---

## 5. Input Rails

> **COLANG-301** | Priority: MUST
>
> **Description:** The system MUST provide a `check query length` input rail that validates user queries against minimum (3 characters) and maximum (2000 characters) length bounds. Queries outside these bounds MUST be rejected with a descriptive message via `abort`.
>
> **Rationale:** Extremely short queries (1-2 characters) cannot carry meaningful search intent. Extremely long queries may be adversarial or indicate a paste error. Enforcing length bounds at the Colang layer provides fast rejection before any expensive processing.
>
> **Acceptance Criteria:** A query of 2 characters triggers `abort` with a message containing "too short". A query of 2001 characters triggers `abort` with a message containing "too long" or "2000 characters". A query of 10 characters passes this rail.

> **COLANG-303** | Priority: MUST
>
> **Description:** The system MUST provide a `check language` input rail that detects the query language and rejects non-English queries with a message directing the user to rephrase in English. The rail MUST use the `detect_language` action.
>
> **Rationale:** The RAG pipeline's LLM, embeddings, and knowledge base are English-only. Non-English queries produce poor retrieval results and confusing responses. Early rejection with a clear message is better than a garbled answer.
>
> **Acceptance Criteria:** A query in Spanish ("Cual es el mecanismo de atencion?") triggers `abort` with a message containing "English". A query in English ("What is the attention mechanism?") passes this rail.

> **COLANG-305** | Priority: MUST
>
> **Description:** The system MUST provide a `check query clarity` input rail that detects vague or underspecified queries using heuristics (word count below threshold, all stopwords, no content-bearing terms). Unclear queries MUST be rejected with a suggestion for improvement.
>
> **Rationale:** Single-word or all-stopword queries ("it", "the what") produce poor retrieval results. Prompting the user to add keywords improves downstream result quality.
>
> **Acceptance Criteria:** A query of "it" triggers `abort` with a suggestion to provide more detail. A query of "the and or" triggers `abort` with a suggestion to include specific terms. A query of "How does BM25 compare to dense retrieval?" passes this rail.

> **COLANG-307** | Priority: MUST
>
> **Description:** The system MUST provide a `check abuse` input rail that tracks query rate per session and flags sessions exceeding 20 queries within a 60-second window. Flagged queries MUST be rejected with a message about query pattern detection.
>
> **Rationale:** Rapid-fire queries (>20/minute) indicate automated enumeration or data harvesting, not legitimate human search behavior. Rate limiting at the Colang layer prevents abuse from reaching the retrieval pipeline.
>
> **Acceptance Criteria:** A session submitting its 21st query within 60 seconds triggers `abort` with a message about the query pattern being flagged. A session submitting 5 queries in 60 seconds passes this rail. Query timestamps older than 60 seconds are excluded from the count.

> **COLANG-309** | Priority: MUST
>
> **Description:** The system MUST provide a `run python executor` input rail that calls the `run_input_rails` action to execute the full Python executor stack (injection detection, PII redaction, toxicity filtering, topic safety checking) via the `InputRailExecutor` and `RailMergeGate`. This rail MUST be registered last in the input rail order.
>
> **Rationale:** The Python executor performs the computationally expensive, ML-based safety checks. Running it last ensures that queries rejected by cheaper Colang checks never reach the executor, saving compute. Traces to parent REQ-702 (parallel input rail execution within the executor).
>
> **Acceptance Criteria:** The `config.yml` registers `input rails run python executor` as the last entry in the input rail flow list. When this rail returns `action: "reject"`, the flow emits the rejection message and calls `abort`. When it returns `action: "modify"`, the flow updates `$user_message` with the redacted query.

> **COLANG-311** | Priority: MUST
>
> **Description:** Input rails MUST execute in the order registered in `config.yml`. The registered order MUST be: (1) query length, (2) language, (3) query clarity, (4) abuse, (5) exfiltration, (6) role boundary, (7) jailbreak escalation, (8) sensitive topic, (9) off topic, (10) ambiguity, (11) Python executor.
>
> **Rationale:** The ordering ensures fast deterministic checks run before slower checks, and safety checks run before content checks. The Python executor (most expensive) runs only if all policy checks pass. Supports the "deterministic before expensive" design principle.
>
> **Acceptance Criteria:** The `config.yml` `rails.input.flows` list contains exactly 11 entries in the specified order. A query rejected by `check query length` (position 1) never triggers `run python executor` (position 11).

---

## 6. Conversation Management

> **COLANG-401** | Priority: MUST
>
> **Description:** The system MUST provide intent-matching flows for greeting utterances (`user said greeting`) and farewell utterances (`user said farewell`). Each intent flow MUST include at least 5 example utterances.
>
> **Rationale:** Greetings and farewells are the most common non-search intents. Without explicit handling, they would enter the RAG pipeline and produce irrelevant results. Minimum 5 examples ensures reasonable intent coverage. Traces to parent REQ-101 (intent taxonomy) and REQ-102 (minimum 5 examples).
>
> **Acceptance Criteria:** `user said greeting` matches "hello", "hi there", "hey", "good morning", and "greetings". `user said farewell` matches "goodbye", "bye", "see you later", "thanks, bye", and "that's all". Each intent has at least 5 utterance examples.

> **COLANG-403** | Priority: MUST
>
> **Description:** The system MUST provide handler flows (`handle greeting`, `handle farewell`) that respond to greeting and farewell intents with canned messages. These handlers MUST be standalone dialog flows, not rail flows.
>
> **Rationale:** Greetings and farewells do not need to block the pipeline (they are not security concerns) -- they need to provide a friendly response. Standalone dialog flows are matched by NeMo's intent engine before the rail pipeline runs. Traces to parent REQ-103 (non-search intent routing).
>
> **Acceptance Criteria:** "Hello" triggers `handle greeting` and produces a bot response containing "help you search the knowledge base". "Goodbye" triggers `handle farewell` and produces a bot response containing "Feel free to return". Neither handler calls `abort` or blocks the rail pipeline.

> **COLANG-405** | Priority: MUST
>
> **Description:** The system MUST provide an intent-matching flow for administrative/help queries (`user said administrative`) and a handler flow (`handle administrative`) that responds with a description of the system's capabilities.
>
> **Rationale:** Users asking "help" or "what can you do" need a capabilities description, not a search result. Traces to parent REQ-101 (administrative intent).
>
> **Acceptance Criteria:** "help" and "what can you do" match `user said administrative`. The handler responds with a message explaining that the system searches the knowledge base.

> **COLANG-407** | Priority: MUST
>
> **Description:** The system MUST provide follow-up detection flows (`user said follow up`, `handle follow up`) that recognize continuation queries (e.g., "tell me more", "can you elaborate") and attempt to augment the query with prior conversation context via the `handle_follow_up` action. When no prior context exists, the handler MUST ask the user to restate their question and call `abort`.
>
> **Rationale:** Follow-up queries like "tell me more" are meaningless without the context of the prior answer. The `handle_follow_up` action checks NeMo's conversation context for prior Q&A pairs and augments the query if possible.
>
> **Acceptance Criteria:** "tell me more" matches `user said follow up`. When the action returns `has_context: true`, `$user_message` is updated with the augmented query. When the action returns `has_context: false`, the handler emits a message asking for clarification and calls `abort`.

> **COLANG-409** | Priority: MUST
>
> **Description:** The system MUST provide a `check off topic` input rail that matches off-topic utterances (e.g., "what's the weather", "tell me a joke") and rejects them with a message directing the user to ask knowledge-base-related questions. This MUST be an input rail flow (not a standalone dialog flow) so it can block the pipeline via `abort`.
>
> **Rationale:** Off-topic queries must be blocked from entering the retrieval pipeline because they waste compute and return irrelevant results. Unlike greetings (which are harmless side-channels), off-topic queries need pipeline-blocking behavior. Traces to parent REQ-103 (off-topic routing).
>
> **Acceptance Criteria:** "what's the weather" triggers the off-topic rail and produces an `abort` with a message about being designed for knowledge base search. The flow is registered in `config.yml` as an input rail. A legitimate RAG query does not match the off-topic intent.

> **COLANG-411** | Priority: SHOULD
>
> **Description:** The system SHOULD provide a `check topic drift` flow that detects when the conversation topic changes between turns and sets a context flag (`$topic_drifted = True`). This flow SHOULD be a standalone dialog flow, not an input rail.
>
> **Rationale:** When a user switches topics mid-conversation (e.g., from asking about transformers to asking about databases), the retrieval pipeline should clear prior context and search fresh. The context flag is consumed by the `rag_retrieve_and_generate` action.
>
> **Acceptance Criteria:** The `check topic drift` flow calls the `check_topic_drift` action and sets `$topic_drifted = True` when drift is detected. The flow does not call `abort` (it sets state, not blocks).

---

## 7. Output Rails

> **COLANG-501** | Priority: MUST
>
> **Description:** The system MUST provide a `run python executor` output rail that calls the `run_output_rails` action to execute the full Python output executor stack (faithfulness checking, PII redaction, toxicity filtering). This rail MUST be registered first in the output rail order.
>
> **Rationale:** The Python output executor performs the most critical output safety checks (faithfulness, PII, toxicity). Running it first ensures these checks execute before lighter Colang policy flows. An answer rejected by the faithfulness checker should not undergo citation enforcement or length adjustment.
>
> **Acceptance Criteria:** The `config.yml` registers `output rails run python executor` as the first entry in the output rail flow list. When the action returns `action: "reject"`, the flow emits the rejection message and calls `abort`. When it returns `action: "modify"`, the flow updates `$bot_message` with the redacted answer.

> **COLANG-503** | Priority: MUST
>
> **Description:** The system MUST provide a `prepend disclaimer` output rail that prepends a domain-specific disclaimer to `$bot_message` when the `$sensitive_disclaimer` context variable was set by the `check sensitive topic` input rail. When `$sensitive_disclaimer` is not set, this rail MUST be a no-op.
>
> **Rationale:** Sensitive topic detection happens at input time, but the disclaimer must be prepended to the output. The context variable bridges these two phases. This rail must run before other output modifications to ensure the disclaimer appears at the beginning of the response.
>
> **Acceptance Criteria:** When `$sensitive_disclaimer` contains "This is not medical advice...", the rail prepends this text to `$bot_message`. When `$sensitive_disclaimer` is not set (undefined or falsy), `$bot_message` is unchanged.

> **COLANG-505** | Priority: MUST
>
> **Description:** The system MUST provide a `check no results` output rail that inspects retrieval results quality via the `check_retrieval_results` action. When no results were found (`has_results: false`), the rail MUST respond with a helpful no-results message and call `abort`. When results have low average confidence (below 0.3), the rail MUST prepend a low-confidence note and set the `$low_confidence_noted` context variable.
>
> **Rationale:** Empty or very low-confidence retrieval results produce poor answers. The user needs a clear signal that the system could not find relevant information, along with suggestions for improving the query.
>
> **Acceptance Criteria:** When `has_results` is `false`, the rail emits a message about rephrasing and calls `abort`. When `avg_confidence` is 0.2 (below 0.3), the rail prepends a note about limited matches and sets `$low_confidence_noted = True`. When results are present with confidence above 0.3, `$bot_message` is unchanged.

> **COLANG-507** | Priority: MUST
>
> **Description:** The system MUST provide a `check citations` output rail that verifies the generated answer contains citation patterns (e.g., `[Source: ...]`, `[1]`, "According to", "Based on the document"). When no citations are found, the rail MUST append a citation reminder to `$bot_message`.
>
> **Rationale:** RAG answers should reference their source documents. When the LLM omits citations, appending a reminder ensures the user knows that source metadata is available.
>
> **Acceptance Criteria:** An answer containing "[Source: doc1.pdf]" passes this rail unchanged. An answer with no citation patterns has "Note: Sources are available in the response metadata." appended. The check is case-insensitive.

> **COLANG-509** | Priority: MUST
>
> **Description:** The system MUST provide a `check confidence` output rail that reads retrieval confidence via the `check_response_confidence` action and applies confidence-based routing. When confidence is `"none"`, the rail MUST respond with a no-relevant-information message and call `abort`. When confidence is `"low"` and `$low_confidence_noted` is not set, the rail MUST prepend hedge language to `$bot_message`.
>
> **Rationale:** Low-confidence answers should be hedged to set user expectations. The `$low_confidence_noted` check prevents double-hedging when the no-results rail (COLANG-505) has already prepended a low-confidence note.
>
> **Acceptance Criteria:** When confidence is `"none"`, the rail emits a no-information message and calls `abort`. When confidence is `"low"` and `$low_confidence_noted` is not set, `$bot_message` is prepended with "Based on limited information in the knowledge base:". When `$low_confidence_noted` is `True`, no additional hedge is applied. When confidence is `"high"`, `$bot_message` is unchanged.

> **COLANG-511** | Priority: MUST
>
> **Description:** The system MUST provide a `check length` output rail that validates answer length against minimum (20 characters) and maximum (5000 characters) bounds. Answers outside these bounds MUST be adjusted via the `adjust_answer_length` action: overly long answers are truncated with an ellipsis, and terse answers are flagged.
>
> **Rationale:** Excessively long answers overwhelm users and may indicate runaway generation. Extremely short answers may indicate generation failure. Length governance ensures consistent response quality.
>
> **Acceptance Criteria:** An answer of 15 characters triggers adjustment. An answer of 6000 characters is truncated to 5000 characters with "..." appended. An answer of 100 characters passes unchanged.

> **COLANG-513** | Priority: MUST
>
> **Description:** The system MUST provide a `check scope` output rail that verifies the generated answer stays within the scope of retrieved context via the `check_source_scope` action. When the answer is determined to be out of scope, the rail MUST respond with a scope-boundary message and call `abort`.
>
> **Rationale:** The RAG system should only provide answers grounded in its knowledge base. Out-of-scope answers may contain hallucinated or unverifiable information.
>
> **Acceptance Criteria:** When `in_scope` is `true`, `$bot_message` passes unchanged. When `in_scope` is `false`, the rail emits a message about only providing answers from the knowledge base and calls `abort`.

> **COLANG-515** | Priority: MUST
>
> **Description:** Output rails MUST execute in the order registered in `config.yml`. The registered order MUST be: (1) Python executor, (2) prepend disclaimer, (3) check no results, (4) check confidence, (5) check citations, (6) check length, (7) check scope.
>
> **Rationale:** The Python executor (faithfulness, PII, toxicity) must run first as the critical safety gate. The disclaimer must be prepended before other modifications so it appears at the top. No-results and confidence checks run before citation/length/scope checks because they may `abort`, avoiding unnecessary downstream processing.
>
> **Acceptance Criteria:** The `config.yml` `rails.output.flows` list contains exactly 7 entries in the specified order. An answer rejected by the Python executor (position 1) never triggers `check scope` (position 7).

> **COLANG-517** | Priority: MUST
>
> **Description:** Output rails that modify `$bot_message` MUST use the two-step action-result pattern: call the action into a temporary variable, then extract the `answer` field (e.g., `$mod = await action_name(answer=$bot_message)` followed by `$bot_message = $mod.answer`).
>
> **Rationale:** All actions return dicts (per COLANG-203), not bare strings. Direct assignment of the action result to `$bot_message` would assign the entire dict, corrupting the response. The two-step pattern extracts the string value.
>
> **Acceptance Criteria:** Every output rail that modifies `$bot_message` uses the `$mod = await ...; $bot_message = $mod.answer` pattern. No output rail assigns an action result dict directly to `$bot_message`.

---

## 8. Safety & Compliance

> **COLANG-601** | Priority: MUST
>
> **Description:** The system MUST provide a `check sensitive topic` input rail that detects queries related to medical, legal, or financial domains using keyword matching. When a sensitive topic is detected, the rail MUST set the `$sensitive_disclaimer` context variable with a domain-appropriate disclaimer text. The rail MUST NOT call `abort` -- the query proceeds with the disclaimer flag set.
>
> **Rationale:** Sensitive topic queries are legitimate -- users may ask about medical topics in a healthcare knowledge base. The system should answer but prepend a disclaimer. Blocking these queries would reduce the system's utility. The input-to-output context variable bridge enables cross-phase communication.
>
> **Acceptance Criteria:** A query containing "medication" or "dosage" sets `$sensitive_disclaimer` to a medical disclaimer. A query containing "legal advice" sets it to a legal disclaimer. A query containing "investment advice" sets it to a financial disclaimer. A query about "vector search" does not set the variable. The rail does not call `abort` for any input.

> **COLANG-603** | Priority: MUST
>
> **Description:** The system MUST provide a `check exfiltration` input rail that detects bulk data extraction patterns using regex matching. Detected patterns MUST include: "list all documents/records/entries", "dump everything/all/the database", "show me all/every records/documents", "export the database/data/everything", "give me everything/every entry", "download all", and "extract all". Detection MUST trigger `abort` with a message refusing bulk extraction.
>
> **Rationale:** Bulk extraction attempts seek to enumerate the entire knowledge base, which may contain proprietary or sensitive information. Blocking these at the Colang layer prevents them from reaching the retrieval pipeline.
>
> **Acceptance Criteria:** "list all documents in the database" triggers `abort`. "dump everything" triggers `abort`. "export the database" triggers `abort`. "What is semantic chunking?" does not trigger the rail. The rejection message directs the user to ask specific questions.

> **COLANG-605** | Priority: MUST
>
> **Description:** The system MUST provide a `check role boundary` input rail that detects role-play and instruction-override patterns using regex matching. Detected patterns MUST include: "you are now a", "ignore previous/all/your instructions", "pretend you are/to be", "act as if", "forget everything/your rules/your instructions", "disregard your/all rules/guidelines/instructions", "you have no restrictions", "jailbreak", and "DAN mode". Detection MUST trigger `abort` with a message affirming the system's role as a knowledge base assistant.
>
> **Rationale:** Role-play and instruction-override attacks are common prompt injection vectors. Blocking them at the Colang layer provides an additional defense layer alongside the Python `InjectionDetector`. Supports the defense-in-depth principle.
>
> **Acceptance Criteria:** "ignore previous instructions" triggers `abort`. "you are now a hacker" triggers `abort`. "pretend to be a different AI" triggers `abort`. "DAN mode" triggers `abort`. "How do transformers work?" does not trigger the rail. The rejection message states the system is a knowledge base search assistant.

> **COLANG-607** | Priority: MUST
>
> **Description:** The system MUST provide a `check jailbreak escalation` input rail that tracks policy violation attempt count per session and applies escalating responses. The escalation levels MUST be: `"none"` (0 violations), `"warn"` (1-2 violations, responds with a policy violation warning and calls `abort`), and `"block"` (3+ violations, responds with a session restriction warning and calls `abort`).
>
> **Rationale:** Persistent jailbreak attempts indicate a determined adversary. Escalating responses signal to the user that their behavior is being tracked, potentially deterring further attempts. The escalation threshold is intentionally low (3 attempts) for safety.
>
> **Acceptance Criteria:** A session's first jailbreak-pattern query (e.g., "ignore instructions") triggers `"warn"` with an `abort`. A session's third jailbreak-pattern query triggers `"block"` with a different, stronger `abort` message mentioning session restrictions. A session with no jailbreak patterns always returns `"none"` and does not trigger `abort`. Different sessions have independent violation counts.

---

## 9. RAG Dialog Patterns

> **COLANG-701** | Priority: MUST
>
> **Description:** The system MUST provide a `check ambiguity` input rail that detects ambiguous queries with multiple valid interpretations via the `check_query_ambiguity` action. When ambiguity is detected, the rail MUST respond with a disambiguation prompt and call `abort`.
>
> **Rationale:** Ambiguous queries produce inconsistent retrieval results. Prompting the user to clarify their intent before retrieval improves answer quality and user satisfaction.
>
> **Acceptance Criteria:** When the action returns `ambiguous: true` with a disambiguation prompt, the rail emits the prompt and calls `abort`. When the action returns `ambiguous: false`, the query passes through unchanged. The rail is registered in `config.yml` as an input rail.

> **COLANG-703** | Priority: MUST
>
> **Description:** The system MUST provide scope explanation flows (`user asked about scope`, `handle scope question`) that respond to queries about the knowledge base's coverage with a summary obtained from the `get_knowledge_base_summary` action. These MUST be standalone dialog flows, not rail flows.
>
> **Rationale:** Users need to understand what topics the knowledge base covers to formulate effective queries. This is a conversational side-channel that should not block the pipeline.
>
> **Acceptance Criteria:** "what documents do you have" matches `user asked about scope`. The handler calls `get_knowledge_base_summary()` and responds with the summary text. "what topics do you cover" and "what's in the knowledge base" also match.

> **COLANG-705** | Priority: MUST
>
> **Description:** The system MUST provide feedback collection flows (`user gave positive feedback`, `handle positive feedback`, `user gave negative feedback`, `handle negative feedback`) that recognize user satisfaction signals and respond appropriately. Positive feedback flows MUST respond with an encouraging message. Negative feedback flows MUST respond with an offer to rephrase and provide more context. These MUST be standalone dialog flows.
>
> **Rationale:** Acknowledging user feedback improves the conversational UX. Negative feedback responses that suggest rephrasing help the user get better results on their next attempt.
>
> **Acceptance Criteria:** "thanks" and "great answer" match `user gave positive feedback`. "that's wrong" and "not what I asked" match `user gave negative feedback`. Positive feedback handler responds with "Glad that was helpful!". Negative feedback handler responds with a suggestion to rephrase.

> **COLANG-707** | Priority: SHOULD
>
> **Description:** Intent-matching flows for dialog patterns SHOULD include at least 4 example utterances each for scope queries, positive feedback, and negative feedback.
>
> **Rationale:** Sufficient example coverage ensures reliable intent matching. Fewer than 4 examples per intent increases false-negative rates for common user expressions.
>
> **Acceptance Criteria:** `user asked about scope` has at least 4 utterance examples. `user gave positive feedback` has at least 4 utterance examples. `user gave negative feedback` has at least 4 utterance examples.

---

## 10. Runtime Integration

> **COLANG-801** | Priority: MUST
>
> **Description:** The `GuardrailsRuntime` class MUST implement the singleton pattern with thread-safe initialization. The `get()` class method MUST return the same instance across all calls within a process.
>
> **Rationale:** NeMo runtime initialization is expensive (loading config, compiling Colang flows, potentially loading models). Multiple instances would waste memory and introduce inconsistent state. Thread-safety is required because multiple request-handling threads may call `get()` concurrently. Traces to parent REQ-701 (once at startup, reused across queries).
>
> **Acceptance Criteria:** `GuardrailsRuntime.get() is GuardrailsRuntime.get()` is `True`. Concurrent calls to `get()` from multiple threads all receive the same instance. The constructor is not called directly by callers.

> **COLANG-803** | Priority: MUST
>
> **Description:** The `GuardrailsRuntime.initialize()` method MUST load the NeMo configuration from the specified directory using `RailsConfig.from_path()` and compile all Colang flows. The method MUST be idempotent -- subsequent calls after successful initialization MUST be no-ops.
>
> **Rationale:** Idempotent initialization prevents accidental re-initialization during application lifecycle events (e.g., health checks, reconnection logic). `RailsConfig.from_path()` auto-discovers all `.co` files and `actions.py` in the config directory.
>
> **Acceptance Criteria:** Calling `initialize()` twice with the same config directory succeeds without error. The second call does not re-load configuration or re-compile flows. The `initialized` property returns `True` after successful initialization.

> **COLANG-805** | Priority: MUST
>
> **Description:** The `GuardrailsRuntime.initialize()` method MUST fail fast on Colang syntax errors by raising `SyntaxError`. For all other initialization errors, the method MUST log the error and auto-disable guardrails by setting the `_auto_disabled` flag.
>
> **Rationale:** Colang syntax errors indicate a configuration problem that must be fixed before deployment -- failing fast surfaces these at startup. Other errors (network issues, model loading failures) are transient and should not crash the worker. Auto-disabling ensures the pipeline continues without guardrails. Traces to parent REQ-902 (graceful degradation).
>
> **Acceptance Criteria:** A `.co` file with invalid syntax causes `initialize()` to raise `SyntaxError`. A network error during model loading causes `initialize()` to log an error and set `_auto_disabled = True`. After auto-disable, `is_enabled()` returns `False`.

> **COLANG-807** | Priority: MUST
>
> **Description:** The `GuardrailsRuntime.generate_async()` method MUST execute the full NeMo pipeline (input rails, generation, output rails) via a single call to the underlying `LLMRails.generate_async()`. When rails are unavailable (not initialized, auto-disabled, or runtime error), the method MUST return an empty assistant message `{"role": "assistant", "content": ""}`.
>
> **Rationale:** The single `generate_async()` call is the sole entry point for the Colang pipeline. All input rails, the generation action, and all output rails execute within this single call. The fail-open empty response ensures the caller can handle the degraded case. Traces to parent REQ-902 (fail-open on runtime error).
>
> **Acceptance Criteria:** A legitimate query produces an assistant message with non-empty content. When the runtime is not initialized, `generate_async()` returns `{"role": "assistant", "content": ""}` without raising an exception. When a runtime error occurs, the method logs a warning, sets `_auto_disabled = True`, and returns the empty response.

> **COLANG-809** | Priority: MUST
>
> **Description:** The `GuardrailsRuntime.is_enabled()` class method MUST return `True` only when both `RAG_NEMO_ENABLED` is `true` and the runtime has not been auto-disabled due to a prior failure. When `RAG_NEMO_ENABLED` is `false`, no NeMo imports, initializations, or function calls MUST execute.
>
> **Rationale:** The master toggle must fully deactivate the Colang subsystem. Auto-disable provides a runtime kill switch when failures occur. Traces to parent REQ-706 (master toggle) and REQ-907 (inert when disabled).
>
> **Acceptance Criteria:** With `RAG_NEMO_ENABLED=false`, `is_enabled()` returns `False`. After auto-disable, `is_enabled()` returns `False` even if `RAG_NEMO_ENABLED=true`. With both conditions satisfied, `is_enabled()` returns `True`.

> **COLANG-811** | Priority: MUST
>
> **Description:** The `GuardrailsRuntime` MUST provide a `register_actions()` method that registers Python action functions with the NeMo runtime by name. Actions registered via this method MUST be available to Colang flows via `await action_name(...)`.
>
> **Rationale:** While NeMo auto-discovers `actions.py` in the config directory, explicit registration enables programmatic action injection (e.g., setting the RAG chain reference for `rag_retrieve_and_generate`).
>
> **Acceptance Criteria:** After calling `register_actions({"my_action": my_fn})`, a Colang flow can call `await my_action()`. Registering an action when the runtime is not initialized logs a warning and does not raise.

> **COLANG-813** | Priority: MUST
>
> **Description:** The `config.yml` MUST declare the LLM provider configuration for NeMo's internal LLM calls, specifying the engine (Ollama), model, base URL, and temperature. The model and URL MUST be configurable via environment variables with sensible defaults.
>
> **Rationale:** NeMo uses an LLM for intent matching and LLM-based actions. The configuration must match the project's existing Ollama deployment. Environment variable overrides enable per-environment tuning without config file changes. Traces to parent REQ-903 (externalized configuration).
>
> **Acceptance Criteria:** `config.yml` specifies `engine: ollama` with `model: ${RAG_OLLAMA_MODEL:-qwen2.5:3b}` and `base_url: ${RAG_OLLAMA_URL:-http://localhost:11434}`. Setting `RAG_OLLAMA_MODEL=llama3` overrides the default model.

> **COLANG-815** | Priority: MUST
>
> **Description:** The `config.yml` MUST register all NeMo built-in rails as intentionally removed, relying instead on the Python executor actions. The built-in `check jailbreak`, `jailbreak detection heuristics`, `check faithfulness`, `self check facts`, and `self check output` flows MUST NOT be registered.
>
> **Rationale:** The Python `InjectionDetector` provides a superior 4-layer defense compared to NeMo's built-in perplexity-only jailbreak detection. The Python `FaithfulnessChecker` and `ToxicityFilter` provide richer analysis (per-claim scoring, entity hallucination detection) compared to NeMo's simpler single-prompt checks. Both capabilities are preserved through the Colang action bridge.
>
> **Acceptance Criteria:** The `config.yml` `rails.input.flows` list does not contain `check jailbreak` or `jailbreak detection heuristics`. The `rails.output.flows` list does not contain `check faithfulness`, `self check facts`, or `self check output`. All security checks route through the Python executor actions.

---

## 11. Non-Functional Requirements

> **COLANG-901** | Priority: MUST
>
> **Description:** All configurable thresholds, patterns, and parameters used by Python actions MUST be externalized to environment variables or configuration files. Hardcoded values in action implementations MUST have corresponding environment variable overrides or be documented as intentional defaults.
>
> **Rationale:** Hardcoded thresholds (query length bounds, abuse rate limits, escalation thresholds) cannot be tuned without code changes. Operators need deployment-time control over these values. Traces to parent REQ-903 (configuration externalization).
>
> **Acceptance Criteria:** The query length bounds (3, 2000), abuse rate limit (20 queries/60 seconds), jailbreak escalation thresholds (1-2 warn, 3+ block), answer length bounds (20, 5000), and confidence threshold (0.3) are either configurable via environment variables or documented as defaults in the design guide. Individual Python rail toggles (`RAG_NEMO_INJECTION_ENABLED`, `RAG_NEMO_PII_ENABLED`, etc.) control their respective executor actions.

> **COLANG-903** | Priority: MUST
>
> **Description:** The system MUST remain fully operational when `RAG_NEMO_ENABLED=false`. No NeMo-related imports, initializations, or function calls MUST execute. The `actions.py` module MUST be importable without `nemoguardrails` installed.
>
> **Rationale:** Environments without NeMo (development, testing, lightweight deployments) must not encounter import errors or behavioral changes from the Colang subsystem. Traces to parent REQ-907 (inert when disabled).
>
> **Acceptance Criteria:** With `RAG_NEMO_ENABLED=false` and `nemoguardrails` uninstalled: the pipeline processes queries without errors, no NeMo log entries appear, and `import config.guardrails.actions` succeeds.

> **COLANG-905** | Priority: MUST
>
> **Description:** The system MUST provide unit tests for deterministic actions (testable without NeMo runtime), integration tests that verify all `.co` files parse correctly, and end-to-end tests that verify the full `generate_async()` pipeline.
>
> **Rationale:** Safety-critical code requires thorough test coverage. The three-tier test structure ensures: (1) individual action correctness, (2) Colang syntax validity, and (3) full pipeline behavior. Traces to parent REQ-906 (test coverage).
>
> **Acceptance Criteria:** `tests/guardrails/test_colang_actions.py` tests each deterministic action in isolation (positive and negative cases). `tests/guardrails/test_colang_flows.py` verifies all 5 `.co` files parse without `SyntaxError`. `tests/guardrails/test_colang_e2e.py` tests the full pipeline with legitimate queries, blocked queries, and disabled-NeMo regression.

> **COLANG-907** | Priority: MUST
>
> **Description:** The Colang subsystem MUST degrade gracefully across all failure modes:
>
> | Failure Mode | Expected Behavior |
> |-------------|-------------------|
> | LLM provider unavailable | LLM-based actions return stub/default results via fail-open; deterministic actions continue normally |
> | Colang parse error at startup | `initialize()` raises `SyntaxError`; worker startup fails with clear error message |
> | Action raises exception at runtime | `_fail_open` decorator catches and returns default passing result; pipeline continues |
> | NeMo runtime crashes during `generate_async()` | Auto-disable sets `_auto_disabled = True`; subsequent requests bypass guardrails |
> | `nemoguardrails` not installed | `actions.py` uses no-op decorator; deterministic actions work in isolation |
> | Optional dependency unavailable (langdetect, spaCy) | Affected action fails open with default result |
>
> **Rationale:** The guardrails subsystem must never become a single point of failure for the RAG pipeline. Every failure mode must have a defined, tested degradation path. Traces to parent REQ-902 (graceful degradation).
>
> **Acceptance Criteria:** Each failure mode in the table is tested. In all cases, the pipeline returns results (not unhandled exceptions). Warning-level log entries are emitted for each degradation event.

> **COLANG-909** | Priority: SHOULD
>
> **Description:** Deterministic input rail actions (query length, language, clarity, abuse, exfiltration, role boundary) SHOULD complete within 10ms per action. The total Colang input rail overhead (excluding the Python executor action) SHOULD be less than 100ms.
>
> **Rationale:** Deterministic checks are simple regex/string operations. They must not add perceptible latency to the pipeline. The 100ms budget ensures that the 10 Colang input rails before the Python executor do not measurably impact the user experience.
>
> **Acceptance Criteria:** Benchmarking each deterministic action with a typical query produces execution times under 10ms. The aggregate wall-clock time for all 10 Colang input rails (excluding `run python executor`) is under 100ms at P95.

> **COLANG-911** | Priority: SHOULD
>
> **Description:** The system SHOULD log action failures at WARNING level with the action name, exception type, and exception message. The system SHOULD NOT log the raw user query or raw answer text in action failure logs.
>
> **Rationale:** Action failure logs are essential for diagnosing degradation events. However, logging raw queries or answers in failure logs creates a secondary data exposure risk, especially for queries that triggered PII or injection detection.
>
> **Acceptance Criteria:** When an action fails, the log entry contains the action function name and the exception message. The log entry does not contain `$user_message` or `$bot_message` content. Log level is WARNING.

---

## 12. Error Taxonomy

| Category | Examples | Severity | Expected Behavior |
|----------|----------|----------|-------------------|
| Syntax | Invalid Colang 2.0 syntax in `.co` file | Fatal | `SyntaxError` raised at startup; worker does not start |
| Import | `nemoguardrails` not installed | Non-blocking | No-op decorator fallback; actions work standalone |
| Dependency | `langdetect` unavailable, spaCy model missing | Recoverable | Affected action fails open with default result |
| Runtime | NeMo `generate_async()` exception | Recoverable (once) | Auto-disable guardrails; subsequent requests bypass |
| Action | Any action raises exception | Recoverable | `_fail_open` returns default; pipeline continues |
| Session State | Worker restart clears in-memory state | Acceptable | Escalation counters reset; documented limitation |

---

## 13. External Dependencies

### Required Services

| Service | Purpose |
|---------|---------|
| NeMo Guardrails Runtime (`nemoguardrails>=0.21.0`) | Colang flow compilation, rail execution, `generate_async()` pipeline |
| Ollama LLM Endpoint | LLM calls for NeMo intent matching, LLM-based actions (`check_query_ambiguity`, `check_source_scope`) |

### Optional Services

| Service | Purpose |
|---------|---------|
| `langdetect` library | Language detection in `detect_language` action |
| spaCy models | Entity recognition in `PIIDetector` (via `run_input_rails`) |
| Transformer model classifiers | Injection model classification (via `InjectionDetector` in `run_input_rails`) |

### Downstream Dependencies

| Consumer | Interface | Contract |
|----------|-----------|----------|
| `rag_chain.py` | `GuardrailsRuntime.generate_async()` | Receives `{"role": "assistant", "content": "..."}` dict |
| NeMo runtime | `actions.py` auto-discovery | All `@action()` functions in config directory are registered |

---

## 14. System-Level Acceptance Criteria

| Criterion | Threshold | Related Requirements |
|-----------|-----------|---------------------|
| All 5 `.co` files parse without errors under Colang 2.0 | 0 parse errors | COLANG-101, COLANG-103 |
| All 26 actions return valid dicts on both happy and error paths | 100% dict return rate | COLANG-203, COLANG-205 |
| Input rail ordering matches spec (deterministic before expensive) | Exact order match | COLANG-311 |
| Output rail ordering matches spec (executor first, scope last) | Exact order match | COLANG-515 |
| Pipeline remains operational under all 6 failure modes | 0 unhandled exceptions | COLANG-907 |
| Master toggle (`RAG_NEMO_ENABLED=false`) fully deactivates subsystem | 0 NeMo imports/calls | COLANG-903 |
| Deterministic actions complete within latency budget | P95 < 10ms per action | COLANG-909 |

---

## 15. Requirements Traceability Matrix

| COLANG ID | Section | Priority | Component | Parent REQ (NeMo Spec) |
|-----------|---------|----------|-----------|----------------------|
| COLANG-101 | 3 | MUST | File Structure & Syntax | REQ-102, REQ-704 |
| COLANG-103 | 3 | MUST | File Structure & Syntax | REQ-704 |
| COLANG-105 | 3 | MUST | File Structure & Syntax | -- |
| COLANG-107 | 3 | MUST | File Structure & Syntax | -- |
| COLANG-109 | 3 | MUST | File Structure & Syntax | -- |
| COLANG-111 | 3 | SHOULD | File Structure & Syntax | -- |
| COLANG-201 | 4 | MUST | Python Actions | -- |
| COLANG-203 | 4 | MUST | Python Actions | -- |
| COLANG-205 | 4 | MUST | Python Actions | REQ-902 |
| COLANG-207 | 4 | MUST | Python Actions | REQ-907 |
| COLANG-209 | 4 | MUST | Python Actions | -- |
| COLANG-211 | 4 | MUST | Python Actions | -- |
| COLANG-213 | 4 | MUST | Python Actions | REQ-707 |
| COLANG-215 | 4 | MUST | Python Actions | REQ-703 |
| COLANG-217 | 4 | MUST | Python Actions | -- |
| COLANG-219 | 4 | MUST | Python Actions | REQ-705 |
| COLANG-221 | 4 | SHOULD | Python Actions | -- |
| COLANG-301 | 5 | MUST | Input Rails | -- |
| COLANG-303 | 5 | MUST | Input Rails | -- |
| COLANG-305 | 5 | MUST | Input Rails | -- |
| COLANG-307 | 5 | MUST | Input Rails | -- |
| COLANG-309 | 5 | MUST | Input Rails | REQ-702 |
| COLANG-311 | 5 | MUST | Input Rails | -- |
| COLANG-401 | 6 | MUST | Conversation Management | REQ-101, REQ-102 |
| COLANG-403 | 6 | MUST | Conversation Management | REQ-103 |
| COLANG-405 | 6 | MUST | Conversation Management | REQ-101 |
| COLANG-407 | 6 | MUST | Conversation Management | -- |
| COLANG-409 | 6 | MUST | Conversation Management | REQ-103 |
| COLANG-411 | 6 | SHOULD | Conversation Management | -- |
| COLANG-501 | 7 | MUST | Output Rails | REQ-703 |
| COLANG-503 | 7 | MUST | Output Rails | -- |
| COLANG-505 | 7 | MUST | Output Rails | -- |
| COLANG-507 | 7 | MUST | Output Rails | -- |
| COLANG-509 | 7 | MUST | Output Rails | -- |
| COLANG-511 | 7 | MUST | Output Rails | -- |
| COLANG-513 | 7 | MUST | Output Rails | -- |
| COLANG-515 | 7 | MUST | Output Rails | -- |
| COLANG-517 | 7 | MUST | Output Rails | -- |
| COLANG-601 | 8 | MUST | Safety & Compliance | -- |
| COLANG-603 | 8 | MUST | Safety & Compliance | -- |
| COLANG-605 | 8 | MUST | Safety & Compliance | REQ-201 |
| COLANG-607 | 8 | MUST | Safety & Compliance | -- |
| COLANG-701 | 9 | MUST | RAG Dialog Patterns | -- |
| COLANG-703 | 9 | MUST | RAG Dialog Patterns | -- |
| COLANG-705 | 9 | MUST | RAG Dialog Patterns | -- |
| COLANG-707 | 9 | SHOULD | RAG Dialog Patterns | REQ-102 |
| COLANG-801 | 10 | MUST | Runtime Integration | REQ-701 |
| COLANG-803 | 10 | MUST | Runtime Integration | REQ-701 |
| COLANG-805 | 10 | MUST | Runtime Integration | REQ-902 |
| COLANG-807 | 10 | MUST | Runtime Integration | REQ-902 |
| COLANG-809 | 10 | MUST | Runtime Integration | REQ-706, REQ-907 |
| COLANG-811 | 10 | MUST | Runtime Integration | -- |
| COLANG-813 | 10 | MUST | Runtime Integration | REQ-903 |
| COLANG-815 | 10 | MUST | Runtime Integration | -- |
| COLANG-901 | 11 | MUST | Non-Functional | REQ-903 |
| COLANG-903 | 11 | MUST | Non-Functional | REQ-907 |
| COLANG-905 | 11 | MUST | Non-Functional | REQ-906 |
| COLANG-907 | 11 | MUST | Non-Functional | REQ-902 |
| COLANG-909 | 11 | SHOULD | Non-Functional | REQ-901 |
| COLANG-911 | 11 | SHOULD | Non-Functional | REQ-904 |

**Total Requirements: 60**
- MUST: 54
- SHOULD: 6
- MAY: 0

---

## Appendix A. Glossary

| Term | Definition |
|------|-----------|
| `$bot_message` | NeMo context variable holding the generated response; modifiable by output rail flows |
| `$user_message` | NeMo context variable holding the user query; modifiable by input rail flows |
| `$sensitive_disclaimer` | Custom context variable set by the sensitive topic input rail; consumed by the disclaimer output rail |
| `$low_confidence_noted` | Custom context variable set by the no-results output rail to prevent double-hedging |
| `$topic_drifted` | Custom context variable set by the topic drift dialog flow; consumed by the generation action |
| `abort` | Colang keyword that terminates the current rail pipeline and returns the most recent `bot say` message |
| `@action()` | NeMo decorator that registers a Python function as a callable action in Colang flows |
| `_fail_open` | Project-specific decorator that catches exceptions in actions and returns a default passing result |
| `InputRailExecutor` | Python class that orchestrates input rail checks (injection, PII, toxicity, topic safety) in parallel |
| `OutputRailExecutor` | Python class that orchestrates output rail checks (faithfulness, PII, toxicity) sequentially |
| `RailMergeGate` | Python class that combines query processing results with input rail verdicts into a routing decision |
| `LLMRails` | NeMo Guardrails class that executes the compiled rail pipeline |
| `RailsConfig` | NeMo Guardrails class that loads and compiles configuration from a directory |

---

## Appendix B. Document References

| Document | Purpose |
|----------|---------|
| `docs/retrieval/NEMO_GUARDRAILS_SPEC.md` | Parent specification defining the NeMo Guardrails integration requirements (REQ-1xx through REQ-9xx). This Colang spec is a child subsystem spec. |
| `docs/guardrails/COLANG_DESIGN_GUIDE.md` | Design guide covering Colang 2.0 syntax reference, naming conventions, project implementation patterns, and troubleshooting |
| `docs/superpowers/specs/2026-03-24-colang-guardrails-design.md` | Brainstorming design document that preceded this formal spec; contains flow pseudocode and architectural decisions |
| NVIDIA NeMo Guardrails Documentation | Official SDK documentation for Colang 2.0 syntax, `@action()` registration, and `generate_async()` pipeline |

---

## Appendix C. Open Questions

1. **Session state persistence:** The current in-memory session state for abuse detection and jailbreak escalation resets on worker restart. Should this be persisted to Redis or a database for production deployments with multiple workers? *(Relates to COLANG-211, COLANG-307, COLANG-607)*

2. **LLM-based action stubs:** Several actions (`check_query_ambiguity`, `check_source_scope`, `check_topic_drift`, `handle_follow_up`, `check_response_confidence`, `check_retrieval_results`) are currently implemented as stubs returning default values. Should these be prioritized for full implementation, and what LLM prompt patterns should they use? *(Relates to COLANG-701, COLANG-513, COLANG-411)*

3. **Configurable thresholds:** The current implementation hardcodes several thresholds (query length 3/2000, abuse rate 20/60s, jailbreak escalation 1-2/3+, answer length 20/5000, confidence 0.3). Should these be moved to environment variables or `config.yml` entries? *(Relates to COLANG-901)*
