# Conversational Query Routing & Memory-Aware Generation — Design Sketch

| Field | Value |
|---|---|
| Date | 2026-03-27 |
| Status | APPROVED (brainstorm complete) |
| Scope | UPDATE to existing retrieval pipeline (`src/retrieval/`) |
| Produced by | Interactive brainstorming session (user + Claude) |

---

## Problem Statement

The RAG pipeline conflates two query patterns through a single pipeline:

1. **RAG (Retrieval-Augmented Generation)**: Documents are the primary knowledge source. Memory is supplementary.
2. **MAG (Memory-Augmented Generation)**: Conversation history is the primary knowledge source. Documents are irrelevant or secondary.

### Observed Failures

| Failure | Root Cause | Example |
|---|---|---|
| **Memory echo** | LLM sees `recent_turns` with prior answers + weak retrieved docs → generates from history instead of docs | User asks unrelated question, gets prior answer repeated |
| **Backward-reference BLOCK** | "Tell me more about the above" → retrieval returns weak docs → BLOCK/FLAG | MAG query treated as failed RAG query |
| **Error accumulation** | BLOCK message stored in memory → next turn echoes "Insufficient documentation found..." | "Who is Sam Altman?" → BLOCK → "What is the moon size?" → echoes BLOCK |
| **No context reset** | User says "forget about past convo" but memory still injected into generation | Memory-enriched reformulation over-narrows or contradicts user intent |

## Chosen Approach: Retrieval-First, Classify-on-Failure

**Key insight**: Don't pre-classify query intent. Always run retrieval (it's cheap). Use retrieval quality as the primary routing signal. Only when retrieval fails, use lightweight backward-reference detection to decide between memory-generation and BLOCK.

**Why not pre-classification?**
- Misclassifying `retrieval → memory` is dangerous: generates from conversation history as if authoritative
- Misclassifying `memory → retrieval` produces weak results and BLOCK
- Retrieval quality is an observed fact, not a prediction
- Backward-reference detection is narrower and simpler than full intent classification

### Rejected Alternatives

| Alternative | Why Rejected |
|---|---|
| Pre-classification routing (memory/retrieval/hybrid) | High misclassification cost. LLM intent classification is brittle for conversational follow-ups |
| Always-parallel two-pass (memory-gen + retrieval-gen) | Expensive — double LLM calls per query. Benefit is marginal vs. retrieval-first |
| Three-type classification at query processor | Over-engineered. Retrieval quality already provides the signal |

## The Four Fixes

### Fix 1: Dual-Query Reformulation

The query processor produces TWO query variants in a **single LLM call**:

- `processed_query`: Memory-enriched reformulation. Resolves pronouns ("its" → "component X's"), carries conversational references, expands backward references ("the above" → specific topic).
- `standalone_query`: Current-turn-only polish. No history injection. Fixes grammar, expands abbreviations, makes search-friendly. Serves as hedge against reformulation over-narrowing.
- `suppress_memory`: Boolean flag. Detected when user explicitly says "forget about past convo", "ignore previous", "new topic", "start fresh". When True, pipeline uses `standalone_query` for retrieval and suppresses memory in generation.

