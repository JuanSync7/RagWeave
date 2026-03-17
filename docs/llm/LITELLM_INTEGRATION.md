# LiteLLM SDK Integration

**Status**: Implemented (ingest pipeline, retrieval pipeline, memory compaction)
**Date**: 2026-03-17
**Module**: `src/platform/llm/`

---

## 1. What is LiteLLM?

LiteLLM is a Python SDK that provides a unified `completion()` interface compatible with 100+ LLM providers (Ollama, OpenAI, Anthropic, Gemini, local models, etc.). Its `Router` class provides in-process model aliasing, fallback chains, load balancing, retries, and routing strategies — all configurable via YAML — without requiring a separate proxy server.

### Why LiteLLM SDK Router (not Proxy)

The RAG platform is a single application. All LLM consumers (ingestion nodes, retrieval, memory) run in the same Python process. The Router gives all the benefits of provider abstraction without:
- Extra network hop (proxy adds latency)
- Extra container to deploy/monitor/upgrade
- Duplicate infrastructure (the platform already has Langfuse, console UI, Redis memory)

| Tier | Mechanism | Use Case | This Project |
|------|-----------|----------|-------------|
| 1. SDK `completion()` | Direct function call | Single model, no fallbacks | Too simple |
| **2. SDK `Router`** | In-process registry | Single app, multiple models | **Chosen** |
| 3. Proxy Server | Separate container | Multi-app ecosystem | Deferred |

---

## 2. Architecture

```
Caller (ingest node / retrieval / memory)
    |
    v
get_llm_provider()  -->  LLMProvider singleton
    |
    v
litellm.Router (in-process)
    |  Named aliases: "default", "vision", "query", "smart", "fast"
    |  Fallback chains, load balancing, retries
    v
Provider (Ollama / OpenAI / Anthropic / etc.)
```

### Module Structure

```
src/platform/llm/
├── __init__.py       # Package facade: LLMProvider, get_llm_provider, LLMConfig, LLMResponse
├── provider.py       # Router wrapper with sync/async completion, streaming, JSON, vision
├── schemas.py        # LLMConfig (frozen), LLMResponse dataclasses
└── README.md         # Module documentation
```

### Key Design Decisions

1. **Singleton pattern** — `get_llm_provider()` returns a shared instance. The Router is expensive to initialize (model list parsing, connection pooling), so it's created once.

2. **Model aliases** — Callers request what they need by alias (`"default"`, `"vision"`, `"smart"`, `"fast"`), not by provider-specific model strings. Adding a new model or swapping providers is a config change, not a code change.

3. **Backward compatibility** — If `RAG_OLLAMA_MODEL` is set but `RAG_LLM_MODEL` is not, the system auto-prefixes with `ollama/` and uses the legacy value. Existing Ollama deployments work with zero config changes.

4. **Per-call overrides** — Temperature, max_tokens, and response_format can be overridden per call. The Router defaults come from config.

---

## 3. Configuration

### 3.1 Environment Variables (Simple Mode)

| Variable | Default | Description |
|----------|---------|-------------|
| `RAG_LLM_MODEL` | `ollama/<RAG_OLLAMA_MODEL>` | LiteLLM model string (e.g., `ollama/qwen2.5:3b`, `openai/gpt-4o`) |
| `RAG_LLM_API_BASE` | `<RAG_OLLAMA_URL>` | Base URL for local models |
| `RAG_LLM_API_KEY` | (empty) | API key for cloud providers |
| `RAG_LLM_FALLBACK_MODELS` | (empty) | Comma-separated fallback model list |
| `RAG_LLM_VISION_MODEL` | `ollama/<RAG_INGESTION_VISION_MODEL>` | Vision model string |
| `RAG_LLM_QUERY_MODEL` | `<RAG_LLM_MODEL>` | Query reformulation model string |
| `RAG_LLM_MAX_TOKENS` | `1024` | Max output tokens |
| `RAG_LLM_TEMPERATURE` | `0.3` | Default temperature |
| `RAG_LLM_NUM_RETRIES` | `3` | Retry count with built-in backoff |
| `RAG_LLM_ROUTER_CONFIG` | (empty) | Path to YAML Router config (activates YAML mode) |

**Backward compatibility**: Legacy `RAG_OLLAMA_MODEL` and `RAG_OLLAMA_URL` are auto-mapped to `RAG_LLM_MODEL` and `RAG_LLM_API_BASE` when the new vars are not set.

