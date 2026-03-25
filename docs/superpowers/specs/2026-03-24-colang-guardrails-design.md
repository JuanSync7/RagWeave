# Colang 2.0 Guardrails — Design Specification

**Date:** 2026-03-24
**Status:** Approved
**Scope:** Proper Colang 2.0 implementation for NeMo Guardrails in the RAG retrieval pipeline

---

## Overview

Replace the demo-quality Colang 1.0 intent definitions with a full Colang 2.0 implementation covering five categories of RAG-specific guardrail flows. Colang acts as a **complementary declarative policy layer** alongside the existing Python executor orchestration — it does not replace the Python rails but adds structured dialog management, policy enforcement, and conversational UX on top.

### Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Colang version | **2.0** | `nemoguardrails>=0.21.0` supports it; 2.0 has parallel flows, event-driven architecture, custom action registration |
| Integration model | **Complement** | Keep Python executor (parallel execution, timeouts, merge gate) intact; Colang handles intent/dialog/policy |
| Python interaction | **Action-result pattern** | Colang calls registered actions, branches on results; Python computes, Colang decides |
| File organization | **Modular per-category** | Separate `.co` files per flow category, mirroring existing guardrails code structure |
| Documentation | **General guide + project guide** | Combined document in `docs/guardrails/COLANG_DESIGN_GUIDE.md` |

---

## Section 1: File Structure & Syntax Migration

### Migration from Colang 1.0 to 2.0

The existing `intents.co` uses Colang 1.0 syntax (`define user/bot/flow`). All definitions will be rewritten using Colang 2.0 syntax:

```colang
# Colang 1.0 (current)
define user greeting
  "hello"
  "hi there"

define flow check intent
  user ...
  if user intent is greeting
    bot greeting response

# Colang 2.0 (target)
flow user said greeting
  user said "hello" or user said "hi there" or user said "hey"

flow greeting
  user said greeting
  bot say "Hello! I'm here to help you search the knowledge base."
```

### File Layout

```
config/guardrails/
├── config.yml            # NeMo runtime config, model settings, flow registration
├── input_rails.co        # Query validation: length, language, reformulation, abuse detection
├── conversation.co       # Multi-turn: follow-ups, topic tracking, greetings/farewells, off-topic
├── output_rails.co       # Response quality: citations, confidence routing, length, scope
├── safety.co             # Compliance: sensitive topics, exfiltration, role boundary, jailbreak escalation
├── dialog_patterns.co    # RAG dialog: no-results, disambiguation, scope explanation, feedback
└── actions.py            # Python action wrappers — NeMo auto-discovers this file
```

| File | Purpose | Rail flows | Dialog flows |
|------|---------|------------|--------------|
| `input_rails.co` | Query validation + Python executor bridge | 5 | 0 |
| `conversation.co` | Multi-turn: greetings, farewells, follow-ups, off-topic, topic drift | 1 (`check off topic`) | 9 (intent matchers + handlers + `check topic drift`) |
| `output_rails.co` | Response quality + Python executor bridge + no-results + disclaimer | 7 | 0 |
| `safety.co` | Compliance: exfiltration, role boundary, jailbreak escalation, sensitive topic | 4 | 0 |
| `dialog_patterns.co` | RAG dialog: disambiguation, scope explanation, feedback | 1 (`check ambiguity`) | 6 (intent matchers + handlers) |
| `actions.py` | Registered Python action wrappers | — | 26 actions |

**Rail flows** follow the `input rails *` / `output rails *` naming convention and are registered in `config.yml`.
**Dialog flows** are standalone flows auto-discovered by NeMo from `.co` files — they match by intent before the rail pipeline.

The existing `intents.co` will be **replaced** — intent definitions are absorbed into `conversation.co` (greetings, farewells, admin) and `input_rails.co` (off-topic routing).

### Colang 2.0 Syntax Note

The flow examples in this spec use Colang 2.0 intent syntax (`flow user said greeting`, `user said "hello" or user said "hi there"`). The exact syntax will be validated during implementation against the installed `nemoguardrails` parser (≥0.21.0). If the parser requires event-matching syntax (e.g., `match UtteranceUserAction.Finished(final_transcript="hello")`), the flow bodies will be adapted while preserving the same semantics. The spec defines **intent** and **behavior**, not exact parser tokens.

