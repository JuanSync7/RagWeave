> **Document type:** Technical design document (Layer 4)
> **Companion spec:** `COLANG_GUARDRAILS_SPEC.md`
> **Upstream:** COLANG_GUARDRAILS_SPEC.md
> **Downstream:** COLANG_GUARDRAILS_IMPLEMENTATION.md
> **Last updated:** 2026-03-25

# Colang 2.0 Guardrails Subsystem -- Design Document

| Field | Value |
|-------|-------|
| **Document** | Colang 2.0 Guardrails Subsystem Design Document |
| **Version** | 1.0.0 |
| **Status** | Active |
| **Spec Reference** | `COLANG_GUARDRAILS_SPEC.md` v1.0.0 (COLANG-101--COLANG-911) |
| **Companion Documents** | `COLANG_GUARDRAILS_SPEC.md`, `COLANG_DESIGN_GUIDE.md`, `COLANG_GUARDRAILS_IMPLEMENTATION.md` |
| **Created** | 2026-03-25 |
| **Last Updated** | 2026-03-25 |

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2026-03-25 | Initial design document -- 7 phases, 19 tasks, 60 requirements traced |

> **Document Intent.** This document translates the requirements defined in
> `COLANG_GUARDRAILS_SPEC.md` (COLANG-101--COLANG-911) into a phased, task-oriented
> implementation plan. Each task maps to one or more specification requirements and includes
> subtasks, complexity estimates, dependencies, and testing strategies.
>
> The Colang 2.0 Guardrails Subsystem implements a dual-layer architecture: a **Colang layer**
> of 33 declarative policy flows across 5 `.co` files, and a **Python layer** of 26
> `@action()`-decorated wrappers in `actions.py` that bridge Colang policy decisions to
> existing Python rail executors. The single `generate_async()` pipeline runs input rails,
> generation, and output rails in one NeMo call.
>
> See `COLANG_GUARDRAILS_SPEC.md` for the authoritative requirements. See
> `COLANG_GUARDRAILS_IMPLEMENTATION.md` for the operational build plan.

---

# Part A: Task-Oriented Overview

## Phase 1 -- Foundation (File Structure, Syntax, Config)

Phase 1 establishes the directory layout, validates Colang 2.0 syntax compatibility, and
creates the NeMo runtime configuration file. All subsequent phases depend on this foundation.

---

### Task 1.1 -- Config Directory & File Scaffold

**Description:** Create the `config/guardrails/` directory structure with all seven required
files: five `.co` flow files, one `actions.py`, and one `config.yml`. Each `.co` file is
initially empty except for a comment header stating its purpose and flow type (rail vs. dialog).
The `actions.py` starts with the conditional NeMo import and fail-open decorator. The
`config.yml` declares `colang_version: "2.x"` and the LLM provider configuration.

**Spec requirements:** COLANG-101, COLANG-103, COLANG-111, COLANG-813, COLANG-815

**Dependencies:** None

**Complexity:** Low

**Subtasks:**
1. Create the seven files in `config/guardrails/`: `input_rails.co`, `conversation.co`,
   `output_rails.co`, `safety.co`, `dialog_patterns.co`, `actions.py`, `config.yml`.
2. Add comment headers to each `.co` file describing its purpose, flow category, and whether
   flows are rails or standalone dialog flows (COLANG-111).
3. Write the `config.yml` skeleton with `colang_version: "2.x"`, the Ollama model provider
   block using `${RAG_OLLAMA_MODEL:-qwen2.5:3b}` and `${RAG_OLLAMA_URL:-http://localhost:11434}`
   (COLANG-813), and empty `rails.input.flows` / `rails.output.flows` lists.
4. Verify that NeMo built-in flows (`check jailbreak`, `jailbreak detection heuristics`,
   `check faithfulness`, `self check facts`, `self check output`) are NOT registered in
   `config.yml` (COLANG-815).
5. Validate that `RailsConfig.from_path("config/guardrails/")` succeeds without syntax errors
   on the empty scaffold (COLANG-101).

**Phase 0 contracts:** `config/guardrails/config.yml`
**Phase A test file:** `tests/guardrails/test_colang_flows.py`
**Phase B source file:** `config/guardrails/config.yml`, `config/guardrails/actions.py`

---

### Task 1.2 -- Colang 2.0 Syntax Validation

**Description:** Verify that all `.co` files use valid Colang 2.0 syntax. Confirm that the
`await` keyword is used for all action calls, that action results are assigned to `$variables`,
and that the `abort` keyword functions correctly to terminate rail pipelines. Verify that no
Colang 1.0 `define` keywords appear in any flow file.

**Spec requirements:** COLANG-101, COLANG-105, COLANG-109

**Dependencies:** Task 1.1

**Complexity:** Low

**Subtasks:**
1. Validate that all flow definitions use `flow` keyword (not `define`) per Colang 2.0
   syntax (COLANG-101).
2. Verify that rail flows follow the `input rails <name>` / `output rails <name>` naming
   convention, and standalone dialog flows do not use these prefixes (COLANG-105).
3. Confirm that every action call uses `await` and assigns results to `$variables` for
   conditional branching (COLANG-109).
4. Run `RailsConfig.from_path()` against each `.co` file to confirm zero parse errors.

**Phase 0 contracts:** N/A (validation only)
**Phase A test file:** `tests/guardrails/test_colang_flows.py`
**Phase B source file:** All `.co` files

---

### Task 1.3 -- Config.yml Rail Registration

**Description:** Populate the `config.yml` rail registration with the full input and output
rail flow lists in the specified order. Input rails are ordered deterministic-before-expensive:
Colang policy checks first, Python executor last. Output rails run the Python executor first,
then Colang policy flows.

**Spec requirements:** COLANG-311, COLANG-515

**Dependencies:** Task 1.1

**Complexity:** Low

**Subtasks:**
1. Register all 11 input rail flows in `rails.input.flows` in exact order: (1) check query
   length, (2) check language, (3) check query clarity, (4) check abuse, (5) check
   exfiltration, (6) check role boundary, (7) check jailbreak escalation, (8) check sensitive
   topic, (9) check off topic, (10) check ambiguity, (11) run python executor (COLANG-311).
2. Register all 7 output rail flows in `rails.output.flows` in exact order: (1) run python
   executor, (2) prepend disclaimer, (3) check no results, (4) check confidence, (5) check
   citations, (6) check length, (7) check scope (COLANG-515).
3. Add inline comments documenting ordering rationale (deterministic before expensive for
   input, critical safety first for output).
4. Add the `rails.config` section for jailbreak detection thresholds and sensitive data
   detection entity configuration.

**Phase 0 contracts:** `config/guardrails/config.yml`
**Phase A test file:** `tests/guardrails/test_colang_flows.py`
**Phase B source file:** `config/guardrails/config.yml`

---

## Phase 2 -- Python Action Layer

Phase 2 implements all 26 `@action()`-decorated Python wrappers in `actions.py`. This is the
bridge between Colang policy flows (which decide) and Python computation (which computes).

---

### Task 2.1 -- Action Module Infrastructure

**Description:** Implement the `actions.py` module infrastructure: conditional NeMo import
with no-op decorator fallback, the `_fail_open` decorator, session state dictionaries, and
the lazy initialization helpers for executor singletons. This infrastructure supports all 26
actions.

**Spec requirements:** COLANG-205, COLANG-207, COLANG-209, COLANG-211

**Dependencies:** Task 1.1

**Complexity:** Medium

**Subtasks:**
1. Implement conditional `nemoguardrails` import: try `from nemoguardrails.actions import
   action`, fall back to a no-op decorator that passes through the function unchanged
   (COLANG-207).
2. Implement the `_fail_open(default)` decorator that catches any exception, logs a warning
   with the action name and error message (not the raw query/answer), and returns the default
   dict (COLANG-205).
3. Initialize in-memory session state dicts: `_jailbreak_session_state` (int counts) and
   `_abuse_session_state` (timestamp lists), both keyed by session ID from NeMo context
   (COLANG-211).
4. Initialize the `_rail_instances` dict for lazy executor singletons (COLANG-209).
5. Implement `_get_input_executor()` lazy initialization helper that constructs
   `InputRailExecutor` with all rail class instances on first call, respecting env var toggles
   (COLANG-209).
