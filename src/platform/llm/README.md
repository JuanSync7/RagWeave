<!-- @summary
Unified LLM provider backed by LiteLLM Router — single entry point for all LLM calls across ingestion, retrieval, and memory subsystems.
@end-summary -->

# platform/llm

## Overview

This package provides a unified LLM interface for the entire RAG platform, replacing direct HTTP calls to Ollama and OpenAI-compatible endpoints with LiteLLM's `Router` abstraction.

All LLM consumers (ingestion nodes, retrieval generator, memory compaction) call `get_llm_provider()` and use named model aliases instead of hardcoding provider URLs.

## Files

| File | Purpose | Key Exports |
| --- | --- | --- |
| `schemas.py` | Typed contracts for config and response | `LLMConfig`, `LLMResponse` |
| `provider.py` | LiteLLM Router wrapper with sync/async completion, streaming, JSON mode, vision | `LLMProvider`, `get_llm_provider` |
| `__init__.py` | Package facade | `LLMProvider`, `get_llm_provider`, `LLMConfig`, `LLMResponse` |

## Configuration

Two config modes:

1. **Env-var mode** (simple, backward-compatible default):

   | Variable | Default | Description |
   |----------|---------|-------------|
   | `RAG_LLM_MODEL` | `ollama/<RAG_OLLAMA_MODEL>` | LiteLLM model string |
   | `RAG_LLM_API_BASE` | `<RAG_OLLAMA_URL>` | Base URL for local models |
   | `RAG_LLM_API_KEY` | (empty) | API key for cloud providers |
   | `RAG_LLM_FALLBACK_MODELS` | (empty) | Comma-separated fallback list |
   | `RAG_LLM_VISION_MODEL` | `ollama/<RAG_INGESTION_VISION_MODEL>` | Vision model string |
   | `RAG_LLM_QUERY_MODEL` | `<RAG_LLM_MODEL>` | Query reformulation model |
   | `RAG_LLM_MAX_TOKENS` | `1024` | Max output tokens |
   | `RAG_LLM_TEMPERATURE` | `0.3` | Default temperature |
   | `RAG_LLM_NUM_RETRIES` | `3` | Retry count |
   | `RAG_LLM_ROUTER_CONFIG` | (empty) | Path to YAML Router config |

2. **YAML mode** (multi-model): Set `RAG_LLM_ROUTER_CONFIG=config/llm_router.yaml` to define named aliases, fallback chains, and routing strategies. See `config/llm_router.yaml` for the template.

## Usage

```python
from src.platform.llm import get_llm_provider

provider = get_llm_provider()

# Text completion
response = provider.generate(
    [{"role": "user", "content": "Summarize this document."}],
    model_alias="default",
)
print(response.content)

# JSON mode
response = provider.json_completion(
    [{"role": "user", "content": 'Return {"summary": "..."}'}],
    temperature=0.1,
    max_tokens=250,
)

# Vision
response = provider.vision_completion(
    prompt="Describe this image.",
    image_b64="<base64-encoded-image>",
    mime_type="image/png",
    model_alias="vision",
)

# Streaming
for chunk in provider.generate_stream(messages):
    print(chunk, end="")
```

## Architecture

```
Caller (ingest node / retrieval / memory)
    |
    v
get_llm_provider()  -->  LLMProvider singleton
    |
    v
litellm.Router
    |  (model aliases: "default", "vision", "query", "smart", "fast")
    |  (fallback chains, load balancing, retries)
    v
Provider (Ollama / OpenAI / Anthropic / etc.)
```

## Consumers

| Consumer | Module | Model Alias |
| --- | --- | --- |
| Ingestion LLM (metadata, refactoring) | `src/ingest/support/llm.py` | `default` |
| Ingestion vision (figure captions) | `src/ingest/support/vision.py` | `vision` |
| Retrieval generator (answer synthesis) | `src/retrieval/generator.py` | `default` |
| Retrieval streaming | `server/routes/query.py` | `default` |
| Query processor (reformulation) | `src/retrieval/query_processor.py` | `query` |
| Memory compaction (summarization) | `src/platform/memory/provider.py` | `default` |

## Dependency Notes

- Depends on `litellm` and `pyyaml` (added to `pyproject.toml`).
- Depends on `config.settings` for `LLM_*` env var resolution.
- No dependency on any specific consumer (ingest, retrieval, etc.).