---

## Section 2: Python Action Registration (`actions.py`)

NeMo auto-discovers `actions.py` in the config directory. Each action is a thin wrapper calling into existing rail classes. **All** actions used by Colang flows are declared here.

### 2.1 Actions Wrapping Existing Rail Classes

These actions delegate to existing Python rail classes in `src/guardrails/`:

```python
# config/guardrails/actions.py
from nemoguardrails.actions import action

@action()
async def check_injection(query: str) -> dict:
    """Wraps InjectionDetector — returns {verdict: str, method: str, confidence: float}"""

@action()
async def detect_pii(text: str, direction: str = "input") -> dict:
    """Wraps PIIDetector — returns {found: bool, entities: list, redacted_text: str}"""

@action()
async def check_toxicity(text: str, direction: str = "input") -> dict:
    """Wraps ToxicityFilter — returns {verdict: str, score: float}"""

@action()
async def check_topic_safety(query: str) -> dict:
    """Wraps TopicSafetyChecker — returns {on_topic: bool, confidence: float}"""

@action()
async def check_faithfulness(answer: str, context_chunks: list) -> dict:
    """Wraps FaithfulnessChecker — returns {verdict: str, score: float, claim_scores: list}"""

@action()
async def run_input_rails(query: str) -> dict:
    """Wraps InputRailExecutor — runs all Python input rails (injection, PII, toxicity, topic safety)
    in parallel. Returns {action: str, intent: str, redacted_query: str, metadata: dict}"""

@action()
async def run_output_rails(answer: str) -> dict:
    """Wraps OutputRailExecutor — runs all Python output rails (faithfulness, PII, toxicity).
    Returns {action: str, redacted_answer: str, metadata: dict}"""

@action()
async def rag_retrieve_and_generate(query: str) -> dict:
    """Calls the RAG retrieval+generation pipeline (replaces NeMo's default LLM call).
    Returns {answer: str, sources: list, confidence: float}"""
```

### 2.2 New Lightweight Actions (No Existing Rail Class)

These are new purpose-built actions for Colang policy flows. They are **deterministic or rule-based** (no LLM calls) unless noted:

```python
@action()
async def check_query_length(query: str) -> dict:
    """Min 3 chars, max 2000 chars. Returns {valid: bool, length: int, reason: str}"""

@action()
async def detect_language(query: str) -> dict:
    """Uses langdetect library. Returns {language: str, supported: bool}"""

@action()
async def check_query_clarity(query: str) -> dict:
    """Heuristic: word count < 3, all stopwords, no nouns. Returns {clear: bool, suggestion: str}"""

@action()
async def check_abuse_pattern(query: str) -> dict:
    """Tracks query rate per session via in-memory counter. Returns {abusive: bool, reason: str}"""

@action()
async def handle_follow_up(query: str) -> dict:
    """Checks NeMo conversation context for prior Q&A. Returns {has_context: bool, augmented_query: str}"""

@action()
async def check_topic_drift(query: str) -> dict:
    """Compares query embedding similarity to prior turn. Returns {drifted: bool}"""

@action()
async def check_citations(answer: str) -> dict:
    """Regex check for [Source: ...] or [1] patterns. Returns {has_citations: bool}"""

@action()
async def add_citation_reminder(answer: str) -> dict:
    """Appends 'Note: sources available in metadata.' Returns {answer: str}"""

@action()
async def check_response_confidence(answer: str) -> dict:
    """Reads retrieval confidence from NeMo context. Returns {confidence: str}  # 'none'|'low'|'high'"""

@action()
async def prepend_hedge(answer: str) -> dict:
    """Prepends 'Based on limited information: ...' Returns {answer: str}"""

@action()
async def check_answer_length(answer: str) -> dict:
    """Min 20 chars, max 5000 chars. Returns {valid: bool, reason: str}"""

@action()
async def adjust_answer_length(answer: str, reason: str) -> dict:
    """Truncates with '...' or flags terse answer. Returns {answer: str}"""

@action()
async def check_source_scope(answer: str) -> dict:
    """LLM-based: does answer stay within retrieved context? Returns {in_scope: bool}"""

@action()
async def check_sensitive_topic(query: str) -> dict:
    """Keyword + regex for medical/legal/financial terms. Returns {sensitive: bool, disclaimer: str, domain: str}"""

@action()
async def check_exfiltration(query: str) -> dict:
    """Regex for bulk extraction patterns. Returns {attempt: bool, pattern: str}"""

@action()
async def check_role_boundary(query: str) -> dict:
    """Regex for role-play/instruction-override patterns. Returns {violation: bool}"""

@action()
async def check_jailbreak_escalation(query: str) -> dict:
    """Tracks violation count per session (in-memory dict keyed by session_id from NeMo context).
    Thresholds: 1-2 violations → 'warn', 3+ → 'block'.
    Returns {escalation_level: str}  # 'none'|'warn'|'block'"""

@action()
async def check_retrieval_results(answer: str) -> dict:
    """Reads retrieval metadata from NeMo context (set by rag_retrieve_and_generate).
    Returns {has_results: bool, count: int, avg_confidence: float}"""

@action()
async def prepend_low_confidence_note(answer: str) -> dict:
    """Prepends 'Note: The following answer is based on limited matches.' Returns {answer: str}"""

@action()
async def check_query_ambiguity(query: str) -> dict:
    """LLM-based: does query have multiple valid interpretations? Returns {ambiguous: bool, disambiguation_prompt: str}"""

@action()
async def get_knowledge_base_summary() -> dict:
    """Returns static summary from config. Returns {summary: str}"""

@action()
async def prepend_text(text: str, answer: str) -> dict:
    """Prepends text (e.g., disclaimer) to answer. Returns {answer: str}"""
```

