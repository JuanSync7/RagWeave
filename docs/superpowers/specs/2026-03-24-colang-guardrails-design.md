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

| File | Purpose | Flow count |
|------|---------|------------|
| `input_rails.co` | Query validation before retrieval | ~4 flows |
| `conversation.co` | Multi-turn dialog management | ~5 flows |
| `output_rails.co` | Response quality enforcement | ~4 flows |
| `safety.co` | Safety & compliance flows | ~4 flows |
| `dialog_patterns.co` | RAG-specific dialog (no-results, disambiguation, feedback) | ~4 flows |
| `actions.py` | Registered Python action wrappers | ~8+ actions |

The existing `intents.co` will be **replaced** — intent definitions are absorbed into `conversation.co` (greetings, farewells, admin) and `input_rails.co` (off-topic routing).

---

## Section 2: Python Action Registration (`actions.py`)

NeMo auto-discovers `actions.py` in the config directory. Each action is a thin wrapper calling into existing rail classes:

```python
# config/guardrails/actions.py
from nemoguardrails.actions import action

@action()
async def check_injection(query: str) -> dict:
    """Wraps InjectionDetector — returns {verdict, method, confidence}"""

@action()
async def detect_pii(text: str, direction: str = "input") -> dict:
    """Wraps PIIDetector — returns {found, entities, redacted_text}"""

@action()
async def check_toxicity(text: str, direction: str = "input") -> dict:
    """Wraps ToxicityFilter — returns {verdict, score}"""

@action()
async def check_topic_safety(query: str) -> dict:
    """Wraps TopicSafetyChecker — returns {on_topic, confidence}"""

@action()
async def check_faithfulness(answer: str, context_chunks: list) -> dict:
    """Wraps FaithfulnessChecker — returns {verdict, score, claim_scores}"""

@action()
async def check_query_length(query: str) -> dict:
    """Returns {valid, length, reason} — min 3 chars, max 2000 chars"""

@action()
async def detect_language(query: str) -> dict:
    """Returns {language, supported} — uses simple heuristic or langdetect"""

@action()
async def check_retrieval_results(results: list) -> dict:
    """Returns {has_results, count, avg_confidence} — for no-results flow"""
```

### Design Principles

- Actions return **dicts** (not dataclasses) because NeMo serializes action results into Colang context variables.
- Each action wraps an existing rail class instance — **no logic duplication**.
- Actions respect existing env var toggles (e.g., if `RAG_NEMO_INJECTION_ENABLED=false`, `check_injection` returns `{verdict: "pass"}` immediately).
- `actions.py` lives in `config/guardrails/` (NeMo convention) but imports from `src/guardrails/`.

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

### Registration

```yaml
rails:
  input:
    flows:
      - input rails check query length
      - input rails check language
      - input rails check query clarity
      - input rails check abuse
```

Flows use NeMo's `input rails` naming convention — NeMo auto-wires them in order. `abort` stops the pipeline and returns the bot message.

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

Flags when conversation jumps domains.

```colang
flow input rails check topic drift
  $result = execute check_topic_drift(query=$user_message)
  if $result.drifted == True
    bot say "It looks like you've shifted topics. I'll search the knowledge base fresh for this new question."
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

**Design note:** Greeting, farewell, and administrative are standalone dialog flows (matched by intent before the rail pipeline). Off-topic and topic drift are input rails (they need to block retrieval).

---

## Section 5: Output Rails (`output_rails.co`)

Four flows that run after generation, before returning the response:

### 5.1 Citation Enforcement

Ensures responses reference source documents.

```colang
flow output rails check citations
  $result = execute check_citations(answer=$bot_message)
  if $result.has_citations == False
    $bot_message = execute add_citation_reminder(answer=$bot_message)
```

### 5.2 Confidence-Based Routing

Hedges or refuses when retrieval confidence is low.

```colang
flow output rails check confidence
  $result = execute check_response_confidence(answer=$bot_message)
  if $result.confidence == "none"
    bot say "I couldn't find relevant information in the knowledge base to answer that question."
    abort
  elif $result.confidence == "low"
    $bot_message = execute prepend_hedge(answer=$bot_message)
```

### 5.3 Answer Length Governance

Prevents excessively verbose or terse responses.

```colang
flow output rails check length
  $result = execute check_answer_length(answer=$bot_message)
  if $result.valid == False
    $bot_message = execute adjust_answer_length(answer=$bot_message, reason=$result.reason)