### 3.2 YAML Router Config (Multi-Model Mode)

Set `RAG_LLM_ROUTER_CONFIG=config/llm_router.yaml` to enable multi-model routing. The YAML file defines named model aliases with fallback chains:

```yaml
# config/llm_router.yaml
model_list:
  - model_name: "default"
    litellm_params:
      model: "ollama/qwen2.5:3b"
      api_base: "http://localhost:11434"

  - model_name: "default"              # fallback for "default"
    litellm_params:
      model: "openai/gpt-4o-mini"
      api_key: "os.environ/RAG_LLM_API_KEY"

  - model_name: "vision"
    litellm_params:
      model: "ollama/qwen2.5vl:3b"
      api_base: "http://localhost:11434"

  - model_name: "smart"
    litellm_params:
      model: "openai/gpt-4o"
      api_key: "os.environ/RAG_LLM_API_KEY"

  - model_name: "fast"
    litellm_params:
      model: "ollama/qwen2.5:1.5b"
      api_base: "http://localhost:11434"

router_settings:
  routing_strategy: "simple-shuffle"
  num_retries: 3
  retry_after: 5
  allowed_fails: 2
```

When multiple entries share the same `model_name`, the Router automatically provides fallback + load balancing between them.

### 3.3 Model String Format

LiteLLM model strings follow the `provider/model` convention:

| Provider | Example |
|----------|---------|
| Ollama | `ollama/qwen2.5:3b`, `ollama/llama3.2` |
| OpenAI | `openai/gpt-4o`, `openai/gpt-4o-mini` |
| Anthropic | `anthropic/claude-sonnet-4-20250514` |
| Together AI | `together_ai/meta-llama/Llama-3-70b` |

Full list: https://docs.litellm.ai/docs/providers

---

## 4. Usage Guide

### 4.1 Basic Completion

```python
from src.platform.llm import get_llm_provider

provider = get_llm_provider()
response = provider.generate(
    [{"role": "user", "content": "What is RAG?"}],
    model_alias="default",
)
print(response.content)
print(f"Tokens: {response.total_tokens}, Cost: ${response.cost_usd:.4f}")
```

### 4.2 JSON Mode

```python
response = provider.json_completion(
    [
        {"role": "system", "content": "Return JSON only."},
        {"role": "user", "content": 'Return {"summary": "...", "keywords": []}'},
    ],
    temperature=0.1,
    max_tokens=250,
)
import json
data = json.loads(response.content)
```

### 4.3 Vision Completion

```python
response = provider.vision_completion(
    prompt="Describe this figure. Return JSON with caption, visible_text, tags.",
    image_b64="<base64-encoded-image>",
    mime_type="image/png",
    model_alias="vision",
    temperature=0.1,
    max_tokens=220,
)
```

### 4.4 Streaming

```python
# Sync streaming
for chunk in provider.generate_stream(messages, model_alias="default"):
    print(chunk, end="", flush=True)

# Async streaming
async for chunk in provider.agenerate_stream(messages):
    yield chunk
```

### 4.5 Availability Check

```python
if provider.is_available(model_alias="vision"):
    # Vision model is reachable
    ...
```

---

## 5. What Changed

### 5.1 Replaced Components

| Before | After | Details |
|--------|-------|---------|
| `_ollama_json()` in `src/ingest/support/llm.py` | `_llm_json()` backed by `LLMProvider.json_completion()` | No more raw urllib to Ollama |
| Vision VLM calls in `src/ingest/support/vision.py` | `LLMProvider.vision_completion()` | Unified Ollama + OpenAI-compat into one call |
| `ensure_vision_ready()` — Ollama-specific readiness check | `LLMProvider.is_available("vision")` | Provider-agnostic availability check |
| Provider-specific validation in `pipeline/impl.py` | Removed | LiteLLM handles provider routing |
| `OllamaGenerator` raw urllib in `src/retrieval/generator.py` | `LLMProvider.generate()` / `generate_stream()` | All generation via Router |
| `_call_ollama()` in `src/retrieval/query_processor.py` | `_call_llm()` backed by `LLMProvider.generate()` | Query reformulation via Router |
| `_check_ollama_available()` in query processor | `_check_llm_available()` via `LLMProvider.is_available("query")` | Provider-agnostic health check |
| `_stream_ollama()` in `server/routes/query.py` | `_stream_llm()` via `LLMProvider.generate_stream()` | Streaming via Router |
| `OllamaGenerator` in `src/platform/memory/provider.py` | `LLMProvider.generate()` directly | Memory compaction via Router |