6. Implement `_get_output_executor()` lazy initialization helper that constructs
   `OutputRailExecutor` on first call, sharing PII/toxicity instances with the input executor
   (COLANG-209).

**Phase 0 contracts:** `config/guardrails/actions.py`
**Phase A test file:** `tests/guardrails/test_colang_actions.py`
**Phase B source file:** `config/guardrails/actions.py`

---

### Task 2.2 -- Lightweight Deterministic Actions (18 actions)

**Description:** Implement the 18 lightweight deterministic or rule-based actions that do not
delegate to existing rail classes. These actions are self-contained: they perform string
operations, regex matching, rate counting, or return static values. All actions return dicts
and are decorated with both `@action()` and `@_fail_open(default)`.

**Spec requirements:** COLANG-201, COLANG-203, COLANG-221

**Dependencies:** Task 2.1

**Complexity:** Medium

**Subtasks:**
1. Implement query validation actions: `check_query_length` (min 3, max 2000), `detect_language`
   (via `langdetect`), `check_query_clarity` (word count + stopword heuristic).
2. Implement session-stateful actions: `check_abuse_pattern` (20 queries/60s per session),
   `check_jailbreak_escalation` (violation count escalation: 0=none, 1-2=warn, 3+=block).
3. Implement safety actions: `check_sensitive_topic` (keyword matching for medical/legal/
   financial), `check_exfiltration` (regex for bulk extraction patterns), `check_role_boundary`
   (regex for role-play/instruction-override patterns).
4. Implement output quality actions: `check_citations` (regex for citation patterns),
   `add_citation_reminder`, `check_response_confidence`, `prepend_hedge`,
   `check_answer_length` (min 20, max 5000), `adjust_answer_length`, `prepend_text`,
   `prepend_low_confidence_note`.
5. Implement dialog/stub actions: `handle_follow_up`, `check_topic_drift`,
   `check_retrieval_results`, `check_source_scope`, `check_query_ambiguity`,
   `get_knowledge_base_summary`.
6. Verify boundary value handling: empty strings and whitespace-only input for
   `check_query_length`, `check_answer_length`, and `check_citations` (COLANG-221).
7. Confirm every action returns a `dict` and every returned key matches the Colang flow's
   `$result.key` references (COLANG-203).

**Phase 0 contracts:** `config/guardrails/actions.py`
**Phase A test file:** `tests/guardrails/test_colang_actions.py`
**Phase B source file:** `config/guardrails/actions.py`

---

### Task 2.3 -- Executor Bridge Actions (8 actions)

**Description:** Implement the 8 actions that wrap existing Python rail classes: the 5
individual rail wrappers (`check_injection`, `detect_pii`, `check_toxicity`,
`check_topic_safety`, `check_faithfulness`) and the 3 executor-level wrappers
(`run_input_rails`, `run_output_rails`, `rag_retrieve_and_generate`). These delegate to
singleton executor instances via lazy initialization and respect env var toggles.

**Spec requirements:** COLANG-201, COLANG-213, COLANG-215, COLANG-217, COLANG-219

**Dependencies:** Task 2.1

**Complexity:** High

**Subtasks:**
1. Implement `check_injection`, `detect_pii`, `check_toxicity`, `check_topic_safety`, and
   `check_faithfulness` as thin wrappers calling their respective rail class instances.
2. Implement `run_input_rails` action: call `_get_input_executor()` and `RailMergeGate`,
   execute in a thread executor (since `InputRailExecutor.execute()` is synchronous), return
   dict with `action`/`intent`/`redacted_query`/`reject_message`/`metadata` (COLANG-213).
3. Implement `run_output_rails` action: call `_get_output_executor()`, execute in thread,
   return dict with `action`/`redacted_answer`/`reject_message`/`metadata`. Distinguish
   faithfulness rejection from PII/toxicity modification (COLANG-215).
4. Implement `rag_retrieve_and_generate` action: call the RAG chain reference (set via
   `set_rag_chain()`), execute in thread, return dict with `answer`/`sources`/`confidence`
   (COLANG-217).
5. Verify that env var toggles cause disabled rails to be skipped (e.g.,
   `RAG_NEMO_INJECTION_ENABLED=false` produces `None` injection detector) (COLANG-219).
6. Implement `set_rag_chain()` module-level function for programmatic chain injection.

**Phase 0 contracts:** `config/guardrails/actions.py`
**Phase A test file:** `tests/guardrails/test_colang_actions.py`
**Phase B source file:** `config/guardrails/actions.py`

---

## Phase 3 -- Input Rails

Phase 3 implements the 5 input rail flows in `input_rails.co` and the 4 safety input rails
in `safety.co`. Together these form the 11-flow input rail pipeline that validates and gates
user queries before generation.

---

### Task 3.1 -- Query Validation Input Rails (input_rails.co)

**Description:** Implement the 5 input rail flows in `input_rails.co`: query length
enforcement, language detection, query clarity, abuse detection, and the Python executor
bridge. Each flow calls its corresponding action, branches on the result, and uses `abort`
to block rejected queries.

**Spec requirements:** COLANG-107, COLANG-301, COLANG-303, COLANG-305, COLANG-307, COLANG-309

**Dependencies:** Task 2.2, Task 2.3, Task 1.3

**Complexity:** Medium

**Subtasks:**
1. Implement `input rails check query length`: call `check_query_length`, abort with
   `$result.reason` if `valid == False` (COLANG-301).
2. Implement `input rails check language`: call `detect_language`, abort with English-only
   message if `supported == False` (COLANG-303).
3. Implement `input rails check query clarity`: call `check_query_clarity`, abort with
   `$result.suggestion` if `clear == False` (COLANG-305).
4. Implement `input rails check abuse`: call `check_abuse_pattern`, abort with flagging
   message if `abusive == True` (COLANG-307).
5. Implement `input rails run python executor`: call `run_input_rails`, abort with
   `reject_message` if `action == "reject"`, update `$user_message` with `redacted_query` if
   `action == "modify"`. This flow MUST be the last input rail (COLANG-309).
6. Verify file contains exactly 5 flow definitions (COLANG-107).

**Phase 0 contracts:** N/A (Colang flow file)
**Phase A test file:** `tests/guardrails/test_colang_flows.py`
**Phase B source file:** `config/guardrails/input_rails.co`

---

### Task 3.2 -- Safety Input Rails (safety.co)

**Description:** Implement the 4 safety input rail flows in `safety.co`: sensitive topic
detection (sets context variable, does NOT abort), data exfiltration prevention, role boundary
enforcement, and jailbreak escalation. These complement the Python `InjectionDetector` by
handling policy-level responses.

**Spec requirements:** COLANG-107, COLANG-601, COLANG-603, COLANG-605, COLANG-607

**Dependencies:** Task 2.2, Task 1.3

**Complexity:** Medium

**Subtasks:**
1. Implement `input rails check sensitive topic`: call `check_sensitive_topic`, set
   `$sensitive_disclaimer = $result.disclaimer` if `sensitive == True`. This flow MUST NOT
   call `abort` -- the query proceeds with the disclaimer flag (COLANG-601).
2. Implement `input rails check exfiltration`: call `check_exfiltration`, abort with bulk
   extraction refusal message if `attempt == True` (COLANG-603).
3. Implement `input rails check role boundary`: call `check_role_boundary`, abort with role
   affirmation message if `violation == True` (COLANG-605).
4. Implement `input rails check jailbreak escalation`: call `check_jailbreak_escalation`,
   abort with warning message if `escalation_level == "warn"`, abort with stronger message
   mentioning session restrictions if `escalation_level == "block"` (COLANG-607).
5. Verify file contains exactly 4 flow definitions (COLANG-107).

**Phase 0 contracts:** N/A (Colang flow file)
**Phase A test file:** `tests/guardrails/test_colang_flows.py`
**Phase B source file:** `config/guardrails/safety.co`

---

## Phase 4 -- Conversation & Dialog Patterns

Phase 4 implements the standalone dialog flows for conversational UX (greetings, farewells,
follow-ups, topic drift) and RAG-specific dialog patterns (disambiguation, scope explanation,
feedback). It also includes the off-topic input rail that lives in `conversation.co`.

