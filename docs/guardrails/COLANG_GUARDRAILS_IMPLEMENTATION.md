> **Document type:** Six-phase implementation plan (Layer 5)
> **Companion spec:** `COLANG_GUARDRAILS_SPEC.md`
> **Companion design:** `COLANG_GUARDRAILS_DESIGN.md`
> **Upstream:** COLANG_GUARDRAILS_SPEC.md, COLANG_GUARDRAILS_DESIGN.md
> **Downstream:** COLANG_GUARDRAILS_ENGINEERING_GUIDE.md
> **Last updated:** 2026-03-25

> **Historical artifact:** This is the retroactive implementation plan for the Colang 2.0 Guardrails Subsystem. The code, flows, and tests described here already exist in the repository. The File Structure section reflects the implemented layout. Phase steps and code blocks are planning artifacts preserved for traceability — they reflect what was built, not what remains to be built.

> **For agentic workers:** This plan has six phases: Phase 0 (contracts), Phase A (spec tests), Phase B (implementation), Phase C (engineering guide), Phase D (white-box tests), Phase E (full suite).
> REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

# Colang 2.0 Guardrails Subsystem — Implementation Plan

**Goal:** Implement the Colang 2.0 declarative policy layer (COLANG-101 through COLANG-911) as 33 flows across 5 `.co` files, 26 Python `@action()` wrappers, and a `GuardrailsRuntime` singleton integrated into the RAG chain via a single `generate_async()` call.

**Architecture:** Dual-layer design — a Colang layer of 33 declarative flows (5 files) expresses policy decisions (block, modify, hedge, escalate), while a Python layer of 26 `@action()` wrappers performs computation (regex matching, rate counting, executor delegation). The entire pipeline — 11 input rails, generation, 7 output rails — runs inside a single `generate_async()` call to the NeMo Guardrails runtime. The `rag_retrieve_and_generate` action bridges back to the RAG chain for retrieval+generation, replacing NeMo's default LLM call. Deterministic checks run before expensive Python executor calls in both input and output rail ordering.

**Tech Stack:** Python 3.10+, `nemoguardrails>=0.21.0`, Colang 2.0, `langdetect`, `re`, `asyncio.run_in_executor` for sync-to-async bridging, `pytest-asyncio`.

---

## File Structure

```
config/guardrails/                              # NeMo config directory (auto-discovered)
├── config.yml                                  # CREATE — NeMo runtime config, rail registration
├── actions.py                                  # CREATE — 26 @action()-decorated wrappers
├── input_rails.co                              # CREATE — 5 input rail flows (query validation)
├── conversation.co                             # CREATE — 10 flows (greetings, follow-ups, off-topic)
├── output_rails.co                             # CREATE — 7 output rail flows (response quality)
├── safety.co                                   # CREATE — 4 safety input rail flows
└── dialog_patterns.co                          # CREATE — 7 flows (ambiguity, scope, feedback)

src/guardrails/
└── runtime.py                                  # CREATE — GuardrailsRuntime singleton

src/retrieval/
└── rag_chain.py                                # MODIFY — integrate generate_async() bridge

tests/guardrails/
├── conftest.py                                 # CREATE — langchain_core ghost module fix
├── test_colang_actions.py                      # CREATE (Phase A) — unit tests, deterministic actions
├── test_colang_flows.py                        # CREATE (Phase A) — integration tests, .co parsing
├── test_colang_rail_wrappers.py                # CREATE (Phase A) — executor bridge action tests
└── test_colang_e2e.py                          # CREATE (Phase A/E) — E2E + regression tests
```

### Contracts (Phase 0)

| File | Type | Phase |
|------|------|-------|
| `config/guardrails/actions.py` | Module infrastructure + 26 action stubs | Phase 0 |
| `src/guardrails/runtime.py` | GuardrailsRuntime class skeleton | Phase 0 |
| `config/guardrails/config.yml` | NeMo config skeleton | Phase 0 |

### Source (Phase B — stubs become implementations)

| File | Phase B task |
|------|-------------|
| `config/guardrails/actions.py` | B-2.1, B-2.2, B-2.3 |
| `config/guardrails/input_rails.co` | B-3.1 |
| `config/guardrails/safety.co` | B-3.2 |
| `config/guardrails/conversation.co` | B-4.1 |
| `config/guardrails/dialog_patterns.co` | B-4.2 |
| `config/guardrails/output_rails.co` | B-5.1 |
| `src/guardrails/runtime.py` | B-6.1 |
| `src/retrieval/rag_chain.py` | B-6.2 |

### Tests (Phase A)

| File | Covers |
|------|--------|
| `tests/guardrails/test_colang_actions.py` | Tasks 2.1, 2.2, 2.3 (COLANG-2xx) |
| `tests/guardrails/test_colang_flows.py` | Tasks 1.x, 3.x, 4.x, 5.x (COLANG-1xx, 3xx–7xx) |
| `tests/guardrails/test_colang_rail_wrappers.py` | Task 2.3 (COLANG-213, 215, 217) |
| `tests/guardrails/test_colang_e2e.py` | Tasks 6.x, 7.x (COLANG-8xx, 9xx) |

---

## Phase Gate Tracker

| Phase | Status | Gate Criteria | Approved |
|-------|--------|--------------|----------|
| Phase 0 — Contracts | ☐ | All contract files created, types and stubs compile cleanly | ☐ |
| Phase A — Spec Tests | ☐ | All test files created; all tests FAIL against stubs | ☐ |
| Phase B — Implementation | ☐ | All tests PASS; all flows parse; runtime initializes | ☐ |
| Phase C — Engineering Guide | ☐ | Module sections + cross-cutting sections complete | ☐ |
| Phase D — White-Box Tests | ☐ | All Phase D test files created; tests FAIL on first run | ☐ |
| Phase E — Full Suite | ☐ | All Phase A + Phase D tests PASS | ☐ |

**Rule:** Each phase gate must be approved before the next phase begins.

---

## Dependency Graph

```
Phase 0 (Contracts)
├── Task 0.1: actions.py module infrastructure + action stubs ──────┐
├── Task 0.2: runtime.py class skeleton (stub methods)             │
└── Task 0.3: config.yml skeleton                                  │
       │                                                            │
       ▼                                                            │
  [REVIEW GATE — human approves Phase 0 before Phase A begins]     │
       │                                                            │
       ▼                                                            │
Phase A (Spec Tests — all parallel)                                 │
├── Task A-2.1: test_colang_actions.py (actions infrastructure)    │
├── Task A-2.2: test_colang_actions.py (deterministic actions)     │
├── Task A-2.3: test_colang_rail_wrappers.py (executor bridges)    │
├── Task A-3.1: test_colang_flows.py (input rail flows)            │
├── Task A-3.2: test_colang_flows.py (safety flows)                │
├── Task A-4.1: test_colang_flows.py (conversation flows)          │
├── Task A-4.2: test_colang_flows.py (dialog patterns)             │
├── Task A-5.1: test_colang_flows.py (output rail flows)           │
└── Task A-6.1: test_colang_e2e.py (runtime + e2e)                │
       │                                                            │
       ▼ [Phase A gate: all spec reviews ✅]                        │
Phase B (Implementation — follows dependency graph)                 │
├── Task B-1.1: config.yml, .co scaffolds ◄─── Phase 0            │
├── Task B-1.2: Colang syntax validation ◄─── B-1.1               │
├── Task B-1.3: config.yml rail registration ◄─── B-1.1           │
├── Task B-2.1: actions.py infrastructure ◄─── B-1.1              │
├── Task B-2.2: deterministic actions ◄─── B-2.1                  │
├── Task B-2.3: executor bridge actions ◄─── B-2.1                │
├── Task B-3.1: input_rails.co ◄─── B-2.2, B-2.3, B-1.3          │
├── Task B-3.2: safety.co ◄─── B-2.2, B-1.3                      │
├── Task B-4.1: conversation.co ◄─── B-2.2, B-1.3                 │
├── Task B-4.2: dialog_patterns.co ◄─── B-2.2, B-1.3              │
├── Task B-5.1: output_rails.co ◄─── B-2.2, B-2.3, B-1.3         │
├── Task B-6.1: runtime.py ◄─── B-1.1                             │
└── Task B-6.2: rag_chain.py bridge ◄─── B-6.1, B-2.3            │
       │                                                            │
       ▼ [Phase B gate: all tests PASS]                             │
Phase C → Phase D → Phase E                                         │
                                                                    │
Critical path: 0.1 → B-2.1 → B-2.2/2.3 → B-3.1/3.2/4.1/4.2/5.1  │
                   → B-6.1 → B-6.2                                  └─ feeds all phases
```

---

## Task-to-Requirement Mapping