### 2.3 Design Principles

- Actions return **dicts** (not dataclasses) because NeMo serializes action results into Colang context variables.
- Actions wrapping existing rail classes delegate to singleton instances — **no logic duplication**.
- Actions respect existing env var toggles (e.g., if `RAG_NEMO_INJECTION_ENABLED=false`, `check_injection` returns `{verdict: "pass"}` immediately).
- `actions.py` lives in `config/guardrails/` (NeMo convention) but imports from `src/guardrails/`.
- **Lazy initialization:** Rail class instances are created on first action call, not at module import time. This avoids import-time failures when optional dependencies (spacy models, YAML patterns) are unavailable.
- **Fail-open on action errors:** If any action raises an exception, it catches the error, logs a warning, and returns a passing/no-op result (e.g., `{verdict: "pass"}`, `{valid: True}`). This matches the existing `GuardrailsRuntime` fail-open philosophy.
- **Session state:** Actions needing per-session state (`check_abuse_pattern`, `check_jailbreak_escalation`) use an in-memory dict keyed by `$session_id` from NeMo's context. Session state is not persisted across worker restarts.

---

## Section 3: Input Rails (`input_rails.co`)

Four flows that run before retrieval:

### 3.1 Query Length Enforcement

```colang
flow input rails check query length
  $result = execute check_query_length(query=$user_message)
  if $result.valid == False
    bot say $result.reason
    abort
```

### 3.2 Language Detection

```colang
flow input rails check language
  $result = execute detect_language(query=$user_message)
  if $result.supported == False
    bot say "I can only process queries in English. Please rephrase your question."
    abort
```

### 3.3 Query Reformulation Hints

Detects vague/underspecified queries and prompts for clarification.

```colang
flow input rails check query clarity
  $result = execute check_query_clarity(query=$user_message)
  if $result.clear == False
    bot say $result.suggestion
    abort
```

### 3.4 Multi-Query Abuse Detection

Detects enumeration/data harvesting patterns.

```colang
flow input rails check abuse
  $result = execute check_abuse_pattern(query=$user_message)
  if $result.abusive == True
    bot say "Your query pattern has been flagged. Please ask specific questions one at a time."
    abort
```

### 3.5 Python Input Executor Bridge (MUST be last)

Runs the Python `InputRailExecutor` (injection 4-layer, PII, toxicity, topic safety) + `RailMergeGate` as the last input rail.

```colang
flow input rails run python executor
  $result = execute run_input_rails(query=$user_message)
  if $result.action == "reject"
    bot say $result.reject_message
    abort
  else if $result.action == "modify"
    $user_message = $result.redacted_query
```