---

### Task 4.1 -- Conversation Management Flows (conversation.co)

**Description:** Implement the 10 flows in `conversation.co`: 2 intent-matching flows for
greetings/farewells, 3 handler flows (greeting, farewell, administrative), 2 follow-up flows
(intent matcher + handler), 1 off-topic intent matcher, 1 off-topic input rail, and 1 topic
drift flow. Only the off-topic flow is a registered input rail; all others are standalone
dialog flows.

**Spec requirements:** COLANG-107, COLANG-401, COLANG-403, COLANG-405, COLANG-407, COLANG-409, COLANG-411

**Dependencies:** Task 2.2, Task 1.3

**Complexity:** Medium

**Subtasks:**
1. Implement `user said greeting` intent flow with at least 5 utterance examples: "hello",
   "hi there", "hey", "good morning", "greetings" (COLANG-401).
2. Implement `user said farewell` intent flow with at least 5 utterance examples: "goodbye",
   "bye", "see you later", "thanks, bye", "that's all" (COLANG-401).
3. Implement `handle greeting` and `handle farewell` standalone dialog handlers with canned
   responses (COLANG-403).
4. Implement `user said administrative` intent flow and `handle administrative` handler
   describing system capabilities (COLANG-405).
5. Implement `user said follow up` intent flow and `handle follow up` handler that calls
   `handle_follow_up` action. When `has_context == False`, handler asks for clarification and
   calls `abort` (COLANG-407).
6. Implement `user said off topic` intent flow and `input rails check off topic` rail that
   blocks off-topic queries via `abort` (COLANG-409).
7. Implement `check topic drift` standalone dialog flow that calls `check_topic_drift` action
   and sets `$topic_drifted = True` when drift is detected. This flow MUST NOT call `abort`
   (COLANG-411).
8. Verify file contains exactly 10 flow definitions (COLANG-107).

**Phase 0 contracts:** N/A (Colang flow file)
**Phase A test file:** `tests/guardrails/test_colang_flows.py`
**Phase B source file:** `config/guardrails/conversation.co`

---

### Task 4.2 -- RAG Dialog Pattern Flows (dialog_patterns.co)

**Description:** Implement the 7 flows in `dialog_patterns.co`: 1 ambiguity input rail, 2
scope explanation flows (intent matcher + handler), and 4 feedback flows (2 intent matchers +
2 handlers). The ambiguity flow is a registered input rail; scope and feedback flows are
standalone dialog flows.

**Spec requirements:** COLANG-107, COLANG-701, COLANG-703, COLANG-705, COLANG-707

**Dependencies:** Task 2.2, Task 1.3

**Complexity:** Medium

**Subtasks:**
1. Implement `input rails check ambiguity`: call `check_query_ambiguity`, abort with
   `$result.disambiguation_prompt` if `ambiguous == True` (COLANG-701).
2. Implement `user asked about scope` intent flow with at least 4 utterance examples: "what
   documents do you have", "what can I ask about", "what topics do you cover", "what's in the
   knowledge base" (COLANG-703, COLANG-707).
3. Implement `handle scope question` handler that calls `get_knowledge_base_summary` and
   responds with the summary (COLANG-703).
4. Implement `user gave positive feedback` intent flow with at least 4 utterance examples:
   "thanks", "that's helpful", "great answer", "perfect", "exactly what I needed"
   (COLANG-705, COLANG-707).
5. Implement `user gave negative feedback` intent flow with at least 4 utterance examples:
   "that's wrong", "not what I asked", "that doesn't help", "incorrect" (COLANG-705,
   COLANG-707).
6. Implement `handle positive feedback` and `handle negative feedback` standalone dialog
   handlers (COLANG-705).
7. Verify file contains exactly 7 flow definitions (COLANG-107).

**Phase 0 contracts:** N/A (Colang flow file)
**Phase A test file:** `tests/guardrails/test_colang_flows.py`
**Phase B source file:** `config/guardrails/dialog_patterns.co`

---

## Phase 5 -- Output Rails

Phase 5 implements the 7 output rail flows in `output_rails.co` that enforce response quality
after generation.

---

### Task 5.1 -- Output Rail Flows (output_rails.co)

**Description:** Implement the 7 output rail flows in `output_rails.co`: Python executor
bridge (first), disclaimer prepending, no-results handling, confidence-based routing, citation
enforcement, length governance, and scope enforcement. All flows use the two-step
action-result pattern for `$bot_message` modification.

**Spec requirements:** COLANG-107, COLANG-501, COLANG-503, COLANG-505, COLANG-507, COLANG-509, COLANG-511, COLANG-513, COLANG-517

**Dependencies:** Task 2.2, Task 2.3, Task 1.3

**Complexity:** High

**Subtasks:**
1. Implement `output rails run python executor`: call `run_output_rails`, abort with
   `reject_message` if `action == "reject"`, update `$bot_message` with `redacted_answer`
   if `action == "modify"`. This MUST be the first output rail (COLANG-501).
2. Implement `output rails prepend disclaimer`: check `$sensitive_disclaimer` context variable,
   call `prepend_text` to prepend disclaimer to `$bot_message` if set. No-op when unset
   (COLANG-503).
3. Implement `output rails check no results`: call `check_retrieval_results`. If
   `has_results == False`, abort with no-results guidance message. If `avg_confidence < 0.3`,
   prepend low-confidence note and set `$low_confidence_noted = True` (COLANG-505).
4. Implement `output rails check citations`: call `check_citations`. If
   `has_citations == False`, append citation reminder via `add_citation_reminder` (COLANG-507).
5. Implement `output rails check confidence`: call `check_response_confidence`. If
   `confidence == "none"`, abort with no-information message. If `confidence == "low"` and
   `$low_confidence_noted` is not set, prepend hedge language (COLANG-509).
6. Implement `output rails check length`: call `check_answer_length`. If `valid == False`,
   adjust via `adjust_answer_length` (COLANG-511).
7. Implement `output rails check scope`: call `check_source_scope`. If `in_scope == False`,
   abort with scope-boundary message (COLANG-513).
8. Verify all `$bot_message` modifications use the two-step `$mod = await ...; $bot_message =
   $mod.answer` pattern (COLANG-517).
9. Verify file contains exactly 7 flow definitions (COLANG-107).

**Phase 0 contracts:** N/A (Colang flow file)
**Phase A test file:** `tests/guardrails/test_colang_flows.py`
**Phase B source file:** `config/guardrails/output_rails.co`

---

## Phase 6 -- Runtime Integration

Phase 6 implements the `GuardrailsRuntime` singleton and integrates it with the RAG chain
as the single entry point for the Colang pipeline.

---

### Task 6.1 -- GuardrailsRuntime Singleton

**Description:** Implement the `GuardrailsRuntime` class in `src/guardrails/runtime.py` as a
thread-safe singleton with lazy NeMo imports. The class provides `initialize()`,
`generate_async()`, `is_enabled()`, `register_actions()`, and lifecycle management methods.

**Spec requirements:** COLANG-801, COLANG-803, COLANG-805, COLANG-807, COLANG-809, COLANG-811

**Dependencies:** Task 1.1

**Complexity:** Medium

**Subtasks:**
1. Implement the singleton pattern with `_instance`, `_lock`, and double-checked locking in
   `get()` class method (COLANG-801).
2. Implement `initialize(config_dir)`: load `RailsConfig.from_path()`, create `LLMRails`.
   Make idempotent -- subsequent calls are no-ops after success (COLANG-803).
3. Implement fail-fast for Colang syntax errors: catch `SyntaxError` and re-raise. For other
   exceptions, log error and set `_auto_disabled = True` (COLANG-805).
4. Implement `generate_async(messages)`: delegate to `self._rails.generate_async()`. On
   exception, log warning, set `_auto_disabled = True`, return empty assistant message
   `{"role": "assistant", "content": ""}` (COLANG-807).
5. Implement `is_enabled()` class method: return `True` only when `RAG_NEMO_ENABLED=true` and
   `_auto_disabled` is `False` (COLANG-809).
6. Implement `register_actions(actions)`: register Python action functions by name with the
   NeMo runtime. Log warning if runtime not initialized (COLANG-811).
