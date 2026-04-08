### `config/settings.py` + `src/ingest/common/types.py` + `src/ingest/embedding/state.py` + `src/ingest/embedding/workflow.py` — Configuration, State, and Pipeline Wiring

**Module purpose:** These four files collectively define the visual embedding feature's configuration surface (env-var constants and their IngestionConfig fields), the validation logic for those fields, the state extensions for passing image data through the pipeline, and the LangGraph graph topology that wires the visual embedding node into the DAG.

**In scope:**
- Env-var constant parsing for all six `RAG_INGESTION_*` visual embedding variables (default values, type coercion, truthy/falsy boolean rules)
- `IngestionConfig` field defaults, the `generate_page_images` property alias, and `_check_visual_embedding_config` validation logic
- `IngestFileResult.visual_stored_count` field default
- `PIPELINE_NODE_NAMES` list membership and ordering
- `EmbeddingPipelineState` new fields (`visual_stored_count`, `page_images`) and backward-compatibility of existing fields
- `build_embedding_graph()` DAG topology: node presence, edge ordering, and short-circuit placement

**Out of scope:**
- Runtime behavior of the `visual_embedding_node` itself (model loading, image rendering, Weaviate writes)
- `impl.py` orchestration and `_check_visual_embedding_config` call site behavior beyond what the function itself returns
- Text-track correctness or other pipeline nodes' logic
- Dependency installation (colpali-engine, bitsandbytes) tested separately under NFR-906

---

#### Happy path scenarios

| Scenario | Input | Expected output |
|----------|-------|-----------------|
| All defaults — no env vars set | No `RAG_INGESTION_*` env vars present | `RAG_INGESTION_ENABLE_VISUAL_EMBEDDING=False`, `RAG_INGESTION_VISUAL_TARGET_COLLECTION="RAGVisualPages"`, `RAG_INGESTION_COLQWEN_MODEL="vidore/colqwen2-v1.0"`, `RAG_INGESTION_COLQWEN_BATCH_SIZE=4`, `RAG_INGESTION_PAGE_IMAGE_QUALITY=85`, `RAG_INGESTION_PAGE_IMAGE_MAX_DIMENSION=1024` |
| Boolean enable via `"true"` | `RAG_INGESTION_ENABLE_VISUAL_EMBEDDING="true"` | Constant evaluates to `True` |
| Boolean enable via `"1"` | `RAG_INGESTION_ENABLE_VISUAL_EMBEDDING="1"` | Constant evaluates to `True` |
| Boolean enable via `"yes"` | `RAG_INGESTION_ENABLE_VISUAL_EMBEDDING="yes"` | Constant evaluates to `True` |
| Boolean disable (explicit false) | `RAG_INGESTION_ENABLE_VISUAL_EMBEDDING="false"` | Constant evaluates to `False` |
| Custom collection name | `RAG_INGESTION_VISUAL_TARGET_COLLECTION="TestVisual"` | Constant is `"TestVisual"` |
| Custom model name | `RAG_INGESTION_COLQWEN_MODEL="vidore/other-model"` | Constant is `"vidore/other-model"` |
| Integer env var — batch size | `RAG_INGESTION_COLQWEN_BATCH_SIZE="8"` | Constant is integer `8` |
| Integer env var — image quality | `RAG_INGESTION_PAGE_IMAGE_QUALITY="90"` | Constant is integer `90` |
| Integer env var — max dimension | `RAG_INGESTION_PAGE_IMAGE_MAX_DIMENSION="2048"` | Constant is integer `2048` |
| IngestionConfig defaults | `IngestionConfig()` constructed with no args | All six visual fields match the six settings.py constants exactly |
| `generate_page_images` when enabled | `IngestionConfig(enable_visual_embedding=True)` | `config.generate_page_images` returns `True` |
| `generate_page_images` when disabled | `IngestionConfig(enable_visual_embedding=False)` | `config.generate_page_images` returns `False` |
| `_check_visual_embedding_config` disabled fast-path | `enable_visual_embedding=False` (any other values) | Returns `([], [])` immediately, no validation performed |
| `_check_visual_embedding_config` valid config | `enable_visual_embedding=True`, `enable_docling_parser=True`, `colqwen_batch_size=16`, `page_image_quality=75`, `page_image_max_dimension=1024` | Returns `([], [])` |
| `_check_visual_embedding_config` boundary — minimum valid batch size | `colqwen_batch_size=1` | No error for batch size |
| `_check_visual_embedding_config` boundary — maximum valid batch size | `colqwen_batch_size=32` | No error for batch size |
| `_check_visual_embedding_config` boundary — minimum valid quality | `page_image_quality=1` | No error for quality |
| `_check_visual_embedding_config` boundary — maximum valid quality | `page_image_quality=100` | No error for quality |
| `_check_visual_embedding_config` boundary — minimum valid dimension | `page_image_max_dimension=256` | No error for dimension |
| `_check_visual_embedding_config` boundary — maximum valid dimension | `page_image_max_dimension=4096` | No error for dimension |
| `PIPELINE_NODE_NAMES` membership | Import `PIPELINE_NODE_NAMES` | `"visual_embedding"` is present in the list |
| `PIPELINE_NODE_NAMES` ordering | Import `PIPELINE_NODE_NAMES` | `"visual_embedding"` appears immediately after `"embedding_storage"` and immediately before `"knowledge_graph_storage"` |
| `PIPELINE_NODE_NAMES` total count | Import `PIPELINE_NODE_NAMES` | Length is exactly 15 |
| `IngestFileResult` default `visual_stored_count` | `IngestFileResult()` constructed | `visual_stored_count` field is `0` |
| `EmbeddingPipelineState` new fields accessible | State dict with both new fields set | `state["visual_stored_count"]` and `state["page_images"]` are accessible |
| `EmbeddingPipelineState` new field absent — safe default | State dict without `visual_stored_count` key | `state.get("visual_stored_count", 0)` returns `0` without KeyError |
| `EmbeddingPipelineState` `page_images` accepts None | `page_images=None` | No type error; field holds `None` |
| `EmbeddingPipelineState` `page_images` accepts list | `page_images=[mock_image_1, mock_image_2]` | Field holds the list |
| `build_embedding_graph()` returns compiled graph | Call with valid config | Returns a compiled LangGraph object without error |
| `build_embedding_graph()` node count | Inspect compiled graph | DAG contains exactly 10 nodes |
| `build_embedding_graph()` includes `visual_embedding` node | Inspect compiled graph nodes | `"visual_embedding"` is present as a node |
| `build_embedding_graph()` edge: `embedding_storage` → `visual_embedding` | Inspect graph edges | Unconditional edge from `embedding_storage` to `visual_embedding` exists |
| `build_embedding_graph()` edge: `visual_embedding` → `knowledge_graph_storage` | Graph built with `enable_knowledge_graph_storage=True` | Conditional edge routes from `visual_embedding` to `knowledge_graph_storage` |
| `build_embedding_graph()` edge: `visual_embedding` → END | Graph built with `enable_knowledge_graph_storage=False` | Conditional edge routes from `visual_embedding` to END |
| Legacy edge removed | Inspect graph edges | No direct edge from `embedding_storage` to `knowledge_graph_storage` |