### Registration

See Section 8 `config.yml` for the full input rails registration. Order matters: Colang policy checks run first (fast, deterministic), Python executor runs last (heavy compute).

Flows use NeMo's `input rails` naming convention — NeMo auto-wires them in registered order. `abort` stops the pipeline and returns the bot message.

---

## Section 4: Conversation Management (`conversation.co`)

Five flows for multi-turn RAG dialog:

### 4.1 Greeting/Farewell (Migrated from 1.0)

```colang
flow user said greeting
  user said "hello" or user said "hi there" or user said "hey"
    or user said "good morning" or user said "greetings"

flow user said farewell
  user said "goodbye" or user said "bye" or user said "see you later"
    or user said "thanks, bye" or user said "that's all"

flow handle greeting
  user said greeting
  bot say "Hello! I'm here to help you search the knowledge base. What would you like to know?"

flow handle farewell
  user said farewell
  bot say "Goodbye! Feel free to return if you have more questions."
```

### 4.2 Administrative/Help Queries

```colang
flow user said administrative
  user said "help" or user said "what can you do"
    or user said "how do I use this" or user said "what are your capabilities"

flow handle administrative
  user said administrative
  bot say "I can search the knowledge base to answer your questions. Just type your question in natural language and I'll find relevant information from the available documents."
```

### 4.3 Follow-Up Detection

Recognizes continuation queries and augments context.

```colang
flow user said follow up
  user said "tell me more" or user said "can you elaborate"
    or user said "what else" or user said "go on"
    or user said "more details" or user said "explain further"

flow handle follow up
  user said follow up
  $result = execute handle_follow_up(query=$user_message)
  if $result.has_context == True
    $user_message = $result.augmented_query
  else
    bot say "Could you clarify what you'd like to know more about? Please restate your question."
    abort
```

### 4.4 Topic Drift Detection

Sets a context flag when the conversation jumps domains, so the retrieval pipeline clears prior context and searches fresh. This is **not** an input rail — it is a standalone dialog flow that sets context state.

```colang
flow check topic drift
  user said something
  $result = execute check_topic_drift(query=$user_message)
  if $result.drifted == True
    $topic_drifted = True
    # Context flag consumed by rag_retrieve_and_generate action
    # to clear conversation context and search fresh
```

### 4.5 Off-Topic Routing (Migrated from 1.0, Enhanced)

```colang
flow user said off topic
  user said "what's the weather" or user said "tell me a joke"
    or user said "who won the game" or user said "play some music"
    or user said "what's the stock price"

flow input rails check off topic
  user said off topic
  bot say "I'm designed to help you find information in the knowledge base. I can't help with that topic, but feel free to ask me a question about the documents I have access to."
  abort
```

**Design note:** Greeting, farewell, administrative, follow-up, and topic drift are standalone dialog flows (matched by intent before the rail pipeline or setting context flags). Off-topic is the only input rail in this file — it needs to block retrieval via `abort`.

---

## Section 5: Output Rails (`output_rails.co`)

Seven flows that run after generation, before returning the response. Includes the Python executor bridge (first), disclaimer prepending, no-results handling, and policy checks.

### 5.1 Python Output Executor Bridge (MUST be first)

Runs the Python `OutputRailExecutor` (faithfulness, PII, toxicity) as the first output rail.

```colang
flow output rails run python executor
  $result = execute run_output_rails(answer=$bot_message)
  if $result.action == "reject"
    bot say $result.reject_message
    abort
  else if $result.action == "modify"
    $bot_message = $result.redacted_answer
```

### 5.2 Sensitive Topic Disclaimer

Prepends disclaimer if `$sensitive_disclaimer` was set by the input rail in `safety.co`.

```colang
flow output rails prepend disclaimer
  if $sensitive_disclaimer
    $result = execute prepend_text(text=$sensitive_disclaimer, answer=$bot_message)
    $bot_message = $result.answer
```

### 5.3 No-Results Handling

Graceful response when retrieval returned nothing useful.