```

### 5.4 Source Scope Enforcement

Strips claims outside the knowledge base.

```colang
flow output rails check scope
  $result = execute check_source_scope(answer=$bot_message)
  if $result.in_scope == False
    bot say "I can only provide answers based on the documents in the knowledge base. Your question may be outside the scope of available information."
    abort
```

### Registration

```yaml
rails:
  output:
    flows:
      - output rails check no results
      - output rails check confidence
      - output rails check citations
      - output rails check length
      - output rails check scope
```

**Design note:** These run *after* the existing Python output rails (faithfulness, PII, toxicity). Python handles heavy compute (hallucination scoring, PII redaction). Colang handles policy decisions (hedging, citation reminders) that are better expressed declaratively.

---

## Section 6: Safety & Compliance (`safety.co`)

Four flows for safety enforcement beyond what Python rails handle:

### 6.1 Sensitive Topic Escalation

Adds disclaimers for legal/medical/financial content.

```colang
flow input rails check sensitive topic
  $result = execute check_sensitive_topic(query=$user_message)
  if $result.sensitive == True
    bot say $result.disclaimer
```

Example disclaimers:
- Medical: "This information is from the knowledge base and is not medical advice. Consult a healthcare professional."
- Legal: "This is informational only and does not constitute legal advice."
- Financial: "This is not financial advice. Consult a qualified professional."

Note: Does **not** abort — lets retrieval proceed with disclaimer prepended.

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
  elif $result.escalation_level == "block"
    bot say "Multiple policy violations detected. Further attempts may result in session restrictions."
    abort
```

The Python action tracks attempt count per session and escalates from warn → block.

**Design note:** These complement the existing `InjectionDetector` (4-layer defense). Python catches the technical attack; Colang flows handle the *policy response* — what to say, whether to escalate, when to add disclaimers vs. block.

---

## Section 7: RAG-Specific Dialog Patterns (`dialog_patterns.co`)

Four flows for domain-aware RAG interactions:

### 7.1 No-Results Handling

Graceful response when retrieval returns nothing useful.

```colang
flow output rails check no results
  $result = execute check_retrieval_results(answer=$bot_message)
  if $result.has_results == False
    bot say "I couldn't find relevant documents to answer your question. Try rephrasing with different keywords, or ask about a different aspect of the topic."
    abort
  elif $result.avg_confidence < 0.3
    $bot_message = execute prepend_low_confidence_note(answer=$bot_message)
```

### 7.2 Ambiguous Query Disambiguation

Prompts user to clarify when query matches multiple domains.

```colang
flow input rails check ambiguity
  $result = execute check_query_ambiguity(query=$user_message)
  if $result.ambiguous == True
    bot say $result.disambiguation_prompt
    abort
```

Example: User asks "How does attention work?" → "Did you mean attention in the context of transformer architectures, or attention mechanisms in cognitive science? Please clarify."

### 7.3 Document Scope Explanation

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

### 7.4 Feedback Collection

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
      # Query validation
      - input rails check query length
      - input rails check language
      - input rails check query clarity
      - input rails check abuse
      # Safety
      - input rails check exfiltration
      - input rails check role boundary
      - input rails check jailbreak escalation
      - input rails check sensitive topic
      # Conversation
      - input rails check off topic
      - input rails check topic drift
      # Dialog
      - input rails check ambiguity
  output:
    flows:
      # Response quality
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

### Execution Order

```
User Query
    ↓
1. Colang input rails (declarative policy — length, language, abuse, safety)
    ↓ (abort if blocked)
2. Python InputRailExecutor (heavy compute — injection 4-layer, PII, toxicity, topic safety)
    ↓
3. RailMergeGate (consensus routing)
    ↓
4. [Retrieval + Generation]
    ↓
5. Python OutputRailExecutor (faithfulness scoring, PII redaction, toxicity)
    ↓
6. Colang output rails (policy decisions — citations, confidence, length, scope)
    ↓
RAGResponse
```

### Integration Change

The `rag_chain.py` `_init_guardrails()` method already initializes `GuardrailsRuntime`. The change is to call Colang input rails *before* the Python executor and Colang output rails *after* the Python executor — two `generate_async()` calls bracketing the existing pipeline.

### Configuration

**No new env vars needed.** The existing `RAG_NEMO_ENABLED` master toggle controls the entire Colang+Python stack. Individual Python rail toggles (e.g., `RAG_NEMO_INJECTION_ENABLED`) continue to work — the `actions.py` wrappers check them before calling into rail classes.

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