### 5.2 IngestionConfig Changes

Fields retained for backward compatibility and metadata logging but **no longer used for HTTP calls**:
- `llm_model`, `ollama_url` — routing handled by LiteLLM Router
- `vision_provider`, `vision_model`, `vision_api_base_url`, `vision_api_key`, `vision_api_path` — routing handled by LiteLLM Router

Fields still actively used:
- `enable_llm_metadata`, `enable_vision_processing` — behavioral on/off switches
- `llm_temperature`, `vision_temperature`, `vision_max_tokens` — per-call overrides passed to LLMProvider
- `vision_max_figures`, `vision_max_image_bytes`, `vision_strict` — image extraction limits

### 5.3 New Dependencies

Added to `pyproject.toml`:
- `litellm` — unified LLM SDK
- `pyyaml` — YAML Router config parsing

### 5.4 New Config Variables

See Section 3.1 above. All new `RAG_LLM_*` variables with backward-compatible defaults from legacy `RAG_OLLAMA_*` vars.

---

## 6. Migration Guide

### For Existing Ollama Deployments

**No changes required.** The system auto-maps:
- `RAG_OLLAMA_MODEL=qwen2.5:3b` → `RAG_LLM_MODEL=ollama/qwen2.5:3b`
- `RAG_OLLAMA_URL=http://localhost:11434` → `RAG_LLM_API_BASE=http://localhost:11434`

### To Switch to a Cloud Provider

```bash
# OpenAI
export RAG_LLM_MODEL="openai/gpt-4o-mini"
export RAG_LLM_API_KEY="sk-..."

# Anthropic
export RAG_LLM_MODEL="anthropic/claude-sonnet-4-20250514"
export RAG_LLM_API_KEY="sk-ant-..."
```

### To Use Fallback Chains

```bash
# Try local first, fall back to cloud
export RAG_LLM_MODEL="ollama/qwen2.5:3b"
export RAG_LLM_FALLBACK_MODELS="openai/gpt-4o-mini"
export RAG_LLM_API_KEY="sk-..."
```

### To Use Multi-Model YAML Config

```bash
export RAG_LLM_ROUTER_CONFIG="config/llm_router.yaml"
```

Edit `config/llm_router.yaml` to define model aliases, fallbacks, and routing strategy.

---

## 7. Planned Work

| Phase | Scope | Status |
|-------|-------|--------|
| Ingest pipeline (`support/llm.py`, `support/vision.py`) | Replace raw urllib LLM calls | Done |
| Retrieval generator (`src/retrieval/generator.py`) | Replace `OllamaGenerator` internals | Done |
| Query processor (`src/retrieval/query_processor.py`) | Replace raw urllib query reformulation | Done |
| Streaming route (`server/routes/query.py`) | Replace `_stream_ollama` with `LLMProvider` | Done |
| Memory compaction (`src/platform/memory/provider.py`) | Route summarization through LLMProvider | Done |
| Token counting (`src/platform/token_budget/`) | Replace heuristic with `litellm.token_counter()` + model info via `litellm.get_model_info()` | Done |
| Token budget UX | Wire token budget into CLI display + API QueryResponse + context window % | Done |
| Cost tracking | Add `litellm.completion_cost()` + Prometheus metrics | Planned |
| LiteLLM Redis cache | Custom Redis cache (AOF) is superior for RAG — caches full pipeline, not just LLM | Not needed |

---

## 8. Troubleshooting

### Model not found

```
litellm.exceptions.NotFoundError: Model 'ollama/xyz' not available
```

Ensure the model is pulled locally (`ollama pull xyz`) or that the model string matches a known provider format.

### Connection refused

```
litellm.exceptions.ServiceUnavailableError: Connection refused
```

Check that `RAG_LLM_API_BASE` points to a running service (default: `http://localhost:11434` for Ollama).

### Vision model not reachable

```
RuntimeError: Vision model is not reachable via LiteLLM
```

Ensure `RAG_LLM_VISION_MODEL` is correct and the model is available. For Ollama: `ollama pull qwen2.5vl:3b`.

### YAML config not loading

Verify the file exists and `RAG_LLM_ROUTER_CONFIG` points to an absolute or correct relative path. Check logs for `LLM Router loaded from YAML: ...`.