7. Implement `shutdown()` and `reset()` methods for lifecycle management and testing.

**Phase 0 contracts:** `src/guardrails/runtime.py`
**Phase A test file:** `tests/guardrails/test_colang_e2e.py`
**Phase B source file:** `src/guardrails/runtime.py`

---

### Task 6.2 -- RAG Chain Bridge

**Description:** Integrate the `GuardrailsRuntime` with `rag_chain.py` so that the RAG chain
calls `generate_async()` as the single entry point. The `rag_retrieve_and_generate` action
calls back into the RAG chain for retrieval+generation, replacing NeMo's default LLM call.
The previous `_run_guardrails_input()` and `_run_guardrails_output()` methods in
`rag_chain.py` are replaced by the single `generate_async()` call.

**Spec requirements:** COLANG-807, COLANG-217

**Dependencies:** Task 6.1, Task 2.3

**Complexity:** Medium

**Subtasks:**
1. Call `set_rag_chain(self)` during RAG chain initialization to provide the chain reference
   to the `rag_retrieve_and_generate` action.
2. Replace separate `_run_guardrails_input()` / `_run_guardrails_output()` calls with a single
   `GuardrailsRuntime.get().generate_async(messages)` call.
3. Handle the empty-response case (when guardrails are disabled or auto-disabled) by falling
   back to the existing non-guardrailed pipeline path.
4. Register the `rag_retrieve_and_generate` action with the NeMo runtime via
   `register_actions()`.

**Phase 0 contracts:** N/A (integration task)
**Phase A test file:** `tests/guardrails/test_colang_e2e.py`
**Phase B source file:** `src/retrieval/rag_chain.py`

---

## Phase 7 -- Testing & Documentation

Phase 7 provides comprehensive test coverage across three tiers and creates supporting
documentation.

---

### Task 7.1 -- Unit Tests: Deterministic Actions

**Description:** Test each deterministic action in isolation without the NeMo runtime. Cover
positive cases, negative cases, boundary values, env var toggle behavior, fail-open behavior,
and session state escalation.

**Spec requirements:** COLANG-905, COLANG-221

**Dependencies:** Task 2.2

**Complexity:** Medium

**Subtasks:**
1. Test `check_query_length`: valid query, too short (2 chars), too long (2001 chars), empty
   string, whitespace-only (COLANG-221).
2. Test `detect_language`: English query passes, non-English triggers rejection.
3. Test `check_query_clarity`: vague single-word queries, all-stopword queries, clear queries.
4. Test `check_abuse_pattern`: normal rate passes, 21+ queries in 60s triggers flag. Verify
   timestamps older than 60s are excluded.
5. Test `check_exfiltration`: each extraction pattern triggers, legitimate queries pass.
6. Test `check_role_boundary`: each role-play pattern triggers, legitimate queries pass.
7. Test `check_jailbreak_escalation`: 0 violations = "none", 1-2 = "warn", 3+ = "block".
   Verify independent session state.
8. Test `check_sensitive_topic`: medical/legal/financial keywords trigger, non-sensitive pass.
9. Test `check_citations`, `check_answer_length`: boundary values including empty strings.
10. Test fail-open: mock an action to raise `RuntimeError`, verify default dict is returned.
11. Test env var toggles: verify disabled rails return pass/no-op results.

**Phase 0 contracts:** N/A
**Phase A test file:** `tests/guardrails/test_colang_actions.py`
**Phase B source file:** `tests/guardrails/test_colang_actions.py`

---

### Task 7.2 -- Integration Tests: Colang Flow Parsing

**Description:** Test that all 5 `.co` files parse correctly under Colang 2.0 and that the
flow count matches the spec. Verify input rail blocking, output rail modification, and
standalone dialog flow matching.

**Spec requirements:** COLANG-905, COLANG-107, COLANG-105

**Dependencies:** Task 3.1, Task 3.2, Task 4.1, Task 4.2, Task 5.1

**Complexity:** Medium

**Subtasks:**
1. Verify all 5 `.co` files parse without `SyntaxError` via `RailsConfig.from_path()`.
2. Verify flow counts per file: `input_rails.co` = 5, `conversation.co` = 10,
   `output_rails.co` = 7, `safety.co` = 4, `dialog_patterns.co` = 7, total = 33 (COLANG-107).
3. Test input rail blocking: verify queries that should be blocked (too short, non-English,
   abusive, exfiltration, role boundary, off-topic) return rejection messages and do not
   reach generation.
4. Test input rail pass-through: verify legitimate RAG queries pass all input rails.
5. Test output rail modification: verify `$bot_message` is modified by citation, hedge, length,
   and disclaimer flows.
6. Test output rail blocking: verify no-results and out-of-scope responses are caught.
7. Test standalone dialog flow matching: verify greeting, farewell, administrative, feedback,
   and scope queries match their respective intent flows.

**Phase 0 contracts:** N/A
**Phase A test file:** `tests/guardrails/test_colang_flows.py`
**Phase B source file:** `tests/guardrails/test_colang_flows.py`

---

### Task 7.3 -- End-to-End Tests: Full Pipeline

**Description:** Test the full `generate_async()` pipeline from user message to final
response, covering the happy path, rejection paths, modification paths, and degradation paths.

**Spec requirements:** COLANG-905, COLANG-907, COLANG-903

**Dependencies:** Task 6.1, Task 6.2

**Complexity:** High

**Subtasks:**
1. Test legitimate RAG query: passes all input rails, triggers `rag_retrieve_and_generate`,
   passes all output rails, returns response with metadata.
2. Test jailbreak attempt: caught by Python input executor via Colang action bridge, returns
   rejection.
3. Test sensitive topic query: returns answer with disclaimer prepended.
4. Test no-results query: returns no-results handling response.
5. Test each failure mode from COLANG-907: LLM unavailable, Colang parse error, action
   exception, NeMo runtime crash, NeMo not installed, optional dependency unavailable.
6. Test `RAG_NEMO_ENABLED=false`: verify no NeMo imports/calls execute, pipeline returns
   results (COLANG-903).
7. Test regression: verify existing Python rail behavior is unchanged when invoked through
   Colang action wrappers vs. direct calls.

**Phase 0 contracts:** N/A
**Phase A test file:** `tests/guardrails/test_colang_e2e.py`
**Phase B source file:** `tests/guardrails/test_colang_e2e.py`

---

### Task 7.4 -- Non-Functional Verification

**Description:** Verify non-functional requirements: configurability, performance, and logging
behavior.

**Spec requirements:** COLANG-901, COLANG-909, COLANG-911

**Dependencies:** Task 2.2, Task 7.1

**Complexity:** Low

**Subtasks:**
1. Verify all thresholds and parameters are configurable via env vars or documented as
   intentional defaults: query length bounds (3, 2000), abuse rate (20/60s), escalation
   thresholds (1-2 warn, 3+ block), answer length bounds (20, 5000), confidence threshold
   (0.3) (COLANG-901).
2. Benchmark deterministic actions: verify each completes under 10ms for typical queries.
   Verify aggregate Colang input rail overhead (excluding Python executor) is under 100ms at
   P95 (COLANG-909).
3. Verify logging behavior: action failures log at WARNING level with action name and error
   message, but NOT with raw query/answer content (COLANG-911).

**Phase 0 contracts:** N/A
**Phase A test file:** `tests/guardrails/test_colang_actions.py`
**Phase B source file:** N/A (verification task)

---

## Task Dependency Graph

