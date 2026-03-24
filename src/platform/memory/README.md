<!-- @summary
Tenant-aware conversation memory: Redis canonical backend + no-op fallback. Manages sliding-window turns and rolling summaries for multi-turn RAG queries.
@end-summary -->

# platform/memory

## Overview

This package provides persistent conversation memory for multi-turn RAG queries. Memory is tenant-scoped, stored in Redis, and supports a sliding-window of recent turns plus a rolling summary for older context.

## Files

| File | Purpose | Key Exports |
| --- | --- | --- |
| `provider.py` | Redis-backed and no-op memory implementations with singleton factory | `ConversationMemoryProvider`, `RedisConversationMemory`, `NoopConversationMemory`, `get_conversation_memory` |
| `schemas.py` | Typed dataclasses for memory persistence | `ConversationTurn`, `ConversationSummary`, `ConversationMeta`, `MemoryContext` |
| `utils.py` | Memory context assembly helpers | `build_context_text`, `now_ms` |
| `__init__.py` | Package facade | re-exports from `provider.py` and `schemas.py` |

## Configuration

| Env Var | Default | Description |
|---------|---------|-------------|
| `RAG_MEMORY_ENABLED` | `true` | Enable conversation memory |
| `RAG_MEMORY_PROVIDER` | `redis` | Backend: `redis` or `noop` |
| `RAG_MEMORY_REDIS_URL` | `redis://localhost:6379/0` | Redis connection URL |
| `RAG_MEMORY_REDIS_PREFIX` | `rag:memory` | Redis key prefix |
| `RAG_MEMORY_MAX_RECENT_TURNS` | `8` | Sliding window size (recent turns kept verbatim) |
| `RAG_MEMORY_SUMMARY_TRIGGER_TURNS` | `12` | Rolling summary trigger threshold |
| `RAG_MEMORY_MAX_CONTEXT_TOKENS_ESTIMATE` | `1400` | Max estimated tokens for injected memory context |

## Context Management

```
New turn added
  ↓
Recent turns (last N) kept verbatim in MemoryContext
  ↓
Older turns → rolling summary (LLM-generated when trigger_turns threshold crossed)
  ↓
MemoryContext injected into RAG prompt as system/user context
```