**Reformulation prompt** must be explicitly memory-aware with instructions for:
- Pronoun resolution using conversation context
- Topic shift detection (don't inject prior context on new topics)
- Backward-reference expansion ("tell me more" → "more details about X from previous discussion")
- Context-reset detection ("forget about", "ignore previous" → `suppress_memory = True`)

**Cost**: One LLM call (same as current), two outputs. No latency increase.

### Fix 2: Fallback Retrieval on `standalone_query`

```
Retrieval A on processed_query → observe quality

IF strong/moderate: proceed (reformulation worked)
IF weak AND NOT suppress_memory:
    → Retrieval B on standalone_query → observe quality
    → Use whichever produces better results
IF suppress_memory:
    → Only standalone_query retrieval was run (skip A entirely)
```

**Purpose**: Hedges against reformulation over-narrowing. If the memory-enriched query was too specific ("component X 3.3V rail SPI timing" when user just wanted "clock frequency"), the standalone query ("clock frequency specification") may find the right docs.

**Cost**: One extra retrieval call only when primary retrieval fails (~20-30% of conversational queries). No extra cost on straightforward queries.

### Fix 3: Memory-Generation Path

When BOTH retrievals are weak/insufficient AND backward-reference signals detected:

```
→ Generate from memory_context + recent_turns only (skip document context)
→ Apply confidence routing on this output too
→ Confidence routing can still BLOCK if memory-generated answer is low quality
```

**Backward-reference detection**: Lightweight heuristic (regex + simple signal detection):
- Explicit markers: "the above", "you said", "previously", "tell me more", "elaborate", "based on what we discussed"
- Pronoun density without resolution target
- Not a full intent classifier — narrow, cheap, and the fallback when wrong is the existing BLOCK behavior

### Fix 4: Don't Store BLOCK/FLAG in Memory

Responses where `post_guardrail_action in ("block", "flag")` are NOT stored in conversation memory:
- Show in UI/CLI with appropriate warning
- Skip `append_turn()` call
- Prevents error message accumulation across turns
- Clean memory = clean future generation

## Architecture Flow

```
Query arrives
  → Query Processor (one LLM call, memory_context prepended)
      outputs: processed_query, standalone_query, suppress_memory, confidence

  rag_chain.run():
      IF suppress_memory:
          search_query = standalone_query
          gen_memory = None
          gen_turns = None
      ELSE:
          search_query = processed_query
          gen_memory = memory_context
          gen_turns = recent_turns

      → Retrieval A on search_query → rerank → observe quality

      IF weak AND NOT suppress_memory:
          → Retrieval B on standalone_query → rerank → compare
          → Use better results

      IF both weak + backward reference detected:
          → Generation(memory_context + recent_turns, NO docs)
      ELIF strong/moderate:
          → Generation(docs + gen_memory + gen_turns)
      ELSE (weak, no backward ref):
          → Current behavior (BLOCK / FLAG)

      → Confidence routing on ALL paths (final safety net)
      → If BLOCK/FLAG: show in UI, DON'T store in memory
```

## Modules Affected

| Module | File(s) | Change |
|---|---|---|
| Query schemas | `src/retrieval/query/schemas.py` | Add `standalone_query`, `suppress_memory`, `has_backward_reference` to `QueryResult` |
| Query processor | `src/retrieval/query/nodes/query_processor.py` | Dual-query reformulation prompt, `suppress_memory` detection, backward-reference detection |
| RAG chain | `src/retrieval/pipeline/rag_chain.py` | Routing logic, fallback retrieval, memory-generation path, `suppress_memory` handling |
| RAG response schema | `src/retrieval/common/schemas.py` | Add `query_type` or `generation_source` field to response |
| Memory provider (caller-side) | Caller code (CLI/API/server) | Filter BLOCK/FLAG before `append_turn()` |
| Prompts | `prompts/query_reformulate_and_evaluate.md` | Update reformulation prompt for dual-query + memory-awareness |

## Edge Cases Considered

| Case | Handling |
|---|---|
| "Based on the above, tell me more" | backward ref detected → memory-generation path |
| "Forget about past convo, what's X?" | `suppress_memory=True` → standalone_query retrieval, no memory in generation |
| "What's its tolerance?" (pronoun) | Reformulation resolves via memory → retrieval on resolved query |
| "Who is Sam Altman?" → BLOCK → "What is the moon size?" | BLOCK not stored in memory → no echo on next turn |
| Fresh conversation, no memory | standalone_query = processed_query (no memory to enrich with), memory-gen path has nothing → BLOCK |
| Topic shift mid-conversation | Reformulation detects shift → standalone_query matches better → fallback retrieval catches it |
| Hybrid: "Based on what we discussed, what does the spec say about X?" | Reformulation enriches query → retrieval finds docs → generate with docs + memory |

## Scope Boundary

**In scope:**
- Dual-query reformulation (query processor)
- Fallback retrieval routing (rag_chain)
- Memory-generation path (rag_chain + generator)
- BLOCK/FLAG memory filtering (caller-side)
- Backward-reference heuristic detection
- Updated reformulation prompt

**Out of scope:**
- Full intent classification system
- Parallel two-pass generation (run both paths always)
- Changes to the embedding model or vector search
- Changes to the reranker
- Changes to confidence scoring weights
- Streaming path changes (generate_stream)