| Task | Phase 0 contracts | Phase A test file | Phase B source | FR numbers |
|------|------------------|------------------|----------------|------------|
| 1.1 Config Scaffold | `config.yml`, `actions.py` stubs | `test_colang_flows.py` | `config.yml`, `actions.py` | COLANG-101, 103, 111, 813, 815 |
| 1.2 Syntax Validation | N/A | `test_colang_flows.py` | All `.co` files | COLANG-101, 105, 109 |
| 1.3 Rail Registration | `config.yml` | `test_colang_flows.py` | `config.yml` | COLANG-311, 515 |
| 2.1 Action Infrastructure | `actions.py` | `test_colang_actions.py` | `actions.py` | COLANG-205, 207, 209, 211 |
| 2.2 Deterministic Actions | `actions.py` | `test_colang_actions.py` | `actions.py` | COLANG-201, 203, 221 |
| 2.3 Executor Bridge Actions | `actions.py` | `test_colang_rail_wrappers.py` | `actions.py` | COLANG-201, 213, 215, 217, 219 |
| 3.1 Query Validation Rails | N/A | `test_colang_flows.py` | `input_rails.co` | COLANG-107, 301, 303, 305, 307, 309 |
| 3.2 Safety Input Rails | N/A | `test_colang_flows.py` | `safety.co` | COLANG-107, 601, 603, 605, 607 |
| 4.1 Conversation Flows | N/A | `test_colang_flows.py` | `conversation.co` | COLANG-107, 401, 403, 405, 407, 409, 411 |
| 4.2 RAG Dialog Patterns | N/A | `test_colang_flows.py` | `dialog_patterns.co` | COLANG-107, 701, 703, 705, 707 |
| 5.1 Output Rail Flows | N/A | `test_colang_flows.py` | `output_rails.co` | COLANG-107, 501, 503, 505, 507, 509, 511, 513, 517 |
| 6.1 GuardrailsRuntime | `runtime.py` | `test_colang_e2e.py` | `runtime.py` | COLANG-801, 803, 805, 807, 809, 811 |
| 6.2 RAG Chain Bridge | N/A | `test_colang_e2e.py` | `rag_chain.py` | COLANG-807, 217 |
| 7.1 Unit Tests | N/A | `test_colang_actions.py` | _(test file itself)_ | COLANG-905, 221 |
| 7.2 Integration Tests | N/A | `test_colang_flows.py` | _(test file itself)_ | COLANG-905, 107, 105 |
| 7.3 E2E Tests | N/A | `test_colang_e2e.py` | _(test file itself)_ | COLANG-905, 907, 903 |
| 7.4 Non-Functional | N/A | `test_colang_actions.py` | N/A | COLANG-901, 909, 911 |

---

## Phase 0 — Contract Definitions

**Purpose:** Define all module infrastructure, action signatures, and the runtime skeleton BEFORE any tests or implementation. This is the shared contract that both test and implementation agents work against. No business logic — only type signatures, decorators with `raise NotImplementedError` stubs, and the infrastructure scaffolding.

**Review gate:** Phase 0 output must be human-reviewed and approved before Phase A begins. Any contract change after approval requires re-review.

---

### Task 0.1 — Action Module Infrastructure and Stubs

**Files:**
- Create: `config/guardrails/actions.py`

- [ ] Step 1: Create the module with conditional NeMo import and fail-open decorator:

```python
# config/guardrails/actions.py
"""NeMo Guardrails Colang action wrappers.

Each function decorated with @action() is auto-discovered by the NeMo runtime
when this file lives inside the guardrails config directory. Actions are thin
wrappers — they delegate to existing rail classes or implement lightweight
deterministic checks. All actions return dicts for Colang variable assignment.
"""

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

**Requirements covered:** COLANG-205, COLANG-207, COLANG-209, COLANG-211

- [ ] Step 2: Add action stubs for all 18 lightweight deterministic actions. Each stub uses the correct `@action()` + `@_fail_open(default)` decoration and `raise NotImplementedError("Task 2.2.X")`:

```python
@action()
@_fail_open({"valid": True, "length": 0, "reason": ""})
async def check_query_length(query: str) -> dict:
    """Validate query length: min 3 chars, max 2000 chars.

    Returns: valid (bool), length (int), reason (str).
    """
    raise NotImplementedError("Task 2.2.1")


@action()
@_fail_open({"language": "en", "supported": True})
async def detect_language(query: str) -> dict:
    """Detect query language using langdetect. Only English is supported.

    Returns: language (str ISO 639-1), supported (bool).
    """
    raise NotImplementedError("Task 2.2.1")


@action()
@_fail_open({"clear": True, "suggestion": ""})
async def check_query_clarity(query: str) -> dict:
    """Heuristic clarity check: reject very short or all-stopword queries.

    Returns: clear (bool), suggestion (str).
    """
    raise NotImplementedError("Task 2.2.1")


@action()
@_fail_open({"abusive": False, "reason": ""})
async def check_abuse_pattern(query: str, context: dict = None) -> dict:
    """Track query rate per session. Flag if > 20 queries in 60-second window.

    Returns: abusive (bool), reason (str).
    """
    raise NotImplementedError("Task 2.2.2")


@action()
@_fail_open({"escalation_level": "none"})
async def check_jailbreak_escalation(query: str, context: dict = None) -> dict:
    """Track jailbreak attempt count per session. Thresholds: 1-2=warn, 3+=block.

    Returns: escalation_level (str: "none" | "warn" | "block").
    """
    raise NotImplementedError("Task 2.2.2")


@action()
@_fail_open({"sensitive": False, "disclaimer": "", "domain": ""})
async def check_sensitive_topic(query: str) -> dict:
    """Keyword + regex check for medical/legal/financial sensitive topics.

    Returns: sensitive (bool), disclaimer (str), domain (str).
    """
    raise NotImplementedError("Task 2.2.3")


@action()
@_fail_open({"attempt": False, "pattern": ""})
async def check_exfiltration(query: str) -> dict:
    """Detect bulk data extraction patterns via regex.

    Returns: attempt (bool), pattern (str).
    """
    raise NotImplementedError("Task 2.2.3")


@action()
@_fail_open({"violation": False})
async def check_role_boundary(query: str) -> dict:
    """Detect role-play and instruction-override patterns via regex.

    Returns: violation (bool).
    """
    raise NotImplementedError("Task 2.2.3")


@action()
@_fail_open({"has_citations": True})
async def check_citations(answer: str) -> dict:
    """Check if answer contains citation patterns like [Source: ...] or [1].

    Returns: has_citations (bool).
    """
    raise NotImplementedError("Task 2.2.4")


@action()
@_fail_open({"answer": ""})
async def add_citation_reminder(answer: str) -> dict:
    """Append citation reminder to answer.

    Returns: answer (str) with reminder appended.
    """
    raise NotImplementedError("Task 2.2.4")


@action()
@_fail_open({"confidence": "high"})
async def check_response_confidence(answer: str) -> dict:
    """Read retrieval confidence from NeMo context.

    Returns: confidence (str: "none" | "low" | "high").
    """
    raise NotImplementedError("Task 2.2.4")


@action()
@_fail_open({"answer": ""})
async def prepend_hedge(answer: str) -> dict:
    """Prepend hedge language for low-confidence answers.

    Returns: answer (str) with hedge prepended.
    """
    raise NotImplementedError("Task 2.2.4")


@action()
@_fail_open({"answer": ""})
async def prepend_text(text: str, answer: str) -> dict:
    """Prepend arbitrary text (e.g., disclaimer) to answer.

    Returns: answer (str) with text prepended.
    """
    raise NotImplementedError("Task 2.2.4")


@action()
@_fail_open({"answer": ""})
async def prepend_low_confidence_note(answer: str) -> dict:
    """Prepend low-confidence note to answer.

    Returns: answer (str) with note prepended.
    """
    raise NotImplementedError("Task 2.2.4")


@action()
@_fail_open({"valid": True, "reason": ""})
async def check_answer_length(answer: str) -> dict:
    """Validate answer length: min 20 chars, max 5000 chars.

    Returns: valid (bool), reason (str: "too short" | "too long" | "").
    """
    raise NotImplementedError("Task 2.2.4")


@action()
@_fail_open({"answer": ""})
async def adjust_answer_length(answer: str, reason: str) -> dict:
    """Truncate overly long answers or flag terse ones.

    Returns: answer (str) adjusted.
    """
    raise NotImplementedError("Task 2.2.4")


@action()
@_fail_open({"has_context": False, "augmented_query": ""})
async def handle_follow_up(query: str) -> dict:
    """Check NeMo conversation context for prior Q&A pairs.

    Returns: has_context (bool), augmented_query (str).
    """
    raise NotImplementedError("Task 2.2.5")


@action()
@_fail_open({"drifted": False})
async def check_topic_drift(query: str) -> dict:
    """Detect topic change between conversation turns.

    Returns: drifted (bool).
    """
    raise NotImplementedError("Task 2.2.5")
```

- [ ] Step 3: Add stubs for the 5 dialog/retrieval actions and 8 executor bridge actions. Exact signatures and fail-open defaults must match the Colang flow `$result.key` access patterns in Phase B:

```python
# Dialog actions
@action()
@_fail_open({"has_results": True, "count": 1, "avg_confidence": 1.0})
async def check_retrieval_results(answer: str) -> dict:
    raise NotImplementedError("Task 2.2.5")

@action()
@_fail_open({"in_scope": True})
async def check_source_scope(answer: str) -> dict:
    raise NotImplementedError("Task 2.2.5")

@action()
@_fail_open({"ambiguous": False, "disambiguation_prompt": ""})
async def check_query_ambiguity(query: str) -> dict:
    raise NotImplementedError("Task 2.2.5")

@action()
@_fail_open({"summary": "This knowledge base contains documents about various topics."})
async def get_knowledge_base_summary() -> dict:
    raise NotImplementedError("Task 2.2.5")

# Executor bridge stubs
@action()
@_fail_open({"verdict": "pass", "method": "none", "confidence": 0.0})
async def check_injection(query: str) -> dict:
    raise NotImplementedError("Task 2.3.1")