```
Phase 1 (Foundation)
├── Task 1.1: Config Directory & File Scaffold ─────────────────────┐
├── Task 1.2: Colang 2.0 Syntax Validation ◄─── Task 1.1           │
└── Task 1.3: Config.yml Rail Registration ◄─── Task 1.1           │
                                                                     │
Phase 2 (Python Action Layer)                                        │
├── Task 2.1: Action Module Infrastructure ◄─── Task 1.1            │
├── Task 2.2: Lightweight Deterministic Actions ◄─── Task 2.1       │
└── Task 2.3: Executor Bridge Actions ◄─── Task 2.1                 │
                                                                     │
Phase 3 (Input Rails)                                                │
├── Task 3.1: Query Validation Input Rails ◄─── Task 2.2, 2.3, 1.3 │
└── Task 3.2: Safety Input Rails ◄─── Task 2.2, 1.3                │
                                                                     │
Phase 4 (Conversation & Dialog)                                      │
├── Task 4.1: Conversation Management ◄─── Task 2.2, 1.3           │
└── Task 4.2: RAG Dialog Patterns ◄─── Task 2.2, 1.3               │
                                                                     │
Phase 5 (Output Rails)                                               │
└── Task 5.1: Output Rail Flows ◄─── Task 2.2, 2.3, 1.3            │
                                                                     │
Phase 6 (Runtime Integration)                                        │
├── Task 6.1: GuardrailsRuntime Singleton ◄─── Task 1.1             │
└── Task 6.2: RAG Chain Bridge ◄─── Task 6.1, 2.3                   │
                                                                     │
Phase 7 (Testing & Documentation)                                    │
├── Task 7.1: Unit Tests ◄─── Task 2.2                              │
├── Task 7.2: Integration Tests ◄─── Task 3.1, 3.2, 4.1, 4.2, 5.1 │
├── Task 7.3: E2E Tests ◄─── Task 6.1, 6.2                         │
└── Task 7.4: Non-Functional Verification ◄─── Task 2.2, 7.1       │

Critical path: Task 1.1 → Task 2.1 → Task 2.2/2.3 → Task 3.1/3.2/4.1/4.2/5.1 → Task 7.2
```

---

## Task-to-Requirement Traceability

| Task | COLANG IDs | Phase 0 contracts | Phase A test | Phase B source |
|------|-----------|-------------------|--------------|----------------|
| 1.1 Config Directory & File Scaffold | COLANG-101, COLANG-103, COLANG-111, COLANG-813, COLANG-815 | `config/guardrails/config.yml` | `tests/guardrails/test_colang_flows.py` | `config/guardrails/config.yml`, `config/guardrails/actions.py` |
| 1.2 Colang 2.0 Syntax Validation | COLANG-101, COLANG-105, COLANG-109 | N/A | `tests/guardrails/test_colang_flows.py` | All `.co` files |
| 1.3 Config.yml Rail Registration | COLANG-311, COLANG-515 | `config/guardrails/config.yml` | `tests/guardrails/test_colang_flows.py` | `config/guardrails/config.yml` |
| 2.1 Action Module Infrastructure | COLANG-205, COLANG-207, COLANG-209, COLANG-211 | `config/guardrails/actions.py` | `tests/guardrails/test_colang_actions.py` | `config/guardrails/actions.py` |
| 2.2 Lightweight Deterministic Actions | COLANG-201, COLANG-203, COLANG-221 | `config/guardrails/actions.py` | `tests/guardrails/test_colang_actions.py` | `config/guardrails/actions.py` |
| 2.3 Executor Bridge Actions | COLANG-201, COLANG-213, COLANG-215, COLANG-217, COLANG-219 | `config/guardrails/actions.py` | `tests/guardrails/test_colang_actions.py` | `config/guardrails/actions.py` |
| 3.1 Query Validation Input Rails | COLANG-107, COLANG-301, COLANG-303, COLANG-305, COLANG-307, COLANG-309 | N/A | `tests/guardrails/test_colang_flows.py` | `config/guardrails/input_rails.co` |
| 3.2 Safety Input Rails | COLANG-107, COLANG-601, COLANG-603, COLANG-605, COLANG-607 | N/A | `tests/guardrails/test_colang_flows.py` | `config/guardrails/safety.co` |
| 4.1 Conversation Management Flows | COLANG-107, COLANG-401, COLANG-403, COLANG-405, COLANG-407, COLANG-409, COLANG-411 | N/A | `tests/guardrails/test_colang_flows.py` | `config/guardrails/conversation.co` |
| 4.2 RAG Dialog Pattern Flows | COLANG-107, COLANG-701, COLANG-703, COLANG-705, COLANG-707 | N/A | `tests/guardrails/test_colang_flows.py` | `config/guardrails/dialog_patterns.co` |
| 5.1 Output Rail Flows | COLANG-107, COLANG-501, COLANG-503, COLANG-505, COLANG-507, COLANG-509, COLANG-511, COLANG-513, COLANG-517 | N/A | `tests/guardrails/test_colang_flows.py` | `config/guardrails/output_rails.co` |
| 6.1 GuardrailsRuntime Singleton | COLANG-801, COLANG-803, COLANG-805, COLANG-807, COLANG-809, COLANG-811 | `src/guardrails/runtime.py` | `tests/guardrails/test_colang_e2e.py` | `src/guardrails/runtime.py` |
| 6.2 RAG Chain Bridge | COLANG-807, COLANG-217 | N/A | `tests/guardrails/test_colang_e2e.py` | `src/retrieval/rag_chain.py` |
| 7.1 Unit Tests: Deterministic Actions | COLANG-905, COLANG-221 | N/A | `tests/guardrails/test_colang_actions.py` | `tests/guardrails/test_colang_actions.py` |
| 7.2 Integration Tests: Colang Flows | COLANG-905, COLANG-107, COLANG-105 | N/A | `tests/guardrails/test_colang_flows.py` | `tests/guardrails/test_colang_flows.py` |
| 7.3 E2E Tests: Full Pipeline | COLANG-905, COLANG-907, COLANG-903 | N/A | `tests/guardrails/test_colang_e2e.py` | `tests/guardrails/test_colang_e2e.py` |
| 7.4 Non-Functional Verification | COLANG-901, COLANG-909, COLANG-911 | N/A | `tests/guardrails/test_colang_actions.py` | N/A |

<!-- VERIFY: All 60 requirements from COLANG_GUARDRAILS_SPEC.md COLANG-101--COLANG-911 appear above. -->

---

# Part B: Code Appendix

The following entries illustrate the key contracts and implementation patterns used in the
Colang 2.0 Guardrails Subsystem. Contract entries are copied verbatim into Phase 0. Pattern
entries are provided to Phase B implementation agents only.

---

## B.1 -- Action Module Infrastructure (Contracts)

#### Contract: `config/guardrails/actions.py` -- Conditional import and fail-open decorator

> **Type: CONTRACT** -- Copy verbatim into Phase 0. Both Phase A and Phase B agents receive this.

```python
# config/guardrails/actions.py (infrastructure excerpt)

from __future__ import annotations

import functools
import logging
import re
from typing import Any, Dict

# COLANG-207: Conditional import — NeMo may not be installed
try:
    from nemoguardrails.actions import action
except ImportError:
    def action():
        """No-op decorator when nemoguardrails is not installed."""
        def decorator(fn):
            return fn
        return decorator

logger = logging.getLogger("rag.guardrails.actions")

# COLANG-211: Session state (in-memory, keyed by session_id)
_jailbreak_session_state: Dict[str, int] = {}
_abuse_session_state: Dict[str, list] = {}

# COLANG-209: Lazy-initialized rail class singletons
_rail_instances: Dict[str, Any] = {}


def _fail_open(default: dict):
    """Decorator: catch exceptions and return default (fail-open).

    Every @action() function MUST also have this decorator. When the action
    raises any exception, the decorator catches it, logs a warning with the
    action name and error message (not the raw query/answer per COLANG-911),
    and returns the default dict.

    Args:
        default: Dict to return when the wrapped function raises an exception.
            Must be a valid passing/no-op result for the action's Colang flow.

    Returns:
        Decorator that wraps the async function with fail-open error handling.

    Raises:
        Never raises — that is the point of this decorator.
    """
    def decorator(fn):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            try:
                return await fn(*args, **kwargs)
            except Exception as e:
                logger.warning("Action %s failed: %s — returning default", fn.__name__, e)
                return default
        return wrapper
    return decorator
```

**Tasks:** Task 2.1
**Requirements:** COLANG-205, COLANG-207, COLANG-209, COLANG-211

---

## B.2 -- Deterministic Action Signatures (Contracts)

#### Contract: `config/guardrails/actions.py` -- Lightweight action signatures

> **Type: CONTRACT** -- Copy verbatim into Phase 0. Both Phase A and Phase B agents receive this.

