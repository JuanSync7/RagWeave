### `config/settings.py` — Docling-Native Chunking Configuration

**Purpose:**

This section of `config/settings.py` defines three module-level constants — `RAG_INGESTION_VLM_MODE`, `RAG_INGESTION_HYBRID_CHUNKER_MAX_TOKENS`, and `RAG_INGESTION_PERSIST_DOCLING_DOCUMENT` — that expose the Docling-Native Chunking Pipeline's behavioral knobs as environment variables. These constants are imported by `src/ingest/common/types.py` and used as default values for the corresponding `IngestionConfig` fields. By reading from environment variables at module load time, the system allows operators to configure pipeline behavior without code changes or redeployment. (FR-2401, FR-2403, FR-2405, FR-2407)

**How it works:**

Each constant is assigned by reading an environment variable with `os.environ.get()` and converting to the correct Python type:

1. `RAG_INGESTION_VLM_MODE` reads the `RAG_INGESTION_VLM_MODE` env var, defaulting to `"disabled"`. No type conversion is applied — the value remains a string. Valid values are `"disabled"`, `"builtin"`, and `"external"`. Invalid strings are accepted silently here; validation occurs in `verify_core_design()` in `src/ingest/impl.py`.

2. `RAG_INGESTION_HYBRID_CHUNKER_MAX_TOKENS` reads the `RAG_INGESTION_HYBRID_CHUNKER_MAX_TOKENS` env var and wraps `os.environ.get()` in `int()`. The default is `512`, which matches the maximum token input length of the bge-m3 embedding model. If the env var contains a non-integer string, `int()` raises `ValueError` at module import time.

3. `RAG_INGESTION_PERSIST_DOCLING_DOCUMENT` reads the `RAG_INGESTION_PERSIST_DOCLING_DOCUMENT` env var and converts to `bool` by checking whether the lowercased result is in `("true", "1", "yes")`. The default is `True` because `"true"` is in that set. Any other value — including `"false"` or an empty string — evaluates to `False`.

**Key design decisions:**

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|-----------------|
| Read env vars at module import time (not call time) | Lazy reads at first access; passing env var names to constructors | Module-level constants provide a single authoritative source of defaults. Downstream callers import the constant rather than re-reading the env var name, preventing typo-induced silent misconfiguration. |
| Use explicit `("true", "1", "yes")` set for boolean parsing | `bool(os.environ.get(...))` (truthy on any non-empty string); deprecated `distutils.strtobool` | `bool("false")` returns `True`, which is a counterintuitive trap. The explicit set avoids it. `distutils.strtobool` is deprecated in Python 3.12+. |
| Default `vlm_mode` to `"disabled"` | Default to `"builtin"` or `"external"` | Preserves pre-redesign behavior — no VLM enrichment unless explicitly requested. Operators opt in. |
| Default `hybrid_chunker_max_tokens` to `512` | Smaller value (256) or larger value (1024) | 512 is bge-m3's actual maximum. Smaller wastes embedding capacity; larger causes silent truncation at embedding time. |

**Configuration:**

| Parameter | Type | Default | Valid Range / Options | Effect |
|-----------|------|---------|----------------------|--------|
| `RAG_INGESTION_VLM_MODE` | `str` | `"disabled"` | `"disabled"`, `"builtin"`, `"external"` | Selects VLM image enrichment mode. `"disabled"`: no enrichment. `"builtin"`: Docling's SmolVLM runs at parse time, descriptions embedded in DoclingDocument before chunking. `"external"`: LiteLLM-routed vision model called post-chunking via `vlm_enrichment_node`. |
| `RAG_INGESTION_HYBRID_CHUNKER_MAX_TOKENS` | `int` | `512` | Positive integer; values above 512 trigger a config warning | Maximum token count per HybridChunker chunk. Values above 512 exceed bge-m3's input limit — `verify_core_design()` emits a warning but does not block execution. |
| `RAG_INGESTION_PERSIST_DOCLING_DOCUMENT` | `bool` | `True` | `"true"`, `"1"`, `"yes"` → `True`; anything else → `False` | When `True`, the serialized `DoclingDocument` JSON is written to `CleanDocumentStore` after Phase 1. When `False`, no `.docling.json` file is written and Phase 2 falls back to markdown chunking. |

**Error behavior:**

`RAG_INGESTION_HYBRID_CHUNKER_MAX_TOKENS` raises `ValueError` at module import time if the env var contains a non-integer string (for example, `RAG_INGESTION_HYBRID_CHUNKER_MAX_TOKENS=abc`). This is an import-time crash — the ingestion pipeline will not start. There is no fallback.

`RAG_INGESTION_VLM_MODE` accepts any string at this layer without error. Validation of valid string values is deferred to `verify_core_design()`, which raises `ValueError` before processing begins.

`RAG_INGESTION_PERSIST_DOCLING_DOCUMENT` cannot fail — boolean coercion via set membership is always valid.