```colang
flow output rails check no results
  $result = execute check_retrieval_results(answer=$bot_message)
  if $result.has_results == False
    bot say "I couldn't find relevant documents to answer your question. Try rephrasing with different keywords, or ask about a different aspect of the topic."
    abort
  else if $result.avg_confidence < 0.3
    $mod = execute prepend_low_confidence_note(answer=$bot_message)
    $bot_message = $mod.answer
    $low_confidence_noted = True
```

### 5.4 Citation Enforcement

Ensures responses reference source documents.

```colang
flow output rails check citations
  $result = execute check_citations(answer=$bot_message)
  if $result.has_citations == False
    $mod = execute add_citation_reminder(answer=$bot_message)
    $bot_message = $mod.answer
```

### 5.5 Confidence-Based Routing

Hedges or refuses when retrieval confidence is low. Skips hedging if `$low_confidence_noted` was already set by the no-results flow (5.3) to avoid double-hedging.

```colang
flow output rails check confidence
  $result = execute check_response_confidence(answer=$bot_message)
  if $result.confidence == "none"
    bot say "I couldn't find relevant information in the knowledge base to answer that question."
    abort
  else if $result.confidence == "low" and not $low_confidence_noted
    $mod = execute prepend_hedge(answer=$bot_message)
    $bot_message = $mod.answer
```

### 5.6 Answer Length Governance

Prevents excessively verbose or terse responses.

```colang
flow output rails check length
  $result = execute check_answer_length(answer=$bot_message)
  if $result.valid == False
    $mod = execute adjust_answer_length(answer=$bot_message, reason=$result.reason)
    $bot_message = $mod.answer
```

### 5.7 Source Scope Enforcement

Strips claims outside the knowledge base.

```colang
flow output rails check scope
  $result = execute check_source_scope(answer=$bot_message)
  if $result.in_scope == False
    bot say "I can only provide answers based on the documents in the knowledge base. Your question may be outside the scope of available information."
    abort
```

### Registration

See Section 8 `config.yml` for the full output rails registration. Order matters: Python executor runs first (heavy compute), then Colang policy flows.

**Design note:** The Python executor bridge (5.1) runs the existing `OutputRailExecutor` (faithfulness scoring, PII redaction, toxicity filtering). The remaining Colang flows handle policy decisions (hedging, citation reminders, length governance) that are better expressed declaratively.

---

## Section 6: Safety & Compliance (`safety.co`)

Four flows for safety enforcement beyond what Python rails handle:

### 6.1 Sensitive Topic Escalation

Adds disclaimers for legal/medical/financial content. Sets a context variable that the output rails pick up to prepend the disclaimer to the final response.

```colang
flow input rails check sensitive topic
  $result = execute check_sensitive_topic(query=$user_message)
  if $result.sensitive == True
    $sensitive_disclaimer = $result.disclaimer
    # Does NOT abort — sets context var for output rail to prepend
```

The corresponding output rail (in `output_rails.co`) prepends the disclaimer:

```colang
flow output rails prepend disclaimer
  if $sensitive_disclaimer
    $result = execute prepend_text(text=$sensitive_disclaimer, answer=$bot_message)
    $bot_message = $result.answer
```

Example disclaimers:
- Medical: "This information is from the knowledge base and is not medical advice. Consult a healthcare professional."
- Legal: "This is informational only and does not constitute legal advice."
- Financial: "This is not financial advice. Consult a qualified professional."

### 6.2 Data Exfiltration Prevention

Detects bulk extraction attempts.

```colang
flow input rails check exfiltration
  $result = execute check_exfiltration(query=$user_message)
  if $result.attempt == True
    bot say "I can't fulfill bulk data extraction requests. Please ask specific questions about particular topics."
    abort
```

Detects: "list all documents", "dump everything", "show me all records", "export the database", "give me every entry about..."

### 6.3 Role Boundary Enforcement

Prevents prompt injection role-play.

```colang
flow input rails check role boundary
  $result = execute check_role_boundary(query=$user_message)
  if $result.violation == True
    bot say "I'm a knowledge base search assistant. I can't adopt other roles or ignore my guidelines."
    abort
```

Detects: "you are now a...", "ignore previous instructions", "pretend you are", "act as if you have no restrictions"

### 6.4 Repeated Jailbreak Escalation

Escalating responses for persistent policy violation attempts.