```python
# config/guardrails/actions.py (deterministic action signatures)

@action()
@_fail_open({"valid": True, "length": 0, "reason": ""})
async def check_query_length(query: str) -> dict:
    """Validate query length: min 3 chars, max 2000 chars.

    Args:
        query: The user's query string.

    Returns:
        Dict with keys:
            valid (bool): True if length is within bounds.
            length (int): Character count of stripped query.
            reason (str): Human-readable rejection reason, or empty string.

    Raises:
        Never raises — fail-open returns {"valid": True, "length": 0, "reason": ""}.
    """
    raise NotImplementedError("Task 2.2.1")


@action()
@_fail_open({"language": "en", "supported": True})
async def detect_language(query: str) -> dict:
    """Detect query language using langdetect. Only English is supported.

    Args:
        query: The user's query string.

    Returns:
        Dict with keys:
            language (str): ISO 639-1 language code (e.g., "en", "es").
            supported (bool): True if language is English.

    Raises:
        Never raises — fail-open returns {"language": "en", "supported": True}.
    """
    raise NotImplementedError("Task 2.2.1")


@action()
@_fail_open({"clear": True, "suggestion": ""})
async def check_query_clarity(query: str) -> dict:
    """Heuristic clarity check: reject very short or all-stopword queries.

    Args:
        query: The user's query string.

    Returns:
        Dict with keys:
            clear (bool): True if query has enough content-bearing terms.
            suggestion (str): Improvement suggestion, or empty string.

    Raises:
        Never raises — fail-open returns {"clear": True, "suggestion": ""}.
    """
    raise NotImplementedError("Task 2.2.1")


@action()
@_fail_open({"abusive": False, "reason": ""})
async def check_abuse_pattern(query: str, context: dict = None) -> dict:
    """Track query rate per session. Flag if > 20 queries in 60-second window.

    Args:
        query: The user's query string.
        context: NeMo context dict containing session_id.

    Returns:
        Dict with keys:
            abusive (bool): True if session exceeds rate limit.
            reason (str): Description of the abuse pattern.

    Raises:
        Never raises — fail-open returns {"abusive": False, "reason": ""}.
    """
    raise NotImplementedError("Task 2.2.2")


@action()
@_fail_open({"sensitive": False, "disclaimer": "", "domain": ""})
async def check_sensitive_topic(query: str) -> dict:
    """Keyword + regex check for medical/legal/financial sensitive topics.

    Args:
        query: The user's query string.

    Returns:
        Dict with keys:
            sensitive (bool): True if sensitive domain detected.
            disclaimer (str): Domain-appropriate disclaimer text.
            domain (str): Detected domain ("medical", "legal", "financial", or "").

    Raises:
        Never raises — fail-open returns {"sensitive": False, "disclaimer": "", "domain": ""}.
    """
    raise NotImplementedError("Task 2.2.3")


@action()
@_fail_open({"attempt": False, "pattern": ""})
async def check_exfiltration(query: str) -> dict:
    """Detect bulk data extraction patterns via regex.

    Args:
        query: The user's query string.

    Returns:
        Dict with keys:
            attempt (bool): True if extraction pattern detected.
            pattern (str): The matched regex pattern, or empty string.

    Raises:
        Never raises — fail-open returns {"attempt": False, "pattern": ""}.
    """
    raise NotImplementedError("Task 2.2.3")


@action()
@_fail_open({"violation": False})
async def check_role_boundary(query: str) -> dict:
    """Detect role-play and instruction-override patterns via regex.

    Args:
        query: The user's query string.

    Returns:
        Dict with keys:
            violation (bool): True if role boundary violation detected.

    Raises:
        Never raises — fail-open returns {"violation": False}.
    """
    raise NotImplementedError("Task 2.2.3")


@action()
@_fail_open({"escalation_level": "none"})
async def check_jailbreak_escalation(query: str, context: dict = None) -> dict:
    """Track jailbreak attempt count per session with escalating responses.

    Thresholds: 0 violations = "none", 1-2 = "warn", 3+ = "block".

    Args:
        query: The user's query string.
        context: NeMo context dict containing session_id.

    Returns:
        Dict with keys:
            escalation_level (str): "none", "warn", or "block".

    Raises:
        Never raises — fail-open returns {"escalation_level": "none"}.
    """
    raise NotImplementedError("Task 2.2.2")


@action()
@_fail_open({"has_citations": True})
async def check_citations(answer: str) -> dict:
    """Check if answer contains citation patterns like [Source: ...] or [1].

    Args:
        answer: The generated answer text.

    Returns:
        Dict with keys:
            has_citations (bool): True if citation pattern found.

    Raises:
        Never raises — fail-open returns {"has_citations": True}.
    """
    raise NotImplementedError("Task 2.2.4")


@action()
@_fail_open({"answer": ""})
async def add_citation_reminder(answer: str) -> dict:
    """Append citation reminder to answer.

    Args:
        answer: The generated answer text.

    Returns:
        Dict with keys:
            answer (str): Answer with citation reminder appended.

    Raises:
        Never raises — fail-open returns {"answer": ""}.
    """
    raise NotImplementedError("Task 2.2.4")


@action()
@_fail_open({"confidence": "high"})
async def check_response_confidence(answer: str) -> dict:
    """Read retrieval confidence from NeMo context.

    Args:
        answer: The generated answer text.

    Returns:
        Dict with keys:
            confidence (str): "none", "low", or "high".

    Raises:
        Never raises — fail-open returns {"confidence": "high"}.
    """
    raise NotImplementedError("Task 2.2.4")


@action()
@_fail_open({"answer": ""})
async def prepend_hedge(answer: str) -> dict:
    """Prepend hedge language for low-confidence answers.

    Args:
        answer: The generated answer text.

    Returns:
        Dict with keys:
            answer (str): Answer with hedge language prepended.

    Raises:
        Never raises — fail-open returns {"answer": ""}.
    """
    raise NotImplementedError("Task 2.2.4")


@action()
@_fail_open({"answer": ""})
async def prepend_text(text: str, answer: str) -> dict:
    """Prepend arbitrary text (e.g., disclaimer) to answer.

    Args:
        text: Text to prepend (e.g., disclaimer).
        answer: The generated answer text.

    Returns:
        Dict with keys:
            answer (str): Answer with text prepended.

    Raises:
        Never raises — fail-open returns {"answer": ""}.
    """
    raise NotImplementedError("Task 2.2.4")


@action()
@_fail_open({"answer": ""})
async def prepend_low_confidence_note(answer: str) -> dict:
    """Prepend low-confidence note to answer.

    Args:
        answer: The generated answer text.

    Returns:
        Dict with keys:
            answer (str): Answer with low-confidence note prepended.

    Raises:
        Never raises — fail-open returns {"answer": ""}.
    """
    raise NotImplementedError("Task 2.2.4")


@action()
@_fail_open({"valid": True, "reason": ""})
async def check_answer_length(answer: str) -> dict:
    """Validate answer length: min 20 chars, max 5000 chars.

    Args:
        answer: The generated answer text.

    Returns:
        Dict with keys:
            valid (bool): True if length is within bounds.
            reason (str): "too short", "too long", or empty string.

    Raises:
        Never raises — fail-open returns {"valid": True, "reason": ""}.
    """
    raise NotImplementedError("Task 2.2.4")


@action()
@_fail_open({"answer": ""})
async def adjust_answer_length(answer: str, reason: str) -> dict:
    """Truncate overly long answers or flag terse ones.

    Args:
        answer: The generated answer text.
        reason: "too short" or "too long".

    Returns:
        Dict with keys:
            answer (str): Adjusted answer text.

    Raises:
        Never raises — fail-open returns {"answer": ""}.
    """
    raise NotImplementedError("Task 2.2.4")


@action()
@_fail_open({"has_context": False, "augmented_query": ""})
async def handle_follow_up(query: str) -> dict:
    """Check NeMo conversation context for prior Q&A pairs.

    Args:
        query: The user's follow-up query string.

    Returns:
        Dict with keys:
            has_context (bool): True if prior conversation context exists.
            augmented_query (str): Query augmented with context, or original query.

    Raises:
        Never raises — fail-open returns {"has_context": False, "augmented_query": ""}.
    """
    raise NotImplementedError("Task 2.2.5")


@action()
@_fail_open({"drifted": False})
async def check_topic_drift(query: str) -> dict:
    """Compare query embedding similarity to prior turn for topic drift detection.

    Args:
        query: The user's query string.

    Returns:
        Dict with keys:
            drifted (bool): True if topic drift detected.

    Raises:
        Never raises — fail-open returns {"drifted": False}.
    """
    raise NotImplementedError("Task 2.2.5")


@action()
@_fail_open({"has_results": True, "count": 1, "avg_confidence": 1.0})
async def check_retrieval_results(answer: str) -> dict:
    """Read retrieval metadata from NeMo context.

    Args:
        answer: The generated answer text.

    Returns:
        Dict with keys:
            has_results (bool): True if retrieval returned documents.
            count (int): Number of retrieved documents.
            avg_confidence (float): Average retrieval confidence score.

    Raises:
        Never raises — fail-open returns {"has_results": True, "count": 1, "avg_confidence": 1.0}.
    """
    raise NotImplementedError("Task 2.2.5")


@action()
@_fail_open({"in_scope": True})
async def check_source_scope(answer: str) -> dict:
    """LLM-based check: does answer stay within retrieved context?

    Args:
        answer: The generated answer text.

    Returns:
        Dict with keys:
            in_scope (bool): True if answer is within knowledge base scope.

    Raises:
        Never raises — fail-open returns {"in_scope": True}.
    """
    raise NotImplementedError("Task 2.2.5")


@action()
@_fail_open({"ambiguous": False, "disambiguation_prompt": ""})
async def check_query_ambiguity(query: str) -> dict:
    """LLM-based check: does query have multiple valid interpretations?

    Args:
        query: The user's query string.

    Returns:
        Dict with keys:
            ambiguous (bool): True if query is ambiguous.
            disambiguation_prompt (str): Prompt asking user to clarify.

    Raises:
        Never raises — fail-open returns {"ambiguous": False, "disambiguation_prompt": ""}.
    """
    raise NotImplementedError("Task 2.2.5")


@action()
@_fail_open({"summary": "This knowledge base contains documents about various topics."})
async def get_knowledge_base_summary() -> dict:
    """Return a static summary of the knowledge base contents.

    Returns:
        Dict with keys:
            summary (str): Human-readable summary of available topics.

    Raises:
        Never raises — fail-open returns a generic summary.
    """
    raise NotImplementedError("Task 2.2.5")
```