---

#### Error scenarios

| Error type | Trigger condition | Expected behavior |
|-----------|------------------|-------------------|
| `ValueError` on non-integer batch size | `RAG_INGESTION_COLQWEN_BATCH_SIZE="abc"` at module import | `ValueError` raised at settings.py import time (not deferred) |
| `ValueError` on non-integer quality | `RAG_INGESTION_PAGE_IMAGE_QUALITY="abc"` at module import | `ValueError` raised at settings.py import time |
| `ValueError` on non-integer max dimension | `RAG_INGESTION_PAGE_IMAGE_MAX_DIMENSION="abc"` at module import | `ValueError` raised at settings.py import time |
| `_check_visual_embedding_config` — Docling not enabled | `enable_visual_embedding=True`, `enable_docling_parser=False` | Returns non-empty `errors` list; error message names the Docling requirement |
| `_check_visual_embedding_config` — batch size below range | `enable_visual_embedding=True`, `enable_docling_parser=True`, `colqwen_batch_size=0` | Returns error naming `colqwen_batch_size` and valid range `1–32` |
| `_check_visual_embedding_config` — batch size above range | `enable_visual_embedding=True`, `enable_docling_parser=True`, `colqwen_batch_size=64` | Returns error naming `colqwen_batch_size` and valid range `1–32` |
| `_check_visual_embedding_config` — quality below range | `enable_visual_embedding=True`, `enable_docling_parser=True`, `page_image_quality=0` | Returns error naming `page_image_quality` and valid range `1–100` |
| `_check_visual_embedding_config` — quality above range | `enable_visual_embedding=True`, `enable_docling_parser=True`, `page_image_quality=101` | Returns error naming `page_image_quality` and valid range `1–100` |
| `_check_visual_embedding_config` — dimension below range | `enable_visual_embedding=True`, `enable_docling_parser=True`, `page_image_max_dimension=128` | Returns error naming `page_image_max_dimension` and valid range `256–4096` |
| `_check_visual_embedding_config` — dimension above range | `enable_visual_embedding=True`, `enable_docling_parser=True`, `page_image_max_dimension=8192` | Returns error naming `page_image_max_dimension` and valid range `256–4096` |
| `_check_visual_embedding_config` — multiple simultaneous violations | `colqwen_batch_size=0`, `page_image_quality=0`, `page_image_max_dimension=128` (all out of range, with `enable_docling_parser=True`) | `errors` list contains one entry per violation (at least 3 errors) |
| `ImportError` on missing colpali dependency | `visual_embedding_node` module fails to import due to absent colpali-engine | `workflow.py` itself raises `ImportError` on import; worker startup fails with a clear import error |
| `_check_visual_embedding_config` returns tuple | Call with any valid `IngestionConfig` | Return value is always a 2-tuple `(list, list)`, never raises |

---

#### Boundary conditions

