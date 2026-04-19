# Inference Backend Engineering Guide
Last updated: 2026-04-19
No companion spec — this guide is the authoritative reference. Derived from the implementation.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Architecture Decisions](#2-architecture-decisions)
3. [Module Reference](#3-module-reference)
4. [End-to-End Data Flow](#4-end-to-end-data-flow)
5. [Configuration Reference](#5-configuration-reference)
6. [Integration Contracts](#6-integration-contracts)
7. [Operational Notes](#7-operational-notes)
8. [Known Limitations](#8-known-limitations)
9. [Extension Guide](#9-extension-guide)

---

## 1. System Overview

### Purpose

The inference backend subsystem provides two interchangeable backends for the two inference-heavy operations in the retrieval pipeline: **embedding** (converting text to dense vectors) and **reranking** (rescoring retrieved candidates against a query using a cross-encoder).

Both operations can run in either of two modes:

- **Local mode** — model weights are loaded in-process on the worker. Uses `sentence-transformers` (embedding) and Hugging Face `transformers` (reranking). Suitable for single-node or development environments with a local GPU.
- **vLLM mode** — inference is offloaded to dedicated `rag-vllm-embed` and `rag-vllm-rerank` containers. The worker communicates over HTTP via `litellm`. Suitable for distributed deployments where you want to keep the worker process lean.

A single environment variable (`RAG_INFERENCE_BACKEND`) switches both backends simultaneously. The rest of the system never branches on backend type — all callers receive a uniform interface object.

### Architecture Diagram

```
                        ┌─────────────────────────────────┐
                        │           rag-worker             │
                        │                                  │
                        │  src/ingest/impl.py              │
                        │  rag_chain.py                    │
                        │       │           │              │
                        │       ▼           ▼              │
                        │  get_embedding_  get_reranker_   │
                        │  provider()      provider()      │
                        │       │           │              │
                        └───────┼───────────┼──────────────┘
                                │           │
              ┌─────────────────┤           ├─────────────────┐
              │                 │           │                 │
              ▼                 ▼           ▼                 ▼
     [INFERENCE_BACKEND=local]          [INFERENCE_BACKEND=vllm]
              │                                   │
    ┌─────────┴──────────┐             ┌──────────┴───────────┐
    │                    │             │                       │
    ▼                    ▼             ▼                       ▼
LocalBGEEmbeddings  LocalBGEReranker  LiteLLMEmbeddings  LiteLLMReranker
    │                    │             │                       │
    ▼                    ▼             ▼                       ▼
sentence-          transformers    litellm               litellm
transformers       (AutoModel +    (HTTP client)         (HTTP client)
(SentenceTransformer AutoTokenizer)     │                       │
  in-process)      in-process          ▼                       ▼
                               rag-vllm-embed:8001   rag-vllm-rerank:8002
                               (vLLM OpenAI-compat)  (vLLM OpenAI-compat)
```

### Design Goals

- **Worker leanness in vLLM mode** — `sentence-transformers`, `transformers`, and `litellm` are all imported lazily (inside method bodies), so neither library is required in the other deployment mode's container image.
- **Backward-compatible default** — `RAG_INFERENCE_BACKEND` defaults to `"local"`, so existing single-node setups require no configuration change.
- **Single env var switch** — both embedding and reranking backends are controlled by one variable. No per-surface configuration.
- **Uniform interface** — callers receive standard objects (`Embeddings` for embedding, a duck-typed reranker for reranking) and never inspect the backend type.

### Technology Choices

| Component | Technology | Reason |
|-----------|------------|--------|
| Local embedding | `sentence-transformers` / BAAI/bge-m3 | Established local embedding library; supports batch encoding and normalized output |
| Local reranking | HF `transformers` / BAAI/bge-reranker-v2-m3 | Direct `AutoModelForSequenceClassification` avoids FlagEmbedding compatibility issues with `transformers >= 5.x` |
| Remote HTTP client | LiteLLM | Already in stack for LLM generation; provides routing config, Langfuse observability, and a unified exception hierarchy |
| Inference server | vLLM | High-throughput OpenAI-compatible server; supports both embedding and reranking endpoints |
| Embedding interface | LangChain `Embeddings` | Standard contract used throughout LangChain retrieval chains and vector store integrations |

---

## 2. Architecture Decisions

### AD-1: Single `INFERENCE_BACKEND` controls both embedding and reranking

Both `get_embedding_provider()` and `get_reranker_provider()` read the same `INFERENCE_BACKEND` setting. There is no `EMBED_BACKEND` / `RERANK_BACKEND` split.

The tradeoff is simplicity over flexibility: a single switch is easy to reason about in `.env` and in ops runbooks. The cost is that you cannot run local embedding alongside vLLM reranking (or vice versa) without code changes. Given that both operations are deployed on the same hardware tier, splitting them independently adds configuration surface with minimal practical benefit. See Section 8 (Known Limitations) and Section 9 (Extension Guide) if mixed-backend operation is needed.

### AD-2: LiteLLM as the HTTP client for vLLM

Rather than calling vLLM's `/v1/embeddings` and `/v1/rerank` endpoints directly via `httpx` or `requests`, the vLLM paths use `litellm.embedding()` and `litellm.rerank()`. LiteLLM is already in the stack for LLM generation and its router config (`RAG_LLM_ROUTER_CONFIG`) maps model name strings (`"embedding"`, `"reranking"`) to backend URLs. This means URL changes only require a router config update, not code changes. LiteLLM also provides a consistent exception hierarchy and forwards traces to Langfuse.

### AD-3: vLLM services under the `inference` Docker Compose profile

`rag-vllm-embed` and `rag-vllm-rerank` are defined with `profiles: ["inference"]`. A plain `docker compose up` does not start them. This keeps the default development environment lean — a developer using local mode never pulls multi-gigabyte vLLM images. vLLM services are opt-in via `--profile inference`.

### AD-4: Fast-fail `ValueError` at settings import for unknown backends

`config/settings.py` validates `INFERENCE_BACKEND` at import time (before any provider is instantiated). An unknown value raises `ValueError` immediately on worker startup, rather than surfacing as an obscure `AttributeError` or `ModuleNotFoundError` at the first embedding or reranking call. This surfaces misconfiguration at the earliest possible moment.

### AD-5: Named Docker volumes for HuggingFace model cache

`vllm-embed-cache` and `vllm-rerank-cache` are named volumes mounted at `/root/.cache/huggingface` inside each container. Model weights downloaded on first start persist across container restarts and re-creations. Without this, every `docker compose up` would re-download model weights from HuggingFace Hub.

### AD-6: Lazy imports throughout

`sentence-transformers` (in `LocalBGEEmbeddings`), `transformers` (in `LocalBGEReranker`), and `litellm` (in both `LiteLLMEmbeddings` and `LiteLLMReranker`) are all imported inside the method/function body at first use rather than at module top level. The primary reason is deployment-mode isolation: a vLLM deployment does not need `sentence-transformers` or `transformers` installed, and a local deployment does not need `litellm`. Lazy importing prevents `ModuleNotFoundError` at import time when the dependency is absent and keeps container images lean.

---

## 3. Module Reference

### `src/core/embeddings.py` — Embedding Providers

#### Purpose

This module provides two interchangeable embedding backends and a factory function that selects between them at runtime based on configuration. Both backends implement LangChain's `Embeddings` interface so the rest of the system can treat them identically.

The two backends are:

- **`LocalBGEEmbeddings`** — runs BAAI/bge-m3 in-process using `sentence-transformers`. Suitable for single-node or development deployments where a GPU is available on the same host.
- **`LiteLLMEmbeddings`** — calls an OpenAI-compatible `/v1/embeddings` endpoint (typically a vLLM container) over HTTP via the `litellm` library. Suitable for distributed deployments where embedding is offloaded to a separate inference server.

The module also exposes an internal method `encode_sentences` on both classes, used by the semantic chunking stage to compute cosine similarities without going through the LangChain interface.

---

#### How it works

**Step 1 — Factory selection (`get_embedding_provider`)**

The entry point for all callers is `get_embedding_provider()`. It reads the `INFERENCE_BACKEND` setting and returns the appropriate instance:

```python
def get_embedding_provider() -> Embeddings:
    if INFERENCE_BACKEND == "vllm":
        return LiteLLMEmbeddings(timeout=VLLM_TIMEOUT_SECONDS)
    return LocalBGEEmbeddings()
```

Callers receive a concrete `Embeddings` object and never need to branch on backend type themselves.

**Step 2 — Local path: `LocalBGEEmbeddings`**

Construction loads the model from disk via a lazy import of `sentence-transformers`:

```python
def _load_sentence_transformer(model_path: str):
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(model_path)
```

The lazy import is intentional — it ensures the worker image (used in vLLM deployments) can start without `sentence-transformers` installed.

`embed_documents` batches the input texts and calls `model.encode` with `normalize_embeddings=True` and a batch size of 32. The normalization step produces unit-norm vectors, which is required for the semantic chunking contract (see `encode_sentences` below).

`embed_query` encodes a single string. It uses the same normalization flag but omits the batch size and progress bar for single-item efficiency.

`encode_sentences` is called by the semantic chunking stage. It uses a larger batch size (64) and disables the progress bar:

```python
def encode_sentences(self, sentences: list[str]) -> np.ndarray:
    return self.model.encode(
        sentences,
        normalize_embeddings=True,
        batch_size=64,
        show_progress_bar=False,
    )
```

**Step 3 — Remote path: `LiteLLMEmbeddings`**

`litellm` is imported lazily inside `embed_documents`, so the API container never pays its import cost unless the vLLM backend is active:

```python
def embed_documents(self, texts: list[str]) -> list[list[float]]:
    import litellm
    resp = litellm.embedding(model=self.model, input=texts, timeout=self.timeout)
    return [d["embedding"] for d in resp.data]
```

`embed_query` delegates to `embed_documents` with a single-element list and returns the first result.

`encode_sentences` calls `embed_documents` and then L2-normalizes the resulting numpy array in-place, because vLLM's endpoint does not normalize by default:

```python
def encode_sentences(self, sentences: list[str]) -> np.ndarray:
    vecs = np.array(self.embed_documents(sentences))
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    return vecs / norms
```

**Step 4 — Observability**

Both classes obtain a tracer from `src.platform.observability.get_tracer()` at construction time. Every `embed_documents` and `embed_query` call opens a span, records either the batch size or the text length as an attribute, and closes the span with `status="ok"` on success. Spans are not closed on exception — any exception propagates to the caller with the span left open, which the observability layer treats as an implicit error signal.

---

#### Key design decisions

| Decision | Choice | Alternatives considered | Rationale |
|----------|--------|------------------------|-----------|
| Lazy imports for `sentence-transformers` and `litellm` | Import inside the function/method body, not at module top | Top-level imports | Each dependency is heavy and only needed in one deployment mode. A vLLM deployment should not need `sentence-transformers` installed, and the API container should not need `litellm`. Lazy importing keeps the container images lean and prevents import-time failures in the wrong environment. |
| Single factory function rather than a registry or plugin system | `get_embedding_provider()` reads one env var and returns one of two hardcoded classes | A plugin registry, abstract factory class, or entry-points mechanism | The system currently has exactly two backends. A registry adds indirection without benefit at this scale. The factory is easy to extend when a third backend is needed — add one `elif` branch. |
| Both classes expose `encode_sentences` returning `np.ndarray` | Defined on both `LocalBGEEmbeddings` and `LiteLLMEmbeddings` | Only on `LocalBGEEmbeddings`; semantic chunking uses local only | Semantic chunking must work in both deployment modes. Exposing `encode_sentences` on both classes — with explicit L2 normalization on the vLLM path — keeps the chunking stage backend-agnostic. |
| L2 normalization in `LiteLLMEmbeddings.encode_sentences` | Normalize after the API call using numpy | Rely on vLLM normalization config; document that callers must normalize | vLLM's `/v1/embeddings` endpoint does not normalize by default and the setting is server-side, not per-request. Normalizing client-side in `encode_sentences` satisfies the cosine-sim contract without requiring server configuration. The zero-norm guard (`np.where(norms == 0, 1.0, norms)`) prevents division-by-zero on degenerate inputs. |
| LangChain `Embeddings` as the base class | Both classes inherit from `langchain_core.embeddings.Embeddings` | A custom abstract base class; no base class at all | LangChain's `Embeddings` interface is the standard contract for embeddings in LangChain retrieval chains and vector store integrations. Conforming to it means the classes are directly usable anywhere LangChain expects an `Embeddings` object, with no adapter layer. |

---

#### Configuration

| Parameter | Env var | Type | Default | Effect |
|-----------|---------|------|---------|--------|
| `INFERENCE_BACKEND` | `RAG_INFERENCE_BACKEND` | `str` | `"local"` | Selects the active backend. `"local"` → `LocalBGEEmbeddings`; `"vllm"` → `LiteLLMEmbeddings`. Any other value raises `ValueError` in `config/settings.py` at startup, before any embedding call is made. |
| `EMBEDDING_MODEL_PATH` | derived from `RAG_MODEL_ROOT` | `str` | path under `RAG_MODEL_ROOT/baai/bge-m3` | Filesystem path passed to `SentenceTransformer()` when the local backend is active. Has no effect when `INFERENCE_BACKEND="vllm"`. |
| `VLLM_TIMEOUT_SECONDS` | `RAG_VLLM_TIMEOUT_SECONDS` | `int` | `30` | HTTP timeout (in seconds) applied to every `litellm.embedding()` call when the vLLM backend is active. Has no effect on the local backend. |

The `model` name passed to `LiteLLMEmbeddings` defaults to `"embedding"` and is resolved by the LiteLLM router configuration (`RAG_LLM_ROUTER_CONFIG`) to the actual backend URL. If the router config is absent or misconfigured, `litellm.embedding()` will raise at call time.

---

#### Error behavior

**`LocalBGEEmbeddings`**

- **Model not found at path**: `SentenceTransformer(model_path)` raises `OSError` at construction time. Propagates out of `get_embedding_provider()` to the caller.
- **`sentence-transformers` not installed**: `_load_sentence_transformer` raises `ModuleNotFoundError` at first construction. Expected when configured for vLLM.
- **Encoding errors**: `model.encode()` propagates exceptions from PyTorch/numpy (e.g. `RuntimeError` on CUDA OOM). No retry logic applied.

**`LiteLLMEmbeddings`**

- **`litellm` not installed**: Deferred `import litellm` raises `ModuleNotFoundError` at first call. Expected when using the local backend.
- **Request timeout**: `litellm.embedding()` raises `litellm.Timeout` if the vLLM server does not respond within `VLLM_TIMEOUT_SECONDS`.
- **HTTP / model routing errors**: Surfaces as `litellm.BadRequestError`, `litellm.AuthenticationError`, or similar `litellm.exceptions.APIError` subclasses.
- **Zero-norm vectors in `encode_sentences`**: Silently treated as already normalized (returns zero vector unchanged). Not an error.

In both embedding classes, observability spans use `start_span`/`span.end()` explicitly. A `status="ok"` close happens only on the success path. An exception propagates to the caller with the span left unclosed, which the observability layer treats as an implicit error signal.

---

### `src/retrieval/query/nodes/reranker.py` — Reranker Providers

#### Purpose

This module provides the reranking layer of the retrieval pipeline. After an initial vector search returns a candidate set of documents, the reranker rescores each candidate against the query using a cross-encoder model, which reads the query and document together (rather than embedding them independently). The top-K highest-scoring documents are returned as `RankedResult` objects for downstream answer generation.

The module exposes two provider implementations and a factory function that selects between them based on runtime configuration:

- **`LocalBGEReranker`** — loads `BAAI/bge-reranker-v2-m3` in-process via Hugging Face `transformers` and scores batches on the local GPU or CPU.
- **`LiteLLMReranker`** — delegates to a separately-deployed vLLM container via the `litellm.rerank()` API, keeping the main process free of model weights.

---

#### How it works

**Factory dispatch — `get_reranker_provider()`**

The public entry point is `get_reranker_provider()`. It reads `INFERENCE_BACKEND` and returns the matching provider:

```python
def get_reranker_provider():
    if INFERENCE_BACKEND == "vllm":
        return LiteLLMReranker(timeout=VLLM_TIMEOUT_SECONDS)
    return LocalBGEReranker()
```

**`LocalBGEReranker` — load sequence**

1. **Device selection** — checks `torch.cuda.is_available()`, sets `self.device` to `"cuda"` or `"cpu"`.
2. **Dtype resolution** — looks up `RERANKER_PRECISION` in `_TORCH_DTYPE_NAME_BY_PRECISION` (maps labels to `torch` attribute name *strings*), then resolves via `getattr(torch, _dtype_name)` at use time.
3. **Model load — two paths:** fp16/bf16 loads directly in reduced precision with SDPA; fp32 loads in default precision (int8/int4 fall through to fp32 with a warning).
4. **Error handling** — any load exception is caught, logged, and re-raised as `ModelLoadError` with `model_path` attribute.
5. **`model.eval()`** — disables dropout.

**`LocalBGEReranker.rerank()` — batching loop**

```python
pairs = [[query, doc.text] for doc in documents]
for i in range(0, len(pairs), RERANKER_BATCH_SIZE):
    batch = pairs[i : i + RERANKER_BATCH_SIZE]
    inputs = self.tokenizer(batch, padding=True, truncation=True,
                            max_length=RERANKER_MAX_LENGTH,
                            return_tensors="pt").to(self.device)
    logits = self.model(**inputs).logits.squeeze(-1).float()
    scores_raw = logits.cpu().tolist()
    if isinstance(scores_raw, float):
        scores_raw = [scores_raw]
    batch_scores = [1.0 / (1.0 + math.exp(-x)) for x in scores_raw]
    scores.extend(batch_scores)
```

Results are assembled, sorted descending by score, and the top-K slice returned. The entire body runs under `torch.inference_mode()` as a context manager.

**`LiteLLMReranker.rerank()` — deferred import and results guard**

`litellm` is imported inside the method body. The call:
```python
resp = litellm.rerank(model=self.model, query=query,
                      documents=[d.text for d in documents],
                      top_n=top_k, timeout=self.timeout)
raw_results = resp.results or []
```
`resp.results or []` guards against `None` on transient routing failures.

---

#### Key design decisions

| Decision | Choice | Alternatives considered | Rationale |
|----------|--------|------------------------|-----------|
| `_TORCH_DTYPE_NAME_BY_PRECISION` stores strings, not `torch.dtype` objects | `{"fp16": "float16", ...}` with `getattr` at use time | Store `torch.float16` etc. directly | Module-level `torch.float32` access crashed CI pytest collection on incomplete torch wheel builds. Strings are safe at import time. |
| `torch.inference_mode()` as context manager | `with torch.inference_mode():` inside `rerank()` | `@torch.inference_mode()` decorator | Decorator evaluates at class-body definition time (import time). CI had incomplete torch wheels at that point, breaking collection. |
| Manual sigmoid via `1.0 / (1.0 + math.exp(-x))` | Python `math.exp` on CPU floats | `logits.sigmoid()` or `torch.sigmoid` | `transformers >= 4.50` returns a `_Logits` proxy lacking `__neg__` and `.sigmoid()`; `torch.sigmoid` removed in `torch 2.x`. |
| `resp.results or []` guard | Falsy check | Assert non-None / raise | `resp.results` is typed `Optional[List]`. Graceful degradation to empty list is consistent with the empty-input fast path. |
| `litellm` deferred import | Inside `rerank()` | Top-level import | API container does not include `litellm`. Top-level import would make the module unimportable there. |
| `transformers` directly instead of `FlagEmbedding` | `AutoModelForSequenceClassification` + `AutoTokenizer` | `FlagEmbedding.FlagReranker` | FlagEmbedding has compatibility issues with `transformers >= 5.x`. |
| `attn_implementation="sdpa"` | SDPA for both load paths | Default attention / flash-attn | PyTorch built-in SDPA fuses the attention kernel without requiring a separate `flash-attn` wheel. |

---

#### Configuration

| Parameter | Env var | Type | Default | Effect |
|-----------|---------|------|---------|--------|
| `INFERENCE_BACKEND` | `RAG_INFERENCE_BACKEND` | `str` | `"local"` | `"local"` → `LocalBGEReranker`; `"vllm"` → `LiteLLMReranker`. Unknown values raise `ValueError` at settings load. |
| `RERANKER_MODEL_PATH` | Derived from `RAG_MODEL_ROOT` | `str` | *(under model root)* | Path to `BAAI/bge-reranker-v2-m3`. Local backend only. |
| `RERANK_TOP_K` | `RAG_RERANK_TOP_K` | `int` | `5` | Max `RankedResult` objects returned by either provider. |
| `RERANKER_MAX_LENGTH` | `RAG_RERANKER_MAX_LENGTH` | `int` | `512` | Token truncation limit for the tokenizer in `LocalBGEReranker`. |
| `RERANKER_BATCH_SIZE` | `RAG_RERANKER_BATCH_SIZE` | `int` | `32` | Query-document pairs per forward pass in `LocalBGEReranker`. |
| `RERANKER_PRECISION` | `RAG_RERANKER_PRECISION` | `str` | `"fp32"` | Weight precision: `"fp32"`, `"fp16"`, `"bf16"`. `"int8"`/`"int4"` fall through to fp32 with a warning. |
| `VLLM_TIMEOUT_SECONDS` | `RAG_VLLM_TIMEOUT_SECONDS` | `int` | `30` | HTTP timeout for `LiteLLMReranker` requests. |

---

#### Error behavior

- **`ModelLoadError`** — raised by `LocalBGEReranker.__init__()` on tokenizer/model load failure. Carries `model_path` attribute; original exception chained.
- **`RuntimeError`** — from CUDA OOM or unexpected tensor shape in `rerank()`. Not caught; propagates to caller.
- **Empty-input fast path** — both providers return `[]` immediately when `documents` is empty.
- **`ValueError` from unknown `INFERENCE_BACKEND`** — raised by `config/settings.py` at startup, before `get_reranker_provider()` is called.
- **`resp.results` being `None`** — silently converted to `[]` via `or []` guard.

---

## 4. End-to-End Data Flow

### Scenario A — Local backend, document ingest

The ingest caller (`src/ingest/impl.py`) needs to embed document chunks for storage in Weaviate.

1. `src/ingest/impl.py` calls `get_embedding_provider()`.
2. `INFERENCE_BACKEND == "local"` → `LocalBGEEmbeddings()` is constructed. On first construction, `_load_sentence_transformer(EMBEDDING_MODEL_PATH)` executes the deferred `from sentence_transformers import SentenceTransformer` and loads the model from disk.
3. The caller invokes `embed_documents(["chunk1", "chunk2"])`.
4. An observability span is opened.
5. `model.encode(texts, normalize_embeddings=True, batch_size=32)` runs in-process.
6. A `list[list[float]]` of unit-norm vectors is returned.
7. The span is closed with `status="ok"`.
8. The caller stores the vectors in Weaviate.

### Scenario B — vLLM backend, query reranking

The RAG chain (`rag_chain.py`) has completed a vector search and needs to rerank the candidate documents.

1. `rag_chain.py` calls `get_reranker_provider()`.
2. `INFERENCE_BACKEND == "vllm"` → `LiteLLMReranker(timeout=30)` is returned.
3. The caller invokes `rerank(query, search_results, top_k=5)`.
4. `documents` is non-empty, so the fast-path early return is skipped.
5. `import litellm` executes (deferred; first call only).
6. `litellm.rerank(model="reranking", query=query, documents=[d.text for d in documents], top_n=5, timeout=30)` is called.
7. LiteLLM resolves `"reranking"` via `RAG_LLM_ROUTER_CONFIG` to `http://rag-vllm-rerank:8002`.
8. An HTTP POST is sent to `rag-vllm-rerank:8002/v1/rerank`.
9. The response is received; `resp.results or []` extracts the scored list.
10. Results are assembled into `RankedResult` objects, sorted descending by score, and the top-5 are returned to `rag_chain.py`.

### Scenario C — vLLM backend, timeout failure

The reranker is called in vLLM mode but the `rag-vllm-rerank` container is not responding.

1. `LiteLLMReranker.rerank()` calls `litellm.rerank(timeout=30)`.
2. The vLLM container does not respond within 30 seconds.
3. `litellm.Timeout` is raised inside `rerank()`.
4. The exception propagates uncaught through `rerank()` to `rag_chain.py`.
5. `rag_chain.py` logs the error and returns an empty or degraded result set to the caller.
6. The observability span — opened inside `rerank()` after the empty-document guard, via `with self.tracer.span(...)` — is closed by the context manager `__exit__` without a `status="ok"` attribute, which the observability backend records as an error signal.

---

## 5. Configuration Reference

All variables below are read by `config/settings.py` unless noted otherwise.

| Parameter | Env var | Type | Default | Scope |
|-----------|---------|------|---------|-------|
| `INFERENCE_BACKEND` | `RAG_INFERENCE_BACKEND` | str | `"local"` | Both |
| `EMBEDDING_MODEL_PATH` | derived from `RAG_MODEL_ROOT` | str | `$RAG_MODEL_ROOT/baai/bge-m3` | Local embed |
| `VLLM_EMBED_URL` | `RAG_VLLM_EMBED_URL` | str | `http://rag-vllm-embed:8001` | vLLM embed |
| `VLLM_RERANK_URL` | `RAG_VLLM_RERANK_URL` | str | `http://rag-vllm-rerank:8002` | vLLM rerank |
| `VLLM_EMBEDDING_MODEL` | `RAG_VLLM_EMBEDDING_MODEL` | str | `Qwen/Qwen3-Embedding-0.6B` | vLLM embed container |
| `VLLM_RERANKER_MODEL` | `RAG_VLLM_RERANKER_MODEL` | str | `Qwen/Qwen3-Reranker-0.6B` | vLLM rerank container |
| `VLLM_TIMEOUT_SECONDS` | `RAG_VLLM_TIMEOUT_SECONDS` | int | `30` | vLLM paths |
| `RERANKER_MODEL_PATH` | derived from `RAG_MODEL_ROOT` | str | under model root | Local rerank |
| `RERANK_TOP_K` | `RAG_RERANK_TOP_K` | int | `5` | Both rerankers |
| `RERANKER_MAX_LENGTH` | `RAG_RERANKER_MAX_LENGTH` | int | `512` | Local rerank |
| `RERANKER_BATCH_SIZE` | `RAG_RERANKER_BATCH_SIZE` | int | `32` | Local rerank |
| `RERANKER_PRECISION` | `RAG_RERANKER_PRECISION` | str | `"fp32"` | Local rerank |

**Note:** `RAG_VLLM_DTYPE` controls the dtype passed to the vLLM container startup command (`auto` / `float16` / `bfloat16`). It is set in `docker-compose.yml` as part of the `--dtype` flag and is not read by `config/settings.py`.

**Note:** `RAG_LLM_ROUTER_CONFIG` must map the model name strings `"embedding"` and `"reranking"` to the correct backend URLs (`RAG_VLLM_EMBED_URL` and `RAG_VLLM_RERANK_URL`). If absent or misconfigured, `litellm.embedding()` and `litellm.rerank()` will raise at call time.

---

## 6. Integration Contracts

### Callers of `get_embedding_provider()`

- **Input:** none — reads config at module import time.
- **Output:** an `Embeddings`-conforming object with:
  - `embed_documents(list[str]) -> list[list[float]]`
  - `embed_query(str) -> list[float]`
  - `encode_sentences(list[str]) -> np.ndarray`
- **Contract:** `encode_sentences` always returns L2-normalized vectors (unit norm) regardless of backend. Callers may compute cosine similarity as a raw dot product without additional normalization.
- **Failure modes:** raises on model load failure, backend timeout, or encoding error. No retry logic is applied inside the provider — callers are responsible for retry/fallback if needed.

### Callers of `get_reranker_provider()`

- **Input:** none.
- **Output:** an object with:
  - `rerank(query: str, documents: list[SearchResult], top_k: int) -> list[RankedResult]`
- **Contract:** result is sorted descending by `score` (float 0–1 after sigmoid). Returns `[]` if `documents` is empty. May raise on backend failure (CUDA OOM, `litellm.Timeout`, HTTP errors).
- **Failure modes:** `ModelLoadError` on local model load failure; `litellm.Timeout` / `litellm.APIError` subclasses on remote failure; `RuntimeError` on CUDA OOM.

### External dependencies (vLLM mode)

- `rag-vllm-embed` must be running and healthy at `RAG_VLLM_EMBED_URL` before the first embedding call.
- `rag-vllm-rerank` must be running and healthy at `RAG_VLLM_RERANK_URL` before the first rerank call.
- `RAG_LLM_ROUTER_CONFIG` must map model names `"embedding"` and `"reranking"` to the correct container URLs.
- `HUGGING_FACE_HUB_TOKEN` may be required if the configured model is gated on HuggingFace Hub.

---

## 7. Operational Notes

### Starting vLLM services

```bash
./scripts/compose.sh --profile inference up -d
make vllm-pull-models        # first time only — pre-warms named volume caches
make container-probe-vllm    # verify both containers are healthy
```

The `vllm-pull-models` target is important on first start. Both containers have a 120s `start_period` in their health checks. If the model download exceeds 120s, Docker marks the container unhealthy and may terminate it. Pre-warming the named volumes avoids this.

### Switching to vLLM backend

```bash
# In .env:
RAG_INFERENCE_BACKEND=vllm

make restart-worker
```

### Reverting to local backend

```bash
# In .env:
RAG_INFERENCE_BACKEND=local

make restart-worker
```

### Restarting vLLM containers

```bash
make restart-vllm
```

### Monitoring

Both `LocalBGEEmbeddings`/`LiteLLMEmbeddings` and `LocalBGEReranker`/`LiteLLMReranker` emit observability spans visible in Langfuse. Error signal differs by module: **embedding spans** use `start_span`/`span.end()` explicitly — an exception leaves the span unclosed entirely. **Reranker spans** use a `with tracer.span(...)` context manager — an exception closes the span via `__exit__` but without setting `status="ok"`. In both cases, the absence of a `status="ok"` attribute on the span indicates the call did not complete successfully.

The reranker uses `logger = logging.getLogger("rag.reranker")`. Model load time is logged at INFO (`"Reranker ready in Xms"`). Failed loads log at ERROR before the `ModelLoadError` is raised.

### OOM on local reranker

Reduce `RAG_RERANKER_BATCH_SIZE` (default 32) to lower per-forward-pass GPU memory usage, or switch `RAG_RERANKER_PRECISION` to `"fp16"` or `"bf16"` to reduce model memory footprint.

---

## 8. Known Limitations

- **`int8`/`int4` precision not implemented.** These keys are accepted by `RERANKER_PRECISION` but fall through to fp32 with a warning. `bitsandbytes` quantization is not yet wired.

- **`encode_sentences` on `LiteLLMEmbeddings` issues one HTTP request per call.** There is no batching across multiple `encode_sentences` calls. High-volume semantic chunking (many small sentence lists) may bottleneck on the vLLM embed endpoint.

- **`INFERENCE_BACKEND` is a single switch for both surfaces.** There is no supported configuration for local embedding with vLLM reranking, or the reverse. Code changes are required.

- **vLLM health-check `start_period` is 120s.** If model download exceeds this window, the container is marked unhealthy and compose may kill it. Use `make vllm-pull-models` to pre-warm before starting with the `inference` profile.

- **`LiteLLMReranker` does not retry on transient failures.** A single `litellm.Timeout` or HTTP error propagates immediately to the caller. Retry and circuit-breaking logic must be implemented at the call site if needed.

---

## 9. Extension Guide

### Adding a third inference backend (e.g., Triton)

1. Add a new class implementing the `Embeddings` interface in `src/core/embeddings.py`. It must implement `embed_documents`, `embed_query`, and `encode_sentences` with L2-normalized return.

2. Add a new class implementing the reranker interface in `src/retrieval/query/nodes/reranker.py`. It must implement `rerank(query: str, documents: list[SearchResult], top_k: int) -> list[RankedResult]`.

3. Add the new backend name to `_VALID_INFERENCE_BACKENDS` in `config/settings.py`.

4. Add an `elif INFERENCE_BACKEND == "triton":` branch in both `get_embedding_provider()` and `get_reranker_provider()`.

5. Update `.env.example` with any new env vars required by the backend.

6. Add the new classes to `__all__` in both modules and their `__init__.py` re-exports.

7. Verify with:
   ```bash
   RAG_INFERENCE_BACKEND=triton make restart-worker && make smoke-test
   ```

### Adding per-surface backend configuration (different backend for embed vs rerank)

1. Add `EMBED_BACKEND` and `RERANK_BACKEND` settings to `config/settings.py` alongside `INFERENCE_BACKEND`.
2. Add validation for both new vars (same `ValueError` fast-fail pattern).
3. Update `get_embedding_provider()` to read `EMBED_BACKEND`.
4. Update `get_reranker_provider()` to read `RERANK_BACKEND`.
5. Keep `INFERENCE_BACKEND` as a convenience alias: if set, it should populate both `EMBED_BACKEND` and `RERANK_BACKEND` as defaults, so existing `.env` files continue to work without changes.