**Tasks:** Task 2.2
**Requirements:** COLANG-201, COLANG-203, COLANG-221

---

## B.3 -- Executor Bridge Action Signatures (Contracts)

#### Contract: `config/guardrails/actions.py` -- Executor bridge signatures

> **Type: CONTRACT** -- Copy verbatim into Phase 0. Both Phase A and Phase B agents receive this.

```python
# config/guardrails/actions.py (executor bridge action signatures)

@action()
@_fail_open({"action": "pass", "intent": "rag_search", "redacted_query": "", "reject_message": "", "metadata": {}})
async def run_input_rails(query: str) -> dict:
    """Run all Python input rails via InputRailExecutor + RailMergeGate.

    Delegates to the lazily-initialized InputRailExecutor singleton and RailMergeGate
    to execute injection detection, PII redaction, toxicity filtering, and topic safety
    checking. The executor runs in a thread since it is synchronous.

    Args:
        query: The user's query string (possibly modified by upstream Colang rails).

    Returns:
        Dict with keys:
            action (str): "pass", "reject", or "modify".
            intent (str): Classified intent (e.g., "rag_search").
            redacted_query (str): Query with PII redacted, or original query.
            reject_message (str): Rejection message if action is "reject".
            metadata (dict): Additional rail execution metadata.

    Raises:
        Never raises — fail-open returns passing result.
    """
    raise NotImplementedError("Task 2.3.2")


@action()
@_fail_open({"action": "pass", "redacted_answer": "", "reject_message": "", "metadata": {}})
async def run_output_rails(answer: str) -> dict:
    """Run all Python output rails via OutputRailExecutor.

    Delegates to the lazily-initialized OutputRailExecutor singleton to execute
    faithfulness checking, PII redaction, and toxicity filtering.

    Args:
        answer: The generated answer text.

    Returns:
        Dict with keys:
            action (str): "pass", "reject", or "modify".
            redacted_answer (str): Answer with PII redacted, or original answer.
            reject_message (str): Rejection/fallback message if action is "reject".
            metadata (dict): Additional rail execution metadata.

    Raises:
        Never raises — fail-open returns passing result.
    """
    raise NotImplementedError("Task 2.3.3")


@action()
@_fail_open({"answer": "", "sources": [], "confidence": 0.0})
async def rag_retrieve_and_generate(query: str) -> dict:
    """Execute the RAG retrieval+generation pipeline.

    Calls RAGChain.run() in a thread executor. The chain reference is set via
    set_rag_chain() during initialization. This action replaces NeMo's default
    LLM call as the generation step.

    Args:
        query: The validated user query (after input rails).

    Returns:
        Dict with keys:
            answer (str): Generated answer text.
            sources (list): List of source document identifiers.
            confidence (float): Retrieval confidence score (0.0-1.0).

    Raises:
        Never raises — fail-open returns empty defaults.
    """
    raise NotImplementedError("Task 2.3.4")


# Module-level function for chain injection (not an @action)
_rag_chain_ref = None

def set_rag_chain(chain) -> None:
    """Set the RAG chain reference for rag_retrieve_and_generate.

    Called by rag_chain.py during initialization to provide the chain reference
    that enables the generation action to call back into the RAG pipeline.

    Args:
        chain: The RAGChain instance.
    """
    raise NotImplementedError("Task 2.3.6")
```

**Tasks:** Task 2.3
**Requirements:** COLANG-213, COLANG-215, COLANG-217, COLANG-219

---

## B.4 -- GuardrailsRuntime Singleton (Contracts)

#### Contract: `src/guardrails/runtime.py` -- Runtime class signature

> **Type: CONTRACT** -- Copy verbatim into Phase 0. Both Phase A and Phase B agents receive this.

```python
# src/guardrails/runtime.py

from __future__ import annotations

import logging
import threading
from typing import Any, Optional

logger = logging.getLogger("rag.guardrails.runtime")


class GuardrailsRuntime:
    """Singleton manager for the NeMo Guardrails runtime.

    Lazy-imports nemoguardrails to avoid import errors when
    RAG_NEMO_ENABLED=false and the package is not installed.
    Thread-safe initialization via double-checked locking.
    """

    _instance: Optional[GuardrailsRuntime] = None
    _initialized: bool = False
    _rails = None  # LLMRails instance
    _auto_disabled: bool = False
    _lock: threading.Lock = threading.Lock()

    @classmethod
    def get(cls) -> GuardrailsRuntime:
        """Return the process-wide singleton runtime instance.

        Returns:
            The singleton GuardrailsRuntime instance.

        Raises:
            Never raises — creates instance on first call.
        """
        raise NotImplementedError("Task 6.1.1")

    @classmethod
    def is_enabled(cls) -> bool:
        """Return whether guardrails are enabled and not auto-disabled.

        Checks both RAG_NEMO_ENABLED config and the _auto_disabled flag.

        Returns:
            True if guardrails should be active for this process.

        Raises:
            Never raises.
        """
        raise NotImplementedError("Task 6.1.5")

    def initialize(self, config_dir: str) -> None:
        """Load NeMo config and compile Colang flows.

        Idempotent — subsequent calls after success are no-ops.
        Fails fast on Colang syntax errors (SyntaxError).
        Fails open on other errors by setting _auto_disabled.

        Args:
            config_dir: Directory containing NeMo Guardrails configuration.

        Raises:
            SyntaxError: If Colang parsing fails.
        """
        raise NotImplementedError("Task 6.1.2")

    async def generate_async(self, messages: list[dict]) -> dict:
        """Execute the full NeMo rail pipeline on a message sequence.

        Fail-open: returns empty assistant message if rails are unavailable.
        On runtime error, auto-disables guardrails for subsequent requests.

        Args:
            messages: Chat message list in OpenAI-compatible format.

        Returns:
            Assistant message dict with "role" and "content" keys.

        Raises:
            Never raises — fail-open returns empty assistant message.
        """
        raise NotImplementedError("Task 6.1.4")

    def register_actions(self, actions: dict[str, callable]) -> None:
        """Register Python action functions with the NeMo runtime.

        Args:
            actions: Dict mapping action names to async callables.

        Raises:
            Never raises — logs warning if runtime not initialized.
        """
        raise NotImplementedError("Task 6.1.6")

    def shutdown(self) -> None:
        """Release runtime resources and mark uninitialized.

        Raises:
            Never raises.
        """
        raise NotImplementedError("Task 6.1.7")

    @classmethod
    def reset(cls) -> None:
        """Reset singleton state (for testing).

        Raises:
            Never raises.
        """
        raise NotImplementedError("Task 6.1.7")
```