- **Boolean env var parsing**: Only `"true"`, `"1"`, and `"yes"` (case-sensitive as specified) evaluate to `True`; any other string including `"yes_please"`, `"TRUE"`, `"YES"`, `"on"`, and empty string `""` silently evaluate to `False`. Tests should confirm the exact set of truthy strings.
- **Integer env var type**: The settings.py constants for batch size, quality, and max dimension must be Python `int` (not `str`). Tests should assert `isinstance(value, int)`.
- **Range boundaries are inclusive**: `colqwen_batch_size=1` and `colqwen_batch_size=32` are both valid; `0` and `33` are both errors. Same inclusive treatment for quality (`1–100`) and dimension (`256–4096`). Tests must probe both the last valid value and the first invalid value on each boundary.
- **`_check_visual_embedding_config` fast-path**: When `enable_visual_embedding=False`, range checks must NOT run even if range values are set to invalid integers (e.g., batch size 0). This ensures no startup cost and no spurious errors for disabled features.
- **`generate_page_images` is a property, not a field**: It must not appear as a stored key in the dataclass `__dict__`; it is a derived view of `enable_visual_embedding`.
- **`EmbeddingPipelineState` total=False field**: `visual_stored_count` and `page_images` must be genuinely optional — constructing a state dict without them must not raise a TypedDict validation error. Accessing them with `.get()` must return defaults.
- **`page_images` cleared after node**: Although clearing is the node's responsibility, state.py's type annotation must accept `None` as a valid value for `page_images`.
- **`PIPELINE_NODE_NAMES` ordering**: The test must assert positional adjacency (index of `"visual_embedding"` == index of `"embedding_storage"` + 1), not merely membership.
- **Env var isolation**: Tests that modify env vars must restore the original environment (use `monkeypatch.setenv` / `monkeypatch.delenv` or `unittest.mock.patch.dict`). Since constants are read at module-import time, tests that need to verify different env-var values must reload the module (via `importlib.reload`) within the patched environment.

---

#### Integration points

- **`config/settings.py` → `types.py`**: `IngestionConfig` imports the six constants as field defaults. If settings.py raises at import (invalid integer env var), all of `types.py` and everything that imports it will also fail to import.
- **`types.py` → `impl.py`**: `_check_visual_embedding_config` is defined in `types.py` but called in `impl.py`. Tests here only cover the function's own return contract; the call site (error propagation, startup abort) is tested in the impl module's test section.
- **`types.py` → `workflow.py`**: `workflow.py` reads `IngestionConfig` fields (specifically `enable_knowledge_graph_storage`) to set conditional routing out of `visual_embedding`. Workflow tests must construct an `IngestionConfig` and pass it to `build_embedding_graph()`.
- **`state.py` → `visual_embedding_node`**: The node reads `page_images` and writes `visual_stored_count`. State tests verify field presence and type annotations; node behavior is out of scope here.
- **`workflow.py` → `visual_embedding_node` module**: `workflow.py` imports `visual_embedding_node` at module load time. The `ImportError` propagation test therefore exercises the `workflow.py` import path, not a function call.
- **`PIPELINE_NODE_NAMES` → progress reporting / result aggregation**: Callers that iterate over `PIPELINE_NODE_NAMES` to build progress dicts or validate result keys will break if `"visual_embedding"` is absent or misplaced. The count and ordering tests guard this contract.

---

#### Known test gaps

- **Case-sensitivity of boolean truthy strings**: The spec states truthy strings are `"true"/"1"/"yes"`. It is unspecified whether `"True"`, `"TRUE"`, or `"YES"` are also accepted. Tests should document observed behavior and flag this as a spec clarification needed if uppercase forms do not match the spec's intent.
- **Module-reload env var tests**: Because constants are read at import time, testing different env var values requires `importlib.reload(settings)`. This pattern is fragile in test suites that share a process; isolation via subprocess or dedicated test modules may be needed but is not mandated here.
- **`_check_visual_embedding_config` warning list**: The spec defines the return as `(errors, warnings)` but only specifies error conditions. No warning-triggering conditions are documented. Tests cannot cover warning output until warnings are specified; this is a known gap.
- **`EmbeddingPipelineState` runtime validation**: `state.py` explicitly has no runtime validation. There are no tests for invalid field types because the TypedDict contract is structural, not enforced at runtime. Mypy/pyright type checking is outside the scope of pytest tests.
- **Graph compilation internals**: Tests inspect node presence and edge topology via the LangGraph compiled graph's public API. If LangGraph does not expose a stable introspection API, edge topology tests may need to be implemented as smoke-run integration tests rather than structural unit tests.
- **`IngestFileResult.visual_stored_count` non-zero values**: FR-605 states that after a 10-page doc with visual enabled, `visual_stored_count=10`. This end-to-end count correctness is owned by the visual embedding node test section, not this config/state section.

---

#### Agent isolation contract (include verbatim in write-module-tests dispatch)

> **Agent isolation contract:** This agent receives ONLY:
> 1. This module test spec section
> 2. Phase 0 contract files (for import surface only)
>
> **Must NOT receive:** Source implementation files, other modules' test specs, or the engineering guide directly.