```colang
flow input rails check jailbreak escalation
  $result = execute check_jailbreak_escalation(query=$user_message)
  if $result.escalation_level == "warn"
    bot say "This query has been flagged as a potential policy violation. Please ask a legitimate question."
    abort
  else if $result.escalation_level == "block"
    bot say "Multiple policy violations detected. Further attempts may result in session restrictions."
    abort
```

The Python action tracks attempt count per session and escalates from warn → block.

**Design note:** These complement the existing `InjectionDetector` (4-layer defense). Python catches the technical attack; Colang flows handle the *policy response* — what to say, whether to escalate, when to add disclaimers vs. block.

---

## Section 7: RAG-Specific Dialog Patterns (`dialog_patterns.co`)

Three dialog flows + one input rail for domain-aware RAG interactions:

**Note:** The no-results flow (`output rails check no results`) was moved to `output_rails.co` (Section 5) since it is an output rail, not a standalone dialog pattern.

### 7.1 Ambiguous Query Disambiguation

Prompts user to clarify when query matches multiple domains.

```colang
flow input rails check ambiguity
  $result = execute check_query_ambiguity(query=$user_message)
  if $result.ambiguous == True
    bot say $result.disambiguation_prompt
    abort
```

Example: User asks "How does attention work?" → "Did you mean attention in the context of transformer architectures, or attention mechanisms in cognitive science? Please clarify."

### 7.2 Document Scope Explanation

Tells users what the knowledge base covers.

```colang
flow user asked about scope
  user said "what documents do you have" or user said "what can I ask about"
    or user said "what topics do you cover" or user said "what's in the knowledge base"

flow handle scope question
  user asked about scope
  $result = execute get_knowledge_base_summary()
  bot say $result.summary
```

### 7.3 Feedback Collection

Captures user satisfaction signals.

```colang
flow user gave positive feedback
  user said "thanks" or user said "that's helpful" or user said "great answer"
    or user said "perfect" or user said "exactly what I needed"

flow user gave negative feedback
  user said "that's wrong" or user said "not what I asked"
    or user said "that doesn't help" or user said "incorrect"

flow handle positive feedback
  user gave positive feedback
  bot say "Glad that was helpful! Feel free to ask another question."

flow handle negative feedback
  user gave negative feedback
  bot say "I'm sorry that wasn't helpful. Could you rephrase your question or provide more context so I can search more effectively?"
```

**Design note:** `no_results` and `ambiguity` are registered as rails (they gate the pipeline). Scope explanation and feedback are standalone dialog flows — they handle conversational side-channels without blocking retrieval.

---

## Section 8: Config & Runtime Integration

### Updated `config.yml`

```yaml
models:
  - type: main
    engine: ollama
    model: ${RAG_OLLAMA_MODEL:-qwen2.5:3b}
    parameters:
      base_url: ${RAG_OLLAMA_URL:-http://localhost:11434}
      temperature: 0.1

rails:
  input:
    flows:
      # Query validation (Colang policy)
      - input rails check query length
      - input rails check language
      - input rails check query clarity
      - input rails check abuse
      # Safety (Colang policy)
      - input rails check exfiltration
      - input rails check role boundary
      - input rails check jailbreak escalation
      - input rails check sensitive topic
      # Conversation (Colang policy)
      - input rails check off topic
      # Dialog (Colang policy)
      - input rails check ambiguity
      # Python executor (heavy compute — MUST be last)
      - input rails run python executor
  output:
    flows:
      # Python executor (heavy compute — MUST be first)
      - output rails run python executor
      # Sensitive topic disclaimer (reads $sensitive_disclaimer context var)
      - output rails prepend disclaimer
      # Response quality (Colang policy)
      - output rails check no results
      - output rails check confidence
      - output rails check citations
      - output rails check length
      - output rails check scope

  config:
    jailbreak_detection:
      length_per_perplexity_threshold: 89.79
      prefix_suffix_perplexity_threshold: 1845.65
    sensitive_data_detection:
      input:
        entities: [EMAIL_ADDRESS, PHONE_NUMBER, US_SSN, CREDIT_CARD, PERSON]
        score_threshold: 0.4
      output:
        entities: [EMAIL_ADDRESS, PHONE_NUMBER, US_SSN, CREDIT_CARD, PERSON]
        score_threshold: 0.4
```