**Tasks:** Task 6.1
**Requirements:** COLANG-801, COLANG-803, COLANG-805, COLANG-807, COLANG-809, COLANG-811

---

## B.5 -- Fail-Open Decorator Pattern

#### Pattern: `config/guardrails/actions.py` -- Fail-open decorator usage

> **Type: PATTERN** -- For Phase B implementation agents ONLY. Must NOT be passed to Phase A test agents.

```python
# Illustrative pattern — not the final implementation

# Every action function has TWO decorators stacked:
# 1. @action() — registers with NeMo (outer)
# 2. @_fail_open(default) — catches exceptions (inner, wraps the function directly)

@action()
@_fail_open({"valid": True, "length": 0, "reason": ""})
async def check_query_length(query: str) -> dict:
    """The fail-open default MUST be a safe/passing result.

    If this action raises any exception (e.g., TypeError on None input),
    _fail_open catches it and returns {"valid": True, "length": 0, "reason": ""},
    which means the query passes this rail. This ensures a broken action
    never blocks the pipeline.
    """
    length = len(query.strip())
    if length < 3:
        return {"valid": False, "length": length, "reason": "Query too short."}
    if length > 2000:
        return {"valid": False, "length": length, "reason": "Query too long."}
    return {"valid": True, "length": length, "reason": ""}
```

**Why this pattern:** The dual-decorator stack ensures every action is both NeMo-registered
and fail-safe. The `_fail_open` default dict is chosen to represent a "pass" verdict --
if the action crashes, the pipeline continues as if the check passed. This matches the
fail-open design principle (COLANG-205, COLANG-907) and the parent spec's REQ-902
(graceful degradation). The decorator logs a WARNING with the action name and error message
but never includes the raw query/answer content (COLANG-911).

---

## B.6 -- Lazy Initialization Pattern

#### Pattern: `config/guardrails/actions.py` -- Lazy executor initialization

> **Type: PATTERN** -- For Phase B implementation agents ONLY. Must NOT be passed to Phase A test agents.

```python
# Illustrative pattern — not the final implementation

_rail_instances: Dict[str, Any] = {}

def _get_input_executor():
    """Lazy-initialize InputRailExecutor on first call.

    Rail class instances are NOT created at import time. This avoids failures
    when optional dependencies (spaCy models, YAML pattern files) are unavailable.
    The _rail_instances dict starts empty and is populated on first action call.
    """
    if "input_executor" not in _rail_instances:
        # Imports are inside the function body — deferred until first use
        from config.settings import RAG_NEMO_INJECTION_ENABLED, ...
        from src.guardrails.executor import InputRailExecutor
        from src.guardrails.injection import InjectionDetector

        # Env var toggles control whether rail classes are instantiated
        injection_detector = (
            InjectionDetector(...)
            if RAG_NEMO_INJECTION_ENABLED
            else None  # None = disabled, executor skips this rail
        )

        _rail_instances["input_executor"] = InputRailExecutor(
            injection_detector=injection_detector,
            # ... other rail instances
        )

    return _rail_instances["input_executor"]
```

**Why this pattern:** Import-time initialization would fail when optional dependencies
(spaCy models, YAML pattern files, model classifiers) are unavailable. By deferring
construction to the first action call, the runtime environment is fully configured and
all dependencies are available. The singleton is stored in `_rail_instances` and reused
for subsequent calls. Environment variable toggles (e.g., `RAG_NEMO_INJECTION_ENABLED`)
control which rail classes are instantiated -- disabled rails produce `None`, which the
executor skips (COLANG-209, COLANG-219).

---

## B.7 -- Session State Management Pattern

#### Pattern: `config/guardrails/actions.py` -- Per-session state tracking

> **Type: PATTERN** -- For Phase B implementation agents ONLY. Must NOT be passed to Phase A test agents.

```python
# Illustrative pattern — not the final implementation

import time

_abuse_session_state: Dict[str, list] = {}  # session_id -> list of timestamps

@action()
@_fail_open({"abusive": False, "reason": ""})
async def check_abuse_pattern(query: str, context: dict = None) -> dict:
    """Per-session rate limiting using in-memory state.

    The context parameter is provided by NeMo runtime and contains session_id.
    State is NOT persisted across worker restarts — escalation counters reset.
    """
    session_id = context.get("session_id", "default") if context else "default"
    now = time.time()
    window = 60  # 1 minute window

    # Initialize session if new
    if session_id not in _abuse_session_state:
        _abuse_session_state[session_id] = []

    # Prune timestamps outside the window
    _abuse_session_state[session_id] = [
        t for t in _abuse_session_state[session_id] if now - t < window
    ]

    # Record this query
    _abuse_session_state[session_id].append(now)

    # Check threshold
    if len(_abuse_session_state[session_id]) > 20:
        return {"abusive": True, "reason": "Rate limit exceeded"}
    return {"abusive": False, "reason": ""}
```

**Why this pattern:** Session-scoped state (abuse rate, jailbreak escalation) requires
tracking across multiple queries from the same user session. In-memory dicts keyed by
`session_id` from NeMo's context are sufficient for single-worker deployments. The
sliding window approach (pruning timestamps older than 60s) ensures accurate rate
counting. Session state is intentionally not persisted -- escalation counters reset on
worker restart, which is acceptable at current scale (COLANG-211, Assumption A-5).

---

## B.8 -- Two-Step Bot Message Modification Pattern

#### Pattern: `config/guardrails/output_rails.co` -- Action-result pattern for $bot_message

> **Type: PATTERN** -- For Phase B implementation agents ONLY. Must NOT be passed to Phase A test agents.

```colang
# Illustrative pattern — not the final implementation

# WRONG — assigns entire dict to $bot_message:
# $bot_message = await prepend_hedge(answer=$bot_message)

# CORRECT — two-step extraction of the string value:
flow output rails check confidence
  $result = await check_response_confidence(answer=$bot_message)
  if $result.confidence == "none"
    await bot say "I couldn't find relevant information."
    abort
  else if $result.confidence == "low" and not $low_confidence_noted
    $mod = await prepend_hedge(answer=$bot_message)
    $bot_message = $mod.answer
```

**Why this pattern:** All actions return dicts (per COLANG-203), not bare strings.
Assigning the action result directly to `$bot_message` would set `$bot_message` to
the entire dict object, corrupting the NeMo response. The two-step pattern
(`$mod = await ...; $bot_message = $mod.answer`) extracts the string value from the
dict. This pattern is required by COLANG-517 and must be used by every output rail
that modifies `$bot_message`.

---

## Companion Documents

| Document | Purpose | Relationship |
|----------|---------|-------------|
| COLANG_GUARDRAILS_SPEC.md | Authoritative requirements specification | Source of all COLANG-xxx requirements traced in this design |
| COLANG_DESIGN_GUIDE.md | Colang 2.0 syntax reference and project conventions | Reference for flow syntax and naming conventions |
| **COLANG_GUARDRAILS_DESIGN.md** (this document) | Task decomposition and code appendix | Translates spec into implementable tasks |
| COLANG_GUARDRAILS_IMPLEMENTATION.md | Phased implementation plan | Operationalizes this design's tasks |
| COLANG_GUARDRAILS_ENGINEERING_GUIDE.md | Post-implementation reference | Documents what was built |

**Flow:** Spec --> Design (this document) --> Implementation --> Engineering Guide