@action()
@_fail_open({"found": False, "entities": [], "redacted_text": ""})
async def detect_pii(text: str, direction: str = "input") -> dict:
    raise NotImplementedError("Task 2.3.1")

@action()
@_fail_open({"verdict": "pass", "score": 0.0})
async def check_toxicity(text: str, direction: str = "input") -> dict:
    raise NotImplementedError("Task 2.3.1")

@action()
@_fail_open({"on_topic": True, "confidence": 1.0})
async def check_topic_safety(query: str) -> dict:
    raise NotImplementedError("Task 2.3.1")

@action()
@_fail_open({"verdict": "pass", "score": 1.0, "claim_scores": []})
async def check_faithfulness(answer: str, context_chunks: list = None) -> dict:
    raise NotImplementedError("Task 2.3.1")

@action()
@_fail_open({"action": "pass", "intent": "rag_search", "redacted_query": "", "reject_message": "", "metadata": {}})
async def run_input_rails(query: str) -> dict:
    raise NotImplementedError("Task 2.3.2")

@action()
@_fail_open({"action": "pass", "redacted_answer": "", "reject_message": "", "metadata": {}})
async def run_output_rails(answer: str) -> dict:
    raise NotImplementedError("Task 2.3.3")

@action()
@_fail_open({"answer": "", "sources": [], "confidence": 0.0})
async def rag_retrieve_and_generate(query: str) -> dict:
    raise NotImplementedError("Task 2.3.4")


def set_rag_chain(chain) -> None:
    """Inject the RAG chain reference for rag_retrieve_and_generate."""
    global _rag_chain
    _rag_chain = chain

_rag_chain = None
```

**Requirements covered:** COLANG-201, COLANG-203, COLANG-205, COLANG-207, COLANG-209, COLANG-211, COLANG-213, COLANG-215, COLANG-217, COLANG-219, COLANG-221

---

### Task 0.2 — GuardrailsRuntime Class Skeleton

**Files:**
- Create: `src/guardrails/runtime.py`

- [ ] Step 1: Create the `GuardrailsRuntime` class with method stubs and full docstrings:

```python
# src/guardrails/runtime.py
"""NeMo Guardrails runtime lifecycle manager."""
from __future__ import annotations

import logging
import threading
from typing import Any, Optional

logger = logging.getLogger("rag.guardrails.runtime")


class GuardrailsRuntime:
    """Singleton manager for the NeMo Guardrails runtime.

    Thread-safe singleton with lazy NeMo imports. Initializes once at worker
    startup and reuses the LLMRails instance across all queries.
    """

    _instance: Optional[GuardrailsRuntime] = None
    _initialized: bool = False
    _rails = None  # LLMRails instance
    _auto_disabled: bool = False
    _lock: threading.Lock = threading.Lock()

    @classmethod
    def get(cls) -> GuardrailsRuntime:
        """Return the process-wide singleton. Thread-safe via double-checked locking."""
        raise NotImplementedError("Task 6.1.1")

    @classmethod
    def is_enabled(cls) -> bool:
        """Return True only when RAG_NEMO_ENABLED=true and not auto-disabled."""
        raise NotImplementedError("Task 6.1.5")

    def initialize(self, config_dir: str) -> None:
        """Load NeMo config and compile Colang flows. Idempotent.

        Raises:
            SyntaxError: If Colang parsing fails (fail-fast at startup).
        """
        raise NotImplementedError("Task 6.1.2")

    async def generate_async(self, messages: list[dict]) -> dict:
        """Execute rails on a message sequence.

        Returns empty assistant message when rails are unavailable.
        """
        raise NotImplementedError("Task 6.1.4")

    def register_actions(self, actions: dict[str, callable]) -> None:
        """Register custom Python actions with the NeMo runtime."""
        raise NotImplementedError("Task 6.1.6")

    def shutdown(self) -> None:
        """Release runtime resources."""
        raise NotImplementedError("Task 6.1.7")

    @classmethod
    def reset(cls) -> None:
        """Reset singleton state (for testing)."""
        raise NotImplementedError("Task 6.1.7")
```

**Requirements covered:** COLANG-801, COLANG-803, COLANG-805, COLANG-807, COLANG-809, COLANG-811

---

### Task 0.3 — NeMo Config Skeleton

**Files:**
- Create: `config/guardrails/config.yml`

- [ ] Step 1: Create the config skeleton with `colang_version: "2.x"`, Ollama LLM provider, and empty rail lists:

```yaml
colang_version: "2.x"