### Execution Order — Single `generate_async()` Architecture

NeMo's `generate_async()` runs the full pipeline (input rails → generation → output rails) in a **single call**. The Python `InputRailExecutor`, `OutputRailExecutor`, and the RAG retrieval pipeline are registered as NeMo actions called from within Colang flows — not as separate pipeline stages outside NeMo.

```
NeMo generate_async() [single call]
    │
    ├── Input Rails (Colang, in registered order):
    │   ├── check query length
    │   ├── check language
    │   ├── check query clarity
    │   ├── check abuse
    │   ├── check exfiltration
    │   ├── check role boundary
    │   ├── check jailbreak escalation
    │   ├── check sensitive topic (sets $sensitive_disclaimer)
    │   ├── check off topic
    │   ├── check ambiguity
    │   └── run python input rails ← calls InputRailExecutor + RailMergeGate as action
    │
    ├── Generation (custom action replaces NeMo's default LLM call):
    │   └── rag_retrieve_and_generate() ← calls RAG retrieval pipeline
    │
    └── Output Rails (Colang, in registered order):
        ├── run python output rails ← calls OutputRailExecutor as action
        ├── prepend disclaimer (if $sensitive_disclaimer set)
        ├── check no results
        ├── check confidence
        ├── check citations
        ├── check length
        └── check scope
```

### Key Integration Changes

**1. Custom generation action:** Register `rag_retrieve_and_generate` as the action that replaces NeMo's default LLM call. This action calls the existing retrieval pipeline (embedding → search → reranking → LLM generation) and sets retrieval metadata in NeMo context for downstream output rails.

**2. Python executor as last input rail / first output rail:** The Colang flows `input rails run python executor` and `output rails run python executor` call the existing `InputRailExecutor` and `OutputRailExecutor` as NeMo actions. These are defined in `input_rails.co` and `output_rails.co` respectively:

```colang
# Last input rail — runs Python executor (injection, PII, toxicity, topic safety)
flow input rails run python executor
  $result = execute run_input_rails(query=$user_message)
  if $result.action == "reject"
    bot say $result.reject_message
    abort
  else if $result.action == "modify"
    $user_message = $result.redacted_query

# First output rail — runs Python executor (faithfulness, PII, toxicity)
flow output rails run python executor
  $result = execute run_output_rails(answer=$bot_message)
  if $result.action == "reject"
    bot say $result.reject_message
    abort
  else if $result.action == "modify"
    $bot_message = $result.redacted_answer
```

**3. `rag_chain.py` simplification:** The `_run_guardrails_input()` and `_run_guardrails_output()` methods in `rag_chain.py` are replaced by a single `generate_async()` call. The `GuardrailsRuntime` becomes the sole entry point. The `InputRailExecutor` and `OutputRailExecutor` are still instantiated, but invoked by the NeMo action wrappers rather than directly by `rag_chain.py`.

### Standalone Dialog Flows (Not Registered as Rails)

NeMo auto-discovers all `.co` files in the config directory. Flows that do **not** follow the `input rails *` or `output rails *` naming convention are treated as standalone dialog flows — they are matched by NeMo's intent engine before the rail pipeline runs. These include:

- `handle greeting`, `handle farewell`, `handle administrative` (conversation.co)
- `handle follow up`, `check topic drift` (conversation.co)
- `handle scope question`, `handle positive feedback`, `handle negative feedback` (dialog_patterns.co)

### Migration of Existing NeMo Built-In Flows

The current `config.yml` registers NeMo built-in flows:
- **Input:** `check jailbreak`, `jailbreak detection heuristics` — these are **intentionally removed** because the Python `InjectionDetector` provides a superior 4-layer defense (regex + perplexity heuristics + model classifier + LLM semantic check). The built-in NeMo jailbreak flows only use perplexity heuristics.
- **Output:** `check faithfulness`, `self check facts`, `self check output` — these are **intentionally removed** because the Python `FaithfulnessChecker` and `ToxicityFilter` provide richer analysis (per-claim scoring, entity hallucination detection). The built-in NeMo output flows are simpler single-prompt checks.

Both sets of capabilities are preserved through the `run_input_rails` and `run_output_rails` Colang actions, which call the full Python executor stack.