models:
  - type: main
    engine: ollama
    model: ${RAG_OLLAMA_MODEL:-qwen2.5:3b}
    parameters:
      base_url: ${RAG_OLLAMA_URL:-http://localhost:11434}
      temperature: 0.1

rails:
  input:
    flows: []
  output:
    flows: []
```

- [ ] Step 2: Verify `RailsConfig.from_path("config/guardrails/")` succeeds on the empty scaffold (no `.co` content yet).

- [ ] Step 3: Confirm the config does NOT register any NeMo built-in flows (`check jailbreak`, `jailbreak detection heuristics`, `check faithfulness`, `self check facts`, `self check output`).

**Requirements covered:** COLANG-101, COLANG-813, COLANG-815

---

## Phase A — Spec Tests (Isolated from Implementation)

**Agent isolation contract:** The test agent receives ONLY:
1. The spec requirements (COLANG-xxx FR numbers + acceptance criteria)
2. The contract files from Phase 0 (`actions.py` stubs, `runtime.py` skeleton, `config.yml`)
3. The task description from the design document

**Must NOT receive:** Any implementation code, any pattern entries from the design doc's code appendix (Part B Pattern entries), any source files beyond Phase 0 stubs.

---

### Task A-2.1 — Spec Tests: Action Module Infrastructure

**Agent input (ONLY these):**
- COLANG-205 (fail-open), COLANG-207 (conditional import), COLANG-209 (lazy init), COLANG-211 (session state)
- `config/guardrails/actions.py` (Phase 0 stubs only)

**Must NOT receive:** `src/guardrails/`, `src/retrieval/`, design doc Part B Pattern entries

**Files:**
- Create: `tests/guardrails/test_colang_actions.py` (infrastructure section)

**Test cases:**
- COLANG-207: `from config.guardrails.actions import check_query_length` succeeds even when `nemoguardrails` is not installed
- COLANG-207: No-op decorator passes through the decorated function unchanged
- COLANG-205: Mock an action to raise `RuntimeError` — verify `_fail_open` returns default dict and logs at WARNING level
- COLANG-209: `_rail_instances` is empty immediately after module import
- COLANG-211: `_jailbreak_session_state` and `_abuse_session_state` are empty dicts after module import

```bash
pytest tests/guardrails/test_colang_actions.py -v
# Expected: FAIL (stubs raise NotImplementedError)
```

---

### Task A-2.2 — Spec Tests: Deterministic Actions

**Agent input (ONLY these):**
- COLANG-201, COLANG-203, COLANG-221 + acceptance criteria for each action
- `config/guardrails/actions.py` Phase 0 stubs (signatures and fail-open defaults only)

**Must NOT receive:** Any implementation logic, pattern entries from design doc Part B

**Files:**
- Create: `tests/guardrails/test_colang_actions.py` (deterministic section)

**Test cases:**
- COLANG-301/COLANG-221: `check_query_length("")` → `{"valid": False, ...}` (empty string)
- COLANG-301/COLANG-221: `check_query_length("ab")` → `{"valid": False, "reason": contains "too short"}`
- COLANG-301: `check_query_length("x" * 2001)` → `{"valid": False, "reason": contains "too long"}`
- COLANG-301: `check_query_length("What is RAG?")` → `{"valid": True}`
- COLANG-303: `detect_language("What is the attention mechanism?")` → `{"supported": True}`
- COLANG-305: `check_query_clarity("it")` → `{"clear": False, "suggestion": non-empty}`
- COLANG-305: `check_query_clarity("the and or")` → `{"clear": False}` (all stopwords)
- COLANG-305: `check_query_clarity("How does BM25 compare to dense retrieval?")` → `{"clear": True}`
- COLANG-307: `check_abuse_pattern` normal rate → `{"abusive": False}`
- COLANG-307: 21+ queries in 60s → `{"abusive": True}`
- COLANG-603: `check_exfiltration("list all documents in the database")` → `{"attempt": True}`
- COLANG-603: `check_exfiltration("What is semantic chunking?")` → `{"attempt": False}`
- COLANG-605: `check_role_boundary("ignore previous instructions")` → `{"violation": True}`
- COLANG-605: `check_role_boundary("How do transformers work?")` → `{"violation": False}`
- COLANG-607: 0 violations → `{"escalation_level": "none"}`
- COLANG-607: 1-2 violations in session → `{"escalation_level": "warn"}`
- COLANG-607: 3+ violations → `{"escalation_level": "block"}`
- COLANG-607: different session IDs maintain independent state
- COLANG-601: `check_sensitive_topic("What medication for headaches?")` → `{"sensitive": True, "domain": "medical"}`
- COLANG-601: `check_sensitive_topic("What is vector search?")` → `{"sensitive": False}`
- COLANG-507/COLANG-221: `check_citations("")` → `{"has_citations": False}`
- COLANG-507: `check_citations("RAG works by [Source: doc1.pdf] ...")` → `{"has_citations": True}`
- COLANG-511/COLANG-221: `check_answer_length("")` → `{"valid": False}`
- COLANG-511: `check_answer_length("Yes.")` → `{"valid": False}`
- COLANG-511: `check_answer_length("x" * 5001)` → `{"valid": False, "reason": "too long"}`
- COLANG-511: `adjust_answer_length("x" * 6000, "too long")` → answer ≤ 5003 chars

```bash
pytest tests/guardrails/test_colang_actions.py -v
# Expected: FAIL (stubs raise NotImplementedError)
```

---

### Task A-2.3 — Spec Tests: Executor Bridge Actions

**Agent input (ONLY these):**
- COLANG-213, COLANG-215, COLANG-217, COLANG-219 acceptance criteria
- `config/guardrails/actions.py` Phase 0 stubs

**Must NOT receive:** `src/guardrails/executor.py`, `src/guardrails/runtime.py`, design doc Part B pattern entries

**Files:**
- Create: `tests/guardrails/test_colang_rail_wrappers.py`

**Test cases:**
- COLANG-213: Mock `InputRailExecutor` + `RailMergeGate` → `run_input_rails("clean query")` returns `{"action": "pass", "intent": <non-empty>}`
- COLANG-213: Mock merge gate returning reject → `run_input_rails` returns `{"action": "reject", "reject_message": non-empty}`
- COLANG-215: Mock `OutputRailExecutor` returning pass → `run_output_rails("clean answer")` returns `{"action": "pass"}`
- COLANG-217: `rag_retrieve_and_generate` with no chain set → fail-open returns `{"answer": "", "sources": [], "confidence": 0.0}`
- COLANG-219: When env var toggles disable a rail, `_get_input_executor()` passes `None` for that rail class

```bash
pytest tests/guardrails/test_colang_rail_wrappers.py -v
# Expected: FAIL (stubs raise NotImplementedError)
```

---

### Task A-3.1 — Spec Tests: Query Validation Input Rails

**Agent input (ONLY these):**
- COLANG-301, COLANG-303, COLANG-305, COLANG-307, COLANG-309, COLANG-311 acceptance criteria
- `config/guardrails/actions.py` Phase 0 stubs

**Must NOT receive:** `config/guardrails/input_rails.co`, design doc Part B pattern entries

**Files:**
- Create: `tests/guardrails/test_colang_flows.py` (input rail section)

**Test cases:**
- COLANG-103: Files `input_rails.co`, `conversation.co`, `output_rails.co`, `safety.co`, `dialog_patterns.co` all exist in `config/guardrails/`
- COLANG-103: `actions.py` exists in `config/guardrails/`
- COLANG-101: `RailsConfig.from_path("config/guardrails/")` returns non-None (no `SyntaxError`)
- COLANG-107: `input_rails.co` contains exactly 5 `flow` definitions
- COLANG-311: `config.yml` `rails.input.flows` list has exactly 11 entries in spec order
- COLANG-311: First entry is `"input rails check query length"`, last is `"input rails run python executor"`
- COLANG-815: `config.yml` does not contain `"check jailbreak"` or `"jailbreak detection heuristics"` in input flows
- COLANG-109: All action calls in `input_rails.co` use `await` keyword and assign to `$variables`

```bash
pytest tests/guardrails/test_colang_flows.py::test_all_co_files_parse -v
# Expected: FAIL if .co files not yet created
```

---

### Task A-3.2 — Spec Tests: Safety Input Rails

**Agent input (ONLY these):**
- COLANG-601, COLANG-603, COLANG-605, COLANG-607, COLANG-107 acceptance criteria
- `config/guardrails/actions.py` Phase 0 stubs

**Must NOT receive:** `config/guardrails/safety.co`, design doc Part B pattern entries

**Files:**
- Create: `tests/guardrails/test_colang_flows.py` (safety section)

**Test cases:**
- COLANG-107: `safety.co` contains exactly 4 `flow` definitions
- COLANG-601: `safety.co` contains `"check sensitive topic"` flow that sets `$sensitive_disclaimer` and does NOT call `abort`
- COLANG-603: `safety.co` contains `"check exfiltration"` flow that calls `abort` on detection
- COLANG-605: `safety.co` contains `"check role boundary"` flow that calls `abort` on detection
- COLANG-607: `safety.co` contains `"check jailbreak escalation"` flow with two escalation branches (`"warn"` and `"block"`) both calling `abort`
- COLANG-105: All 4 safety flows follow `input rails <name>` naming convention

```bash
pytest tests/guardrails/test_colang_flows.py -k "safety" -v
# Expected: FAIL (safety.co not yet populated)
```

---

### Task A-4.1 — Spec Tests: Conversation Management Flows

**Agent input (ONLY these):**
- COLANG-401, COLANG-403, COLANG-405, COLANG-407, COLANG-409, COLANG-411, COLANG-107 acceptance criteria
- `config/guardrails/actions.py` Phase 0 stubs

**Must NOT receive:** `config/guardrails/conversation.co`

**Files:**
- Create: `tests/guardrails/test_colang_flows.py` (conversation section)

**Test cases:**
- COLANG-107: `conversation.co` contains exactly 10 `flow` definitions
- COLANG-401: `user said greeting` intent has at least 5 example utterances
- COLANG-401: `user said farewell` intent has at least 5 example utterances
- COLANG-403: `handle greeting` and `handle farewell` are standalone (not `input rails`) flows
- COLANG-405: `user said administrative` and `handle administrative` exist
- COLANG-407: `handle follow up` calls `abort` when `has_context == False`
- COLANG-409: `input rails check off topic` follows `input rails *` naming and calls `abort`
- COLANG-411: `check topic drift` does NOT call `abort` (sets `$topic_drifted` only)
- COLANG-105: Only `input rails check off topic` uses `input rails *` prefix in this file

```bash
pytest tests/guardrails/test_colang_flows.py -k "conversation" -v
# Expected: FAIL (conversation.co not yet populated)
```

---

### Task A-4.2 — Spec Tests: RAG Dialog Pattern Flows

**Agent input (ONLY these):**
- COLANG-701, COLANG-703, COLANG-705, COLANG-707, COLANG-107 acceptance criteria
- `config/guardrails/actions.py` Phase 0 stubs

**Must NOT receive:** `config/guardrails/dialog_patterns.co`

**Files:**
- Create: `tests/guardrails/test_colang_flows.py` (dialog patterns section)

**Test cases:**
- COLANG-107: `dialog_patterns.co` contains exactly 7 `flow` definitions
- COLANG-701: `input rails check ambiguity` calls `abort` when `ambiguous == True`
- COLANG-703: `user asked about scope` has at least 4 example utterances (COLANG-707)
- COLANG-703: `handle scope question` calls `get_knowledge_base_summary()` action
- COLANG-705: `user gave positive feedback` has at least 4 example utterances (COLANG-707)
- COLANG-705: `user gave negative feedback` has at least 4 example utterances (COLANG-707)
- COLANG-705: `handle positive feedback` and `handle negative feedback` exist as standalone flows
- COLANG-105: Only `input rails check ambiguity` uses `input rails *` prefix in this file

```bash
pytest tests/guardrails/test_colang_flows.py -k "dialog" -v
# Expected: FAIL (dialog_patterns.co not yet populated)
```

---

### Task A-5.1 — Spec Tests: Output Rail Flows

**Agent input (ONLY these):**
- COLANG-501, COLANG-503, COLANG-505, COLANG-507, COLANG-509, COLANG-511, COLANG-513, COLANG-515, COLANG-517 acceptance criteria
- `config/guardrails/actions.py` Phase 0 stubs

**Must NOT receive:** `config/guardrails/output_rails.co`

**Files:**
- Create: `tests/guardrails/test_colang_flows.py` (output rails section)

**Test cases:**
- COLANG-107: `output_rails.co` contains exactly 7 `flow` definitions
- COLANG-515: `config.yml` `rails.output.flows` has exactly 7 entries; first is `"output rails run python executor"`
- COLANG-815: `config.yml` output flows do not contain `"check faithfulness"`, `"self check facts"`, or `"self check output"`
- COLANG-501: `output rails run python executor` is first output rail; calls `abort` on `action == "reject"`
- COLANG-503: `output rails prepend disclaimer` checks `$sensitive_disclaimer`; no-op when unset
- COLANG-505: `output rails check no results` calls `abort` when `has_results == False`; sets `$low_confidence_noted` when `avg_confidence < 0.3`
- COLANG-509: `output rails check confidence` calls `abort` when `confidence == "none"`; skips hedge when `$low_confidence_noted` is set
- COLANG-517: Every `$bot_message` modification uses two-step pattern (`$mod = await ...; $bot_message = $mod.answer`)
- COLANG-105: All 7 output flows follow `output rails <name>` naming convention

```bash
pytest tests/guardrails/test_colang_flows.py -k "output" -v
# Expected: FAIL (output_rails.co not yet populated)
```

---

### Task A-6.1 — Spec Tests: GuardrailsRuntime and E2E

**Agent input (ONLY these):**
- COLANG-801, COLANG-803, COLANG-805, COLANG-807, COLANG-809, COLANG-811, COLANG-903, COLANG-905, COLANG-907 acceptance criteria
- `src/guardrails/runtime.py` Phase 0 skeleton stubs

**Must NOT receive:** Any implementation files, `src/retrieval/rag_chain.py`

**Files:**
- Create: `tests/guardrails/test_colang_e2e.py`

**Test cases:**
- COLANG-801: `GuardrailsRuntime.get() is GuardrailsRuntime.get()` is `True`
- COLANG-803: Calling `initialize()` twice does not re-load configuration
- COLANG-805: A `.co` file with invalid Colang syntax causes `initialize()` to raise `SyntaxError`
- COLANG-807: When runtime is not initialized, `generate_async()` returns `{"role": "assistant", "content": ""}` without raising
- COLANG-809: With `RAG_NEMO_ENABLED=false`, `is_enabled()` returns `False`
- COLANG-903: `from config.guardrails.actions import check_query_length` succeeds without `nemoguardrails` installed
- COLANG-907: When `generate_async()` raises an exception, runtime sets `_auto_disabled = True` and returns empty response
- COLANG-905: Each runtime/e2e failure mode returns results, not unhandled exceptions

```bash
pytest tests/guardrails/test_colang_e2e.py -v
# Expected: FAIL (runtime stubs raise NotImplementedError)
```

---

### Phase A Gate

Phase A gate — all must be approved before Phase B starts:
- [ ] Task A-2.1: spec review
- [ ] Task A-2.2: spec review
- [ ] Task A-2.3: spec review
- [ ] Task A-3.1: spec review
- [ ] Task A-3.2: spec review
- [ ] Task A-4.1: spec review
- [ ] Task A-4.2: spec review
- [ ] Task A-5.1: spec review
- [ ] Task A-6.1: spec review

---

## Phase B — Implementation (Against Tests)

Each Phase B task receives its Phase A test file, the Phase 0 contracts, and the relevant FR numbers. Implementation agents must NOT receive test files from other tasks.

---

### Task B-1 — Foundation: Config Directory, Syntax, Rail Registration

**Agent input:**
- Design doc Tasks 1.1–1.3 descriptions
- Phase A: `tests/guardrails/test_colang_flows.py` (structure section)
- Phase 0: `config/guardrails/config.yml` skeleton
- FR: COLANG-101, COLANG-103, COLANG-105, COLANG-107, COLANG-109, COLANG-111, COLANG-311, COLANG-515, COLANG-813, COLANG-815

**Files:**
- Create: `config/guardrails/input_rails.co` (comment header + empty scaffold)
- Create: `config/guardrails/conversation.co` (comment header + empty scaffold)
- Create: `config/guardrails/output_rails.co` (comment header + empty scaffold)
- Create: `config/guardrails/safety.co` (comment header + empty scaffold)
- Create: `config/guardrails/dialog_patterns.co` (comment header + empty scaffold)
- Modify: `config/guardrails/config.yml` (populate rail lists)

- [ ] Step 1: Add comment headers to each `.co` file per COLANG-111. Headers state file purpose, flow category, and rail vs. dialog distinction.

- [ ] Step 2: Populate `config.yml` `rails.input.flows` in exact order (COLANG-311):
  1. `input rails check query length`
  2. `input rails check language`
  3. `input rails check query clarity`
  4. `input rails check abuse`
  5. `input rails check exfiltration`
  6. `input rails check role boundary`
  7. `input rails check jailbreak escalation`
  8. `input rails check sensitive topic`
  9. `input rails check off topic`
  10. `input rails check ambiguity`
  11. `input rails run python executor`

- [ ] Step 3: Populate `config.yml` `rails.output.flows` in exact order (COLANG-515):
  1. `output rails run python executor`
  2. `output rails prepend disclaimer`
  3. `output rails check no results`
  4. `output rails check confidence`
  5. `output rails check citations`
  6. `output rails check length`
  7. `output rails check scope`

- [ ] Step 4: Add `rails.config` block for jailbreak and sensitive data detection thresholds.

- [ ] Step 5: Verify `RailsConfig.from_path("config/guardrails/")` succeeds:
  ```bash
  python -c "from nemoguardrails import RailsConfig; c = RailsConfig.from_path('config/guardrails/'); print('OK')"
  # Expected: OK
  ```

- [ ] Step 6: Run structure tests:
  ```bash
  pytest tests/guardrails/test_colang_flows.py -k "exist or parse or config" -v
  # Expected: PASS for existence checks; FAIL for flow-count checks (flows not yet written)
  ```

**Requirements covered:** COLANG-101, COLANG-103, COLANG-105, COLANG-111, COLANG-311, COLANG-515, COLANG-813, COLANG-815

---

### Task B-2.1 — Action Module Infrastructure

**Agent input:**
- Design doc Task 2.1 description + Part B Contract entry B.1
- Phase A: `tests/guardrails/test_colang_actions.py` (infrastructure section)
- Phase 0: `config/guardrails/actions.py` stubs
- FR: COLANG-205, COLANG-207, COLANG-209, COLANG-211

**Files:**
- Modify: `config/guardrails/actions.py`

**Must NOT receive:** `tests/guardrails/test_colang_rail_wrappers.py`, `tests/guardrails/test_colang_e2e.py`

- [ ] Step 1: Implement `_fail_open` decorator. Catches any exception; logs WARNING with `fn.__name__` and error message (NOT raw query/answer per COLANG-911); returns `default`. (COLANG-205)

- [ ] Step 2: Verify conditional NeMo import with no-op fallback is in place. (COLANG-207)

- [ ] Step 3: Confirm `_jailbreak_session_state`, `_abuse_session_state`, and `_rail_instances` are initialized as empty dicts at module level. (COLANG-211, COLANG-209)

- [ ] Step 4: Implement `_get_input_executor()` lazy helper — constructs `InputRailExecutor` on first call, reads env var toggles for each rail class, stores shared `_pii` and `_toxicity` instances. (COLANG-209)

- [ ] Step 5: Implement `_get_output_executor()` lazy helper — ensures input executor is initialized first (for shared PII/toxicity), constructs `OutputRailExecutor`. (COLANG-209)

- [ ] Step 6: Run infrastructure tests:
  ```bash
  pytest tests/guardrails/test_colang_actions.py -k "import or fail_open or rail_instances" -v
  # Expected: PASS
  ```

**Requirements covered:** COLANG-205, COLANG-207, COLANG-209, COLANG-211

---

### Task B-2.2 — Lightweight Deterministic Actions (18 actions)

**Agent input:**
- Design doc Task 2.2 description + Part B Contract entry B.2
- Phase A: `tests/guardrails/test_colang_actions.py` (deterministic section)
- Phase 0: `config/guardrails/actions.py` stubs (signatures)
- FR: COLANG-201, COLANG-203, COLANG-221

**Files:**
- Modify: `config/guardrails/actions.py`

**Must NOT receive:** `tests/guardrails/test_colang_rail_wrappers.py`, `tests/guardrails/test_colang_e2e.py`

- [ ] Step 1: Implement query validation actions. Each returns a `dict` matching its stub signature:
  - `check_query_length`: `len(query.strip())` against bounds 3 and 2000. Empty/whitespace → invalid.
  - `detect_language`: `langdetect.detect(query)`, return `supported = (lang == "en")`.
  - `check_query_clarity`: split on whitespace, check `len(words) < 2` or all words in stopword set.

- [ ] Step 2: Implement session-stateful actions:
  - `check_abuse_pattern`: `time.time()` sliding window on `_abuse_session_state[session_id]`, trim entries older than 60s, flag when count > 20.
  - `check_jailbreak_escalation`: pattern match against 5 regex strings; increment `_jailbreak_session_state[session_id]`; return `"none"` / `"warn"` / `"block"` at thresholds 0 / 1-2 / 3+.

- [ ] Step 3: Implement safety actions:
  - `check_sensitive_topic`: domain-keyed keyword dict for medical/legal/financial; returns domain-appropriate disclaimer text.
  - `check_exfiltration`: 7 regex patterns for bulk extraction; case-insensitive match.
  - `check_role_boundary`: 9 regex patterns for role-play/override; case-insensitive match.

- [ ] Step 4: Implement output quality actions:
  - `check_citations`, `add_citation_reminder`, `check_response_confidence`, `prepend_hedge`, `check_answer_length`, `adjust_answer_length`, `prepend_text`, `prepend_low_confidence_note`.
  - `adjust_answer_length`: truncate to `answer[:5000] + "..."` when `reason == "too long"`.

- [ ] Step 5: Implement stub dialog actions:
  - `handle_follow_up`, `check_topic_drift`, `check_retrieval_results`, `check_source_scope`, `check_query_ambiguity`, `get_knowledge_base_summary`.
  - These can be stubs that return passing results (LLM integration deferred).

- [ ] Step 6: Run deterministic action tests:
  ```bash
  pytest tests/guardrails/test_colang_actions.py -v
  # Expected: ALL PASS (39 total tests; 3 may skip if langdetect unavailable)
  ```

**Requirements covered:** COLANG-201, COLANG-203, COLANG-221, COLANG-301, COLANG-303, COLANG-305, COLANG-307, COLANG-507, COLANG-511, COLANG-601, COLANG-603, COLANG-605, COLANG-607

---

### Task B-2.3 — Executor Bridge Actions (8 actions)

**Agent input:**
- Design doc Task 2.3 description + Part B Contract entry B.3
- Phase A: `tests/guardrails/test_colang_rail_wrappers.py`
- Phase 0: `config/guardrails/actions.py` stubs
- FR: COLANG-201, COLANG-213, COLANG-215, COLANG-217, COLANG-219

**Files:**
- Modify: `config/guardrails/actions.py`

**Must NOT receive:** `tests/guardrails/test_colang_actions.py`, `tests/guardrails/test_colang_e2e.py`

- [ ] Step 1: Implement 5 individual rail-class wrappers as stubs that return passing defaults (`check_injection`, `detect_pii`, `check_toxicity`, `check_topic_safety`, `check_faithfulness`). Full delegation to rail instances is handled via lazy init helpers. (COLANG-201)

- [ ] Step 2: Implement `run_input_rails`:
  - Call `_get_input_executor()` and retrieve merge gate from `_rail_instances`.
  - Run `executor.execute(query)` in `asyncio.run_in_executor(None, ...)` (sync-to-async bridge).
  - Map merge gate decision to `{"action": "pass"|"reject"|"modify", "intent": ..., "redacted_query": ..., "reject_message": ..., "metadata": {}}`.
  - Handle case where merge gate is not yet initialized (return `"pass"`). (COLANG-213)

- [ ] Step 3: Implement `run_output_rails`:
  - Call `_get_output_executor()`, run `executor.execute(answer, [])` in thread executor.
  - Distinguish faithfulness rejection (`RailVerdict.REJECT`) from PII/toxicity modification.
  - Return `{"action": ..., "redacted_answer": ..., "reject_message": ..., "metadata": {}}`. (COLANG-215)

- [ ] Step 4: Implement `rag_retrieve_and_generate`:
  - Read `_rag_chain` module-level reference.
  - If chain is `None`, fail-open returns `{"answer": "", "sources": [], "confidence": 0.0}`.
  - Otherwise call chain retrieval+generation in thread executor. (COLANG-217)

- [ ] Step 5: Implement `set_rag_chain(chain)` module-level injection function.

- [ ] Step 6: Run executor bridge tests:
  ```bash
  pytest tests/guardrails/test_colang_rail_wrappers.py -v
  # Expected: ALL PASS
  ```

**Requirements covered:** COLANG-201, COLANG-213, COLANG-215, COLANG-217, COLANG-219

---

### Task B-3.1 — Query Validation Input Rails (`input_rails.co`)

**Agent input:**
- Design doc Task 3.1 description
- Phase A: `tests/guardrails/test_colang_flows.py` (input rail section)
- FR: COLANG-107, COLANG-301, COLANG-303, COLANG-305, COLANG-307, COLANG-309

**Files:**
- Modify: `config/guardrails/input_rails.co`

**Must NOT receive:** `tests/guardrails/test_colang_rail_wrappers.py`, `tests/guardrails/test_colang_e2e.py`

- [ ] Step 1: Implement 5 input rail flows:

```colang
flow input rails check query length
  $result = await check_query_length(query=$user_message)
  if $result.valid == False
    await bot say $result.reason
    abort

flow input rails check language
  $result = await detect_language(query=$user_message)
  if $result.supported == False
    await bot say "I can only process queries in English. Please rephrase your question."
    abort

flow input rails check query clarity
  $result = await check_query_clarity(query=$user_message)
  if $result.clear == False
    await bot say $result.suggestion
    abort

flow input rails check abuse
  $result = await check_abuse_pattern(query=$user_message)
  if $result.abusive == True
    await bot say "Your query pattern has been flagged. Please ask specific questions one at a time."
    abort

flow input rails run python executor
  $result = await run_input_rails(query=$user_message)
  if $result.action == "reject"
    await bot say $result.reject_message
    abort
  else if $result.action == "modify"
    $user_message = $result.redacted_query
```

- [ ] Step 2: Verify `input_rails.co` contains exactly 5 `flow` definitions (COLANG-107).
- [ ] Step 3: Verify `await` keyword on all action calls; all results assigned to `$variables` (COLANG-109).
- [ ] Step 4: Verify `input rails run python executor` is registered last in `config.yml` (COLANG-309).

```bash
pytest tests/guardrails/test_colang_flows.py -k "input_rails" -v
# Expected: PASS for structure tests
```

**Requirements covered:** COLANG-107, COLANG-109, COLANG-301, COLANG-303, COLANG-305, COLANG-307, COLANG-309

---

### Task B-3.2 — Safety Input Rails (`safety.co`)

**Agent input:**
- Design doc Task 3.2 description
- Phase A: `tests/guardrails/test_colang_flows.py` (safety section)
- FR: COLANG-107, COLANG-601, COLANG-603, COLANG-605, COLANG-607

**Files:**
- Modify: `config/guardrails/safety.co`

- [ ] Step 1: Implement 4 safety input rail flows:

```colang
flow input rails check sensitive topic
  $result = await check_sensitive_topic(query=$user_message)
  if $result.sensitive == True
    $sensitive_disclaimer = $result.disclaimer
# NOTE: NO abort — query proceeds with disclaimer flag set (COLANG-601)

flow input rails check exfiltration
  $result = await check_exfiltration(query=$user_message)
  if $result.attempt == True
    await bot say "I can't fulfill bulk data extraction requests. Please ask specific questions about particular topics."
    abort

flow input rails check role boundary
  $result = await check_role_boundary(query=$user_message)
  if $result.violation == True
    await bot say "I'm a knowledge base search assistant. I can't adopt other roles or ignore my guidelines."
    abort

flow input rails check jailbreak escalation
  $result = await check_jailbreak_escalation(query=$user_message)
  if $result.escalation_level == "warn"
    await bot say "This query has been flagged as a potential policy violation. Please ask a legitimate question."
    abort
  else if $result.escalation_level == "block"
    await bot say "Multiple policy violations detected. Further attempts may result in session restrictions."
    abort
```

- [ ] Step 2: Verify `check sensitive topic` does NOT call `abort` (COLANG-601).
- [ ] Step 3: Verify `safety.co` contains exactly 4 `flow` definitions (COLANG-107).

```bash
pytest tests/guardrails/test_colang_flows.py -k "safety" -v
# Expected: PASS
```

**Requirements covered:** COLANG-107, COLANG-601, COLANG-603, COLANG-605, COLANG-607

---

### Task B-4.1 — Conversation Management Flows (`conversation.co`)

**Agent input:**
- Design doc Task 4.1 description
- Phase A: `tests/guardrails/test_colang_flows.py` (conversation section)
- FR: COLANG-107, COLANG-401, COLANG-403, COLANG-405, COLANG-407, COLANG-409, COLANG-411

**Files:**
- Modify: `config/guardrails/conversation.co`

- [ ] Step 1: Implement 2 intent flows (`user said greeting`, `user said farewell`) — 5+ examples each (COLANG-401).
- [ ] Step 2: Implement `handle greeting` and `handle farewell` standalone dialog handlers (COLANG-403).
- [ ] Step 3: Implement `user said administrative` intent flow and `handle administrative` handler (COLANG-405).
- [ ] Step 4: Implement `user said follow up` intent flow and `handle follow up` handler — calls `abort` when `has_context == False` (COLANG-407).
- [ ] Step 5: Implement `user said off topic` intent flow and `input rails check off topic` rail — calls `abort` (COLANG-409).
- [ ] Step 6: Note: `check topic drift` standalone flow is separate from `input rails check off topic`. `check topic drift` MUST NOT call `abort` (COLANG-411). Add it as the 10th flow.
- [ ] Step 7: Verify `conversation.co` contains exactly 10 `flow` definitions (COLANG-107).

```bash
pytest tests/guardrails/test_colang_flows.py -k "conversation" -v
# Expected: PASS
```

**Requirements covered:** COLANG-107, COLANG-401, COLANG-403, COLANG-405, COLANG-407, COLANG-409, COLANG-411

---

### Task B-4.2 — RAG Dialog Pattern Flows (`dialog_patterns.co`)

**Agent input:**
- Design doc Task 4.2 description
- Phase A: `tests/guardrails/test_colang_flows.py` (dialog patterns section)
- FR: COLANG-107, COLANG-701, COLANG-703, COLANG-705, COLANG-707

**Files:**
- Modify: `config/guardrails/dialog_patterns.co`

- [ ] Step 1: Implement `input rails check ambiguity` — calls `abort` when `ambiguous == True` with `$result.disambiguation_prompt` (COLANG-701).
- [ ] Step 2: Implement `user asked about scope` intent flow with 4+ examples (COLANG-703, COLANG-707).
- [ ] Step 3: Implement `handle scope question` handler — calls `get_knowledge_base_summary()`, responds with `$result.summary` (COLANG-703).
- [ ] Step 4: Implement `user gave positive feedback` and `user gave negative feedback` intent flows — 4+ examples each (COLANG-705, COLANG-707).
- [ ] Step 5: Implement `handle positive feedback` and `handle negative feedback` handlers (COLANG-705).
- [ ] Step 6: Verify `dialog_patterns.co` contains exactly 7 `flow` definitions (COLANG-107).

```bash
pytest tests/guardrails/test_colang_flows.py -k "dialog" -v
# Expected: PASS
```

**Requirements covered:** COLANG-107, COLANG-701, COLANG-703, COLANG-705, COLANG-707

---

### Task B-5.1 — Output Rail Flows (`output_rails.co`)

**Agent input:**
- Design doc Task 5.1 description
- Phase A: `tests/guardrails/test_colang_flows.py` (output rails section)
- FR: COLANG-107, COLANG-501, COLANG-503, COLANG-505, COLANG-507, COLANG-509, COLANG-511, COLANG-513, COLANG-515, COLANG-517

**Files:**
- Modify: `config/guardrails/output_rails.co`

- [ ] Step 1: Implement `output rails run python executor` — first output rail, calls `abort` on reject, updates `$bot_message` on modify (COLANG-501).
- [ ] Step 2: Implement `output rails prepend disclaimer` — checks `$sensitive_disclaimer`, uses two-step pattern (COLANG-503, COLANG-517).
- [ ] Step 3: Implement `output rails check no results` — `abort` on `has_results == False`; prepend low-confidence note and set `$low_confidence_noted = True` when `avg_confidence < 0.3` (COLANG-505).
- [ ] Step 4: Implement `output rails check citations` — append reminder when `has_citations == False`, two-step pattern (COLANG-507, COLANG-517).
- [ ] Step 5: Implement `output rails check confidence` — `abort` on `"none"`; hedge only when `$low_confidence_noted` not set (COLANG-509).
- [ ] Step 6: Implement `output rails check length` — `adjust_answer_length` two-step (COLANG-511, COLANG-517).
- [ ] Step 7: Implement `output rails check scope` — `abort` when `in_scope == False` (COLANG-513).
- [ ] Step 8: Verify all `$bot_message` modifications use `$mod = await ...; $bot_message = $mod.answer` pattern (COLANG-517).
- [ ] Step 9: Verify `output_rails.co` contains exactly 7 `flow` definitions (COLANG-107).

```bash
pytest tests/guardrails/test_colang_flows.py -k "output" -v
# Expected: PASS
```

**Requirements covered:** COLANG-107, COLANG-501, COLANG-503, COLANG-505, COLANG-507, COLANG-509, COLANG-511, COLANG-513, COLANG-515, COLANG-517

---

### Task B-6.1 — GuardrailsRuntime Singleton

**Agent input:**
- Design doc Task 6.1 description + Part B Contract entry B.4
- Phase A: `tests/guardrails/test_colang_e2e.py` (runtime section)
- Phase 0: `src/guardrails/runtime.py` skeleton
- FR: COLANG-801, COLANG-803, COLANG-805, COLANG-807, COLANG-809, COLANG-811

**Files:**
- Modify: `src/guardrails/runtime.py`

**Must NOT receive:** `tests/guardrails/test_colang_actions.py`, `tests/guardrails/test_colang_flows.py`

- [ ] Step 1: Implement `get()` class method with double-checked locking (COLANG-801).
- [ ] Step 2: Implement `initialize(config_dir)`: idempotent, lazy NeMo imports, `RailsConfig.from_path()` → `LLMRails`. Re-raise `SyntaxError` fail-fast; catch all others → `_auto_disabled = True` (COLANG-803, COLANG-805).
- [ ] Step 3: Implement `is_enabled()`: `RAG_NEMO_ENABLED and not _auto_disabled` (COLANG-809).
- [ ] Step 4: Implement `generate_async()`: delegate to `self._rails.generate_async(messages=messages)`. On exception → log warning, `_auto_disabled = True`, return `{"role": "assistant", "content": ""}` (COLANG-807).
- [ ] Step 5: Implement `register_actions()`: iterate `actions.items()`, call `self._rails.register_action(fn, name=name)`. Warn if not initialized (COLANG-811).
- [ ] Step 6: Implement `shutdown()` and `reset()` lifecycle methods.

- [ ] Step 7: Run runtime tests:
  ```bash
  pytest tests/guardrails/test_colang_e2e.py -k "singleton or enabled or disabled or generate" -v
  # Expected: PASS for mocked tests; SKIP for NeMo-requiring tests
  ```

**Requirements covered:** COLANG-801, COLANG-803, COLANG-805, COLANG-807, COLANG-809, COLANG-811

---

### Task B-6.2 — RAG Chain Bridge

**Agent input:**
- Design doc Task 6.2 description
- Phase A: `tests/guardrails/test_colang_e2e.py` (regression section)
- FR: COLANG-807, COLANG-217

**Files:**
- Modify: `src/retrieval/rag_chain.py`

**Must NOT receive:** `tests/guardrails/test_colang_actions.py`, `tests/guardrails/test_colang_flows.py`

- [ ] Step 1: Call `set_rag_chain(self)` during RAG chain initialization to register the chain reference with `rag_retrieve_and_generate`.
- [ ] Step 2: Replace separate `_run_guardrails_input()` / `_run_guardrails_output()` calls with single `GuardrailsRuntime.get().generate_async(messages)`.
- [ ] Step 3: Handle empty-response case (guardrails disabled or auto-disabled) by falling back to the existing non-guardrailed pipeline.
- [ ] Step 4: Register `rag_retrieve_and_generate` action with `GuardrailsRuntime.get().register_actions({"rag_retrieve_and_generate": rag_retrieve_and_generate})`.

- [ ] Step 5: Run regression tests:
  ```bash
  pytest tests/guardrails/test_colang_e2e.py -v
  # Expected: PASS for all regression tests; NeMo e2e tests SKIP if runtime not initialized
  ```

**Requirements covered:** COLANG-807, COLANG-217

---

### Task B-7 — Test Infrastructure and conftest

**Files:**
- Create: `tests/guardrails/conftest.py`

- [ ] Step 1: Add `langchain_core` ghost module cleanup to unblock NeMo imports when `langsmith` pytest plugin is active:

```python
"""Conftest for guardrails tests.

Fixes a broken langchain_core pre-import caused by the langsmith pytest plugin.
"""
import sys

_to_remove = [key for key in sys.modules if key == "langchain_core" or key.startswith("langchain_core.")]
for key in _to_remove:
    mod = sys.modules[key]
    if getattr(mod, "__spec__", None) is None and getattr(mod, "__path__", None) is None:
        del sys.modules[key]
```

- [ ] Step 2: Run full Phase A+B test suite:
  ```bash
  pytest tests/guardrails/ -v --tb=short
  # Expected: 39 PASS, 3 SKIP (langdetect-dependent tests when not installed)
  ```

---

## Phase C — Engineering Guide

Phase C produces the operational engineering guide at `docs/guardrails/COLANG_GUARDRAILS_ENGINEERING_GUIDE.md`. It runs after all Phase B tasks are complete and their tests pass.

> Invoke: `write-engineering-guide` skill for both sub-phases.

---

### Phase C-parallel (one agent per module, all parallel)

Each Phase C-parallel agent receives ONLY its assigned source file(s) and the spec. Must NOT receive other modules' source, any test files, or the design doc.

**Agent isolation contract:**
> The module doc agent receives ONLY its assigned source file(s) and the spec.
> Must NOT receive: other modules' source, any test files, the design doc.

| Agent | Source files | Section covers |
|-------|-------------|---------------|
| C-parallel-1 | `config/guardrails/actions.py` | Action module: all 26 actions, fail-open, session state, lazy init |
| C-parallel-2 | `config/guardrails/input_rails.co`, `config/guardrails/safety.co` | Input rail flows: query validation + safety |
| C-parallel-3 | `config/guardrails/conversation.co`, `config/guardrails/dialog_patterns.co` | Conversation + dialog pattern flows |
| C-parallel-4 | `config/guardrails/output_rails.co` | Output rail flows: quality enforcement |
| C-parallel-5 | `config/guardrails/config.yml` | NeMo config: LLM provider, rail registration, thresholds |
| C-parallel-6 | `src/guardrails/runtime.py` | GuardrailsRuntime: singleton, lifecycle, generate_async() |

Each agent writes one module section covering: Purpose, How it works, Key decisions, Configuration, Error behavior, Test guide.

---

### Phase C-cross (single agent, after all C-parallel complete)

Receives ONLY: all Phase C-parallel module section documents + the companion spec. Must NOT receive any source files directly.

Writes the assembled guide at `docs/guardrails/COLANG_GUARDRAILS_ENGINEERING_GUIDE.md` covering:
- System Overview and Architecture Decisions
- Data Flow (3 scenarios: happy path, rejection, sensitive-topic-with-disclaimer)
- Integration Contracts (RAG chain bridge, Colang-Python action-result protocol)
- Testing Guide (testability map, critical scenarios, boundary conditions)
- Operational Notes (startup, env var configuration, monitoring)
- Known Limitations (in-memory session state, LLM-based stub actions)
- Extension Guide (how to add a new rail, how to add a new action)

---

## Phase D — White-Box Tests (Isolated from Source)

Phase D runs after Phase C-cross completes. All Phase D tasks run in parallel.

> Invoke: `write-module-tests` skill per task.

**Agent isolation contract:**
> The Phase D test agent receives ONLY:
> 1. The module section from the engineering guide (Purpose, Error behavior, Test guide sub-sections)
> 2. The Phase 0 contract files (action stubs, runtime skeleton)
> 3. FR numbers from the spec
>
> Must NOT receive: Any source files, any Phase A test files.

---

### Task D-1 — White-Box Tests: Action Module Coverage

**Agent input (ONLY these):**
- Engineering guide: Action module section (purpose, error behavior, test guide)
- Phase 0: `config/guardrails/actions.py` stubs
- FR: COLANG-205, COLANG-207, COLANG-209, COLANG-221

**Must NOT receive:** `config/guardrails/actions.py` (implementation), Phase A test files

**Files:**
- Create: `tests/guardrails/test_colang_actions_coverage.py`

**Test cases (derived from guide's Error behavior and Test guide sub-sections):**
- `_fail_open` with action that raises `ValueError` — verify default returned, WARNING logged, log excludes `$user_message` content
- `_fail_open` with action that raises `RuntimeError` — same guarantees
- `detect_language` with `langdetect` unavailable (mock import failure) — verify fail-open returns `{"language": "unknown", "supported": True}`
- `check_abuse_pattern` with timestamps exactly at 60s boundary — verify sliding window excludes expired entries
- `check_jailbreak_escalation` with two independent sessions — verify isolation
- `check_jailbreak_escalation` at count == 2 (boundary: still "warn") and count == 3 (boundary: "block")
- `check_query_length` with whitespace-only input (`"   "`) — verify `valid: False`
- `check_sensitive_topic` with query containing two domain keywords — verify first domain wins
- `check_exfiltration` case-insensitivity — `"List All Documents"` matches
- `check_role_boundary` case-insensitivity — `"IGNORE PREVIOUS INSTRUCTIONS"` matches

```bash
pytest tests/guardrails/test_colang_actions_coverage.py -v
# Expected: FAIL (tests are new; run against already-implemented code so may actually PASS)
```

---

### Task D-2 — White-Box Tests: Flow Structure Coverage

**Agent input (ONLY these):**
- Engineering guide: Input/output rail flow sections (purpose, error behavior)
- Phase 0: `config/guardrails/actions.py` stubs
- FR: COLANG-101, COLANG-105, COLANG-107, COLANG-109, COLANG-311, COLANG-515

**Must NOT receive:** Any `.co` source files directly, Phase A test files

**Files:**
- Create: `tests/guardrails/test_colang_flows_coverage.py`

**Test cases:**
- All 5 `.co` files have non-empty `flow` keyword count matching COLANG-107 requirements (parse with regex)
- Total across all files equals 33
- No `.co` file contains the `define` keyword (Colang 1.0 syntax)
- Every `await` call in every `.co` file assigns result to a `$variable`
- `config.yml` `rails.input.flows` and `rails.output.flows` match exact spec ordering
- `input_rails.co` contains no `output rails *` flows; `output_rails.co` contains no `input rails *` flows
- `conversation.co` has exactly one `input rails *` flow (`check off topic`)
- `dialog_patterns.co` has exactly one `input rails *` flow (`check ambiguity`)
- `safety.co` has zero standalone dialog flows (all 4 are `input rails *`)
- `output_rails.co` — `output rails check no results` sets `$low_confidence_noted = True`

```bash
pytest tests/guardrails/test_colang_flows_coverage.py -v
# Expected: FAIL first run (tests are new)
```

---

### Task D-3 — White-Box Tests: GuardrailsRuntime Coverage

**Agent input (ONLY these):**
- Engineering guide: GuardrailsRuntime section (purpose, error behavior, test guide)
- Phase 0: `src/guardrails/runtime.py` skeleton
- FR: COLANG-801, COLANG-803, COLANG-805, COLANG-807, COLANG-809, COLANG-811

**Must NOT receive:** `src/guardrails/runtime.py` (implementation), Phase A test files

**Files:**
- Create: `tests/guardrails/test_runtime_coverage.py`

**Test cases:**
- Concurrent `get()` calls from 10 threads all receive the same instance (thread-safety)
- `initialize()` called twice — verify `_rails.generate_async` not called twice (idempotency)
- Auto-disable after `generate_async()` exception: subsequent `is_enabled()` returns `False` even if `RAG_NEMO_ENABLED=true`
- `register_actions()` before `initialize()` — verify WARNING logged, no exception
- `reset()` clears `_auto_disabled` flag
- `shutdown()` sets `_initialized = False` and `_rails = None`
- `is_enabled()` with `RAG_NEMO_ENABLED=true` AND `_auto_disabled=True` → returns `False`

```bash
pytest tests/guardrails/test_runtime_coverage.py -v
# Expected: FAIL first run
```

---

## Phase E — Full Suite Verification

After ALL Phase D tasks complete:

- [ ] Run full guardrails test suite:
  ```bash
  pytest tests/guardrails/ -v --tb=short
  ```
  Expected: ALL Phase A tests PASS + ALL Phase D tests PASS (39 pass, 3 skip for NeMo-requiring tests when runtime not initialized)

- [ ] Verify no regressions in the broader test suite:
  ```bash
  pytest tests/ -v --tb=short --ignore=tests/guardrails/test_colang_flows.py
  # (skip NeMo integration tests that require the live runtime)
  ```

- [ ] If any Phase A tests fail: diagnose which spec requirement is not met and fix in Phase B.

- [ ] If any Phase D tests fail: diagnose against the engineering guide's Error behavior section and fix the gap (either the test's expectation or a genuine implementation bug).

- [ ] Commit:
  ```bash
  git add tests/guardrails/
  git commit -m "test: add Phase D white-box coverage tests for Colang guardrails"
  ```

---

## Appendix: COLANG-xxx → Phase Coverage Map

| Requirement ID | Phase A | Phase B | Phase D |
|---------------|---------|---------|---------|
| COLANG-101 | A-3.1 | B-1 | D-2 |
| COLANG-103 | A-3.1 | B-1 | D-2 |
| COLANG-105 | A-3.1, A-3.2, A-4.1, A-4.2, A-5.1 | B-3.1, B-3.2, B-4.1, B-4.2, B-5.1 | D-2 |
| COLANG-107 | A-3.1, A-3.2, A-4.1, A-4.2, A-5.1 | B-3.1, B-3.2, B-4.1, B-4.2, B-5.1 | D-2 |
| COLANG-109 | A-3.1 | B-3.1 | D-2 |
| COLANG-111 | A-3.1 | B-1 | D-2 |
| COLANG-201 | A-2.2, A-2.3 | B-2.2, B-2.3 | D-1 |
| COLANG-203 | A-2.2 | B-2.2 | D-1 |
| COLANG-205 | A-2.1 | B-2.1 | D-1 |
| COLANG-207 | A-2.1, A-6.1 | B-2.1 | D-1 |
| COLANG-209 | A-2.1 | B-2.1 | D-1 |
| COLANG-211 | A-2.1 | B-2.1 | D-1 |
| COLANG-213 | A-2.3 | B-2.3 | D-1 |
| COLANG-215 | A-2.3 | B-2.3 | D-1 |
| COLANG-217 | A-2.3 | B-2.3, B-6.2 | D-1 |
| COLANG-219 | A-2.3 | B-2.3 | D-1 |
| COLANG-221 | A-2.2 | B-2.2 | D-1 |
| COLANG-301 | A-3.1 | B-3.1 | D-2 |
| COLANG-303 | A-3.1, A-2.2 | B-2.2, B-3.1 | D-1 |
| COLANG-305 | A-2.2, A-3.1 | B-2.2, B-3.1 | D-1 |
| COLANG-307 | A-2.2, A-3.1 | B-2.2, B-3.1 | D-1 |
| COLANG-309 | A-3.1 | B-3.1 | D-2 |
| COLANG-311 | A-3.1 | B-1 | D-2 |
| COLANG-401 | A-4.1 | B-4.1 | D-2 |
| COLANG-403 | A-4.1 | B-4.1 | D-2 |
| COLANG-405 | A-4.1 | B-4.1 | D-2 |
| COLANG-407 | A-4.1 | B-4.1 | D-2 |
| COLANG-409 | A-4.1 | B-4.1 | D-2 |
| COLANG-411 | A-4.1 | B-4.1 | D-2 |
| COLANG-501 | A-5.1 | B-5.1 | D-2 |
| COLANG-503 | A-5.1 | B-5.1 | D-2 |
| COLANG-505 | A-5.1 | B-5.1 | D-2, D-3 |
| COLANG-507 | A-5.1, A-2.2 | B-2.2, B-5.1 | D-1, D-2 |
| COLANG-509 | A-5.1 | B-5.1 | D-2 |
| COLANG-511 | A-5.1, A-2.2 | B-2.2, B-5.1 | D-1, D-2 |
| COLANG-513 | A-5.1 | B-5.1 | D-2 |
| COLANG-515 | A-5.1 | B-1 | D-2 |
| COLANG-517 | A-5.1 | B-5.1 | D-2 |
| COLANG-601 | A-3.2, A-2.2 | B-2.2, B-3.2 | D-1, D-2 |
| COLANG-603 | A-3.2, A-2.2 | B-2.2, B-3.2 | D-1, D-2 |
| COLANG-605 | A-3.2, A-2.2 | B-2.2, B-3.2 | D-1, D-2 |
| COLANG-607 | A-3.2, A-2.2 | B-2.2, B-3.2 | D-1, D-2 |
| COLANG-701 | A-4.2 | B-4.2 | D-2 |
| COLANG-703 | A-4.2 | B-4.2 | D-2 |
| COLANG-705 | A-4.2 | B-4.2 | D-2 |
| COLANG-707 | A-4.2 | B-4.2 | D-2 |
| COLANG-801 | A-6.1 | B-6.1 | D-3 |
| COLANG-803 | A-6.1 | B-6.1 | D-3 |
| COLANG-805 | A-6.1 | B-6.1 | D-3 |
| COLANG-807 | A-6.1 | B-6.1, B-6.2 | D-3 |
| COLANG-809 | A-6.1 | B-6.1 | D-3 |
| COLANG-811 | A-6.1 | B-6.1 | D-3 |
| COLANG-813 | A-3.1 | B-1 | D-2 |
| COLANG-815 | A-3.1, A-5.1 | B-1 | D-2 |
| COLANG-901 | A-2.2 | B-2.2 | D-1 |
| COLANG-903 | A-6.1 | B-6.1 | D-3 |
| COLANG-905 | A-6.1 | B-7 | D-1, D-2, D-3 |
| COLANG-907 | A-6.1 | B-6.1 | D-3 |
| COLANG-909 | A-2.2 | B-2.2 | D-1 |
| COLANG-911 | A-2.1 | B-2.1 | D-1 |