### Configuration

**No new env vars needed.** The existing `RAG_NEMO_ENABLED` master toggle controls the entire Colang+Python stack. Individual Python rail toggles (e.g., `RAG_NEMO_INJECTION_ENABLED`) continue to work — the `actions.py` wrappers check them before calling into rail classes.

### `$bot_message` Modification in Output Rails

Output rail flows that modify `$bot_message` use a two-step pattern: call the action into a temporary variable, then extract the `answer` field. This is necessary because all actions return dicts (Section 2.3), not bare strings:

```colang
$mod = execute prepend_hedge(answer=$bot_message)
$bot_message = $mod.answer
```

NeMo uses the final value of `$bot_message` after all output rails complete as the response returned by `generate_async()`.

---

## Section 9: Documentation Deliverables

### 9.1 Colang Design Guide

**Location:** `docs/guardrails/COLANG_DESIGN_GUIDE.md`

**Part A — Colang 2.0 Design Principles:**
- Syntax reference (flows, actions, variables, abort)
- Naming conventions (`input rails *`, `output rails *` vs standalone dialog flows)
- When to use Colang vs Python
- Action return contract patterns
- Testing strategies
- Common pitfalls (flow ordering, abort semantics, variable scoping)

**Part B — Project Implementation Guide:**
- File layout
- How to add a new flow
- How to register a new action
- How Colang integrates with the Python executor pipeline
- Execution order diagram
- Configuration reference
- Troubleshooting

### 9.2 Updated Existing Docs

- `src/guardrails/README.md` — Add Colang section explaining dual-layer architecture
- `config/guardrails/README.md` — New file explaining file layout and NeMo conventions
- `docs/retrieval/NEMO_GUARDRAILS_IMPLEMENTATION.md` — Update to reflect Colang 2.0 migration
- `@summary` blocks on all new/modified files

### 9.3 Cleanup

- Remove `colang_demo.py` (replaced by real implementation)
- Remove `config/guardrails/intents.co` (absorbed into modular `.co` files)

---

## Section 10: Test Plan

### 10.1 Unit Tests — Actions (`tests/guardrails/test_colang_actions.py`)

Test each action in isolation (no NeMo runtime needed):
- **Deterministic actions:** `check_query_length`, `check_citations`, `check_answer_length`, `check_exfiltration`, `check_role_boundary`, `prepend_hedge`, `prepend_text`, `add_citation_reminder`, `prepend_low_confidence_note`, `adjust_answer_length`
- **Env var toggle tests:** Verify actions return pass/no-op when their backing rail is disabled
- **Fail-open tests:** Verify actions catch exceptions and return passing verdicts
- **Session state tests:** `check_abuse_pattern` and `check_jailbreak_escalation` escalation thresholds

### 10.2 Integration Tests — Colang Flows (`tests/guardrails/test_colang_flows.py`)

Test each `.co` file against NeMo runtime with a test `config.yml`:
- **Input rail blocking:** Verify queries that should be blocked (too short, non-English, abusive, exfiltration, role boundary, off-topic) return the expected bot message and do not reach generation
- **Input rail pass-through:** Verify legitimate RAG queries pass all input rails
- **Output rail modification:** Verify `$bot_message` is correctly modified by citation, hedge, length, and disclaimer flows
- **Output rail blocking:** Verify no-results and out-of-scope responses are caught
- **Dialog flow matching:** Verify greeting, farewell, administrative, feedback, and scope queries are matched by standalone dialog flows (not rail flows)

### 10.3 End-to-End Tests (`tests/guardrails/test_colang_e2e.py`)

Test the full `generate_async()` pipeline:
- A legitimate RAG query passes all input rails, triggers `rag_retrieve_and_generate`, passes all output rails, returns a response with metadata
- A jailbreak attempt is caught by the Python input executor (via Colang action bridge) and returns a rejection
- A query about a sensitive topic returns the answer with disclaimer prepended
- A query that returns no results gets the no-results handling response

### 10.4 Regression Tests

- Verify existing Python rail behavior is unchanged when invoked through Colang action wrappers vs. direct calls
- Verify `RAG_NEMO_ENABLED=false` bypasses all Colang flows (no NeMo import)
