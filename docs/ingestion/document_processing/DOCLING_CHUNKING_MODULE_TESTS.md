> **Document type:** Phase D white-box test plan
> **Companion spec:** `DOCLING_CHUNKING_SPEC.md`
> **Companion guide:** `DOCLING_CHUNKING_ENGINEERING_GUIDE.md`
> **Phase 0 contracts:** `docs/ingestion/document_processing/DOCLING_CHUNKING_IMPLEMENTATION.md`
> **Last updated:** 2026-03-27

# Docling-Native Chunking Pipeline — Test Docs

> **For write-module-tests agents:** This document is your source of truth.
> Read ONLY your assigned module section. Do not read source files, implementation code,
> or other modules' test specs.

**Engineering guide:** `docs/ingestion/document_processing/DOCLING_CHUNKING_ENGINEERING_GUIDE.md`
**Phase 0 contracts:** `docs/ingestion/document_processing/DOCLING_CHUNKING_IMPLEMENTATION.md`
**Spec:** `docs/ingestion/document_processing/DOCLING_CHUNKING_SPEC.md`
**Produced by:** write-test-docs

---

## Overview

This document specifies the Phase D white-box tests for the Docling-Native Chunking Pipeline redesign.

**Execution model:** All module test agents run in parallel, each in isolation. Each receives only its assigned module section plus Phase 0 contract files.

**Expected outcome:** All Phase D tests FAIL on first run against pre-redesign code (they cover the new Docling-native path and associated behaviors). Tests against the implemented redesign code should all pass.

**Modules covered (9 total):**
1. `config/settings.py` — env var definitions
2. `src/ingest/common/types.py` — IngestionConfig new fields
3. `src/ingest/common/clean_store.py` — write_docling / read_docling
4. `src/ingest/support/docling.py` — parse_with_docling + DoclingParseResult
5. `src/ingest/doc_processing/nodes/structure_detection.py` — DoclingDocument propagation
6. `src/ingest/embedding/nodes/chunking.py` — dual-path chunking
7. `src/ingest/embedding/nodes/vlm_enrichment.py` — external VLM post-chunking
8. `src/ingest/impl.py` — design checks
9. `src/ingest/doc_processing/nodes/structure_detection.py` — input format routing (Docling native vs fallback)

---

## Mock/Stub Interface Specifications

These mock specifications are used across module test sections and integration tests. They are defined once here and referenced by name.

### Mock: DocumentConverter (Docling)

**What it replaces:** `docling.document_converter.DocumentConverter` — parses source documents into `DoclingDocument` objects.

**Interface to mock:**
```python
from unittest.mock import MagicMock, patch

mock_converter = MagicMock()
mock_docling_doc = MagicMock()
mock_docling_doc.model_dump_json.return_value = '{"body":{"children":[]}}'
mock_result = MagicMock()
mock_result.document = mock_docling_doc
mock_converter.convert.return_value = mock_result

with patch("src.ingest.support.docling.DocumentConverter", return_value=mock_converter):
    ...
```

**Happy path return:** `convert(file_path)` → result with `.document` set to a `DoclingDocument` mock

**Error path return:** `mock_converter.convert.side_effect = Exception("corrupt PDF")`

**Used by modules:** `src/ingest/support/docling.py`, `src/ingest/doc_processing/nodes/structure_detection.py`

---

### Mock: HybridChunker (Docling)

**What it replaces:** `docling.chunking.HybridChunker` — structure-aware, token-aware chunker.

**Interface to mock:**
```python
from unittest.mock import MagicMock, patch

mock_chunker_instance = MagicMock()
mock_chunk = MagicMock()
mock_chunk.text = "Chunk content text."
mock_chunk.meta = MagicMock()
mock_chunk.meta.headings = ["Section 1"]
mock_chunker_instance.chunk.return_value = [mock_chunk]
MockHybridChunker = MagicMock(return_value=mock_chunker_instance)

with patch("src.ingest.embedding.nodes.chunking.HybridChunker", MockHybridChunker):
    ...
```

**Happy path return:** `HybridChunker(max_tokens=512).chunk(dl_doc=doc)` → list of chunk mocks

**Error path return:** `mock_chunker_instance.chunk.side_effect = ValueError("unsupported item")`

**Used by modules:** `src/ingest/embedding/nodes/chunking.py`

---

### Mock: LiteLLM Vision API

**What it replaces:** `litellm.completion()` — external vision model API call used by VLM enrichment.

**Interface to mock:**
```python
from unittest.mock import MagicMock, patch

mock_response = MagicMock()
mock_response.choices[0].message.content = "A diagram showing the system architecture."

with patch("src.ingest.embedding.nodes.vlm_enrichment.litellm.completion",
           return_value=mock_response):
    ...
```

**Happy path return:** Response with `choices[0].message.content` set to a description string

**Error path return:** `side_effect = Exception("API timeout after 60s")`

**Used by modules:** `src/ingest/embedding/nodes/vlm_enrichment.py`

---

### Mock: parse_with_docling

**What it replaces:** `src.ingest.support.docling.parse_with_docling` — used in `structure_detection.py` tests to decouple node tests from the Docling library.

**Interface to mock:**
```python
from unittest.mock import MagicMock, patch

mock_result = MagicMock()
mock_result.docling_document = MagicMock()
mock_result.text_markdown = "# Heading\n\nParagraph text."
mock_result.has_figures = False
mock_result.figures = []
mock_result.headings = ["Heading"]
mock_result.parser_model = "docling-parse-v2"

with patch("src.ingest.doc_processing.nodes.structure_detection.parse_with_docling",
           return_value=mock_result):
    ...
```

**Error path return:** `side_effect = RuntimeError("Docling conversion failed: corrupt PDF")`

**Used by modules:** `src/ingest/doc_processing/nodes/structure_detection.py`

---

## Per-Module Test Specifications

---

### `config/settings.py` — Environment Variable Definitions

**Module purpose:** Reads three new environment variables at import time and exposes them as typed module-level constants consumed by `IngestionConfig` defaults.

**In scope:**
- `RAG_INGESTION_VLM_MODE` → `str`, default `"disabled"`
- `RAG_INGESTION_HYBRID_CHUNKER_MAX_TOKENS` → `int`, default `512`
- `RAG_INGESTION_PERSIST_DOCLING_DOCUMENT` → `bool`, default `True`
- Type coercion: int cast for max_tokens, `.lower() in ("true", "1", "yes")` for bool

**Out of scope:**
- IngestionConfig field wiring (owned by `src/ingest/common/types.py`)
- Validation logic (`_check_docling_chunking_config` in `src/ingest/impl.py`)
- Any runtime configuration read after module import

#### Happy path scenarios

| Scenario | Input | Expected output |
|----------|-------|-----------------|
| No env vars set — all defaults | Environment clear of the three vars | `RAG_INGESTION_VLM_MODE == "disabled"`, `RAG_INGESTION_HYBRID_CHUNKER_MAX_TOKENS == 512`, `RAG_INGESTION_PERSIST_DOCLING_DOCUMENT == True` |
| VLM mode set to "external" | `RAG_INGESTION_VLM_MODE=external` | `RAG_INGESTION_VLM_MODE == "external"` |
| VLM mode set to "builtin" | `RAG_INGESTION_VLM_MODE=builtin` | `RAG_INGESTION_VLM_MODE == "builtin"` |
| Max tokens override | `RAG_INGESTION_HYBRID_CHUNKER_MAX_TOKENS=256` | `RAG_INGESTION_HYBRID_CHUNKER_MAX_TOKENS == 256` (int, not str) |
| Persist flag false via "false" | `RAG_INGESTION_PERSIST_DOCLING_DOCUMENT=false` | `RAG_INGESTION_PERSIST_DOCLING_DOCUMENT == False` |
| Persist flag false via "0" | `RAG_INGESTION_PERSIST_DOCLING_DOCUMENT=0` | `RAG_INGESTION_PERSIST_DOCLING_DOCUMENT == False` |
| Persist flag true via "yes" | `RAG_INGESTION_PERSIST_DOCLING_DOCUMENT=yes` | `RAG_INGESTION_PERSIST_DOCLING_DOCUMENT == True` |
| Persist flag true via "1" | `RAG_INGESTION_PERSIST_DOCLING_DOCUMENT=1` | `RAG_INGESTION_PERSIST_DOCLING_DOCUMENT == True` |

#### Error scenarios

| Error type | Trigger condition | Expected behavior |
|-----------|------------------|-------------------|
| `ValueError` | `RAG_INGESTION_HYBRID_CHUNKER_MAX_TOKENS=not_a_number` | `int(os.environ.get(...))` raises `ValueError` at module import time |

#### Boundary conditions

Derived from FR-2405, FR-2403, FR-2407, NFR-2905:

- `RAG_INGESTION_HYBRID_CHUNKER_MAX_TOKENS=0` → `0` (int zero — no validation here; validation is in impl.py)
- `RAG_INGESTION_HYBRID_CHUNKER_MAX_TOKENS=512` → `512` (at bge-m3 limit — valid int)
- `RAG_INGESTION_PERSIST_DOCLING_DOCUMENT=TRUE` (uppercase) → evaluated via `.lower()` → `True`
- `RAG_INGESTION_PERSIST_DOCLING_DOCUMENT=YES` (uppercase) → `True`
- `RAG_INGESTION_VLM_MODE=` (empty string) → `""` (empty string — not validated here)
- All three vars absent → all three return documented defaults

#### Integration points

- Consumed by `src/ingest/common/types.py` as default values for `IngestionConfig` fields
- No calls out to other modules — pure `os.environ.get()` reads

#### Known test gaps

- Testing env var reads requires module re-import or `importlib.reload()` because Python caches module-level constants. Tests must use `monkeypatch.setenv` + `importlib.reload(config.settings)` to observe changed values. This is an inherent Python module caching constraint, not a gap in the module itself.
- `RAG_INGESTION_VLM_MODE` with an invalid value (e.g., `"invalid"`) is not validated by settings.py — that validation belongs in `src/ingest/impl.py`. No test needed here for invalid values beyond confirming the string passes through unchanged.

#### Agent isolation contract (include verbatim in write-module-tests dispatch)

> **Agent isolation contract:** This agent receives ONLY:
> 1. This module test spec section
> 2. Phase 0 contract files (for import surface only — do not infer behavior from stubs)
>
> **Must NOT receive:** Source implementation files (`src/`), Phase B implementation code,
> other modules' test specs, or the engineering guide directly.

**Test file:** `tests/ingest/test_docling_chunking_settings.py`

---

### `src/ingest/common/types.py` — IngestionConfig New Fields

**Module purpose:** Owns the `IngestionConfig` dataclass and `PIPELINE_NODE_NAMES` list. This redesign appended three new fields (`vlm_mode`, `hybrid_chunker_max_tokens`, `persist_docling_document`) and inserted `"vlm_enrichment"` into `PIPELINE_NODE_NAMES` between `"chunking"` and `"chunk_enrichment"`.

**In scope:**
- `vlm_mode: str` field with default `"disabled"` (from `RAG_INGESTION_VLM_MODE`)
- `hybrid_chunker_max_tokens: int` field with default `512` (from `RAG_INGESTION_HYBRID_CHUNKER_MAX_TOKENS`)
- `persist_docling_document: bool` field with default `True` (from `RAG_INGESTION_PERSIST_DOCLING_DOCUMENT`)
- `PIPELINE_NODE_NAMES` list includes `"vlm_enrichment"` between `"chunking"` and `"chunk_enrichment"`
- Backward compatibility: all existing fields unchanged; defaults of new fields preserve pre-redesign behavior

**Out of scope:**
- Env var reads (owned by `config/settings.py`)
- Config validation logic (owned by `src/ingest/impl.py`)
- `DocumentProcessingState` and `EmbeddingPipelineState` TypedDicts (owned by their respective `state.py` files)

#### Happy path scenarios

| Scenario | Input | Expected output |
|----------|-------|-----------------|
| Default construction — all defaults | `IngestionConfig()` with no args | `vlm_mode == "disabled"`, `hybrid_chunker_max_tokens == 512`, `persist_docling_document == True` |
| Override vlm_mode | `IngestionConfig(vlm_mode="external")` | `vlm_mode == "external"` |
| Override max tokens | `IngestionConfig(hybrid_chunker_max_tokens=256)` | `hybrid_chunker_max_tokens == 256` |
| Override persist flag | `IngestionConfig(persist_docling_document=False)` | `persist_docling_document == False` |
| PIPELINE_NODE_NAMES ordering | inspect `PIPELINE_NODE_NAMES` | `"vlm_enrichment"` appears immediately after `"chunking"` and immediately before `"chunk_enrichment"` |

#### Error scenarios

| Error type | Trigger condition | Expected behavior |
|-----------|------------------|-------------------|
| No runtime errors | `IngestionConfig` is a dataclass with no `__post_init__` validation | Construction with any string/int/bool values succeeds without error — validation is delegated to `_check_docling_chunking_config` in `impl.py` |

#### Boundary conditions

Derived from FR-2401, FR-2403, FR-2407, NFR-2903:

- `IngestionConfig()` with no args → new fields all at documented defaults (backward-compat invariant per NFR-2903)
- `IngestionConfig(vlm_mode="builtin")` → `vlm_mode == "builtin"` (valid value stored without error)
- `IngestionConfig(hybrid_chunker_max_tokens=0)` → `hybrid_chunker_max_tokens == 0` (no validation in dataclass; impl.py handles it)
- `IngestionConfig(hybrid_chunker_max_tokens=513)` → `513` stored (warning emitted by impl.py, not here)
- All existing fields (e.g., `enable_docling_parser`, `docling_strict`) remain present and unchanged

#### Integration points

- Imports `RAG_INGESTION_VLM_MODE`, `RAG_INGESTION_HYBRID_CHUNKER_MAX_TOKENS`, `RAG_INGESTION_PERSIST_DOCLING_DOCUMENT` from `config.settings`
- Consumed by all pipeline nodes as their configuration object
- `PIPELINE_NODE_NAMES` consumed by `src/ingest/impl.py` for design checks and `processing_log` validation

#### Known test gaps

- Verifying that existing `IngestionConfig` fields (e.g., `ollama_url`, `enable_docling_parser`) are unchanged requires knowledge of the full pre-redesign field list. Tests should import `IngestionConfig` and verify presence of known pre-existing fields by name, but cannot exhaustively enumerate all fields without reading the source — which is forbidden. Gap: full backward-compat enumeration of existing fields.
- `PIPELINE_NODE_NAMES` is a module-level list constant. Its full ordered contents (all 14 node names) cannot be verified without knowing the pre-redesign list. Test can verify the relative ordering of `vlm_enrichment` among its neighbors.

#### Agent isolation contract (include verbatim in write-module-tests dispatch)

> **Agent isolation contract:** This agent receives ONLY:
> 1. This module test spec section
> 2. Phase 0 contract files (for import surface only — do not infer behavior from stubs)
>
> **Must NOT receive:** Source implementation files (`src/`), Phase B implementation code,
> other modules' test specs, or the engineering guide directly.

**Test file:** `tests/ingest/test_docling_chunking_types.py`

---

### `src/ingest/common/clean_store.py` — CleanDocumentStore (write_docling / read_docling)

**Module purpose:** The Phase 1/Phase 2 boundary store. Two new methods (`write_docling`, `read_docling`) were added, plus the existing `write()` method was extended with an optional `docling_document` parameter. The `delete()` method was extended to also remove `{key}.docling.json`.

**In scope:**
- `write_docling(source_key, docling_document)` — atomically serializes DoclingDocument to `{key}.docling.json` using tmp-then-rename, with envelope `{"_schema_version": "docling-native-v1", "document": {...}}`
- `read_docling(source_key)` — deserializes and returns DoclingDocument; returns `None` on missing file, invalid JSON, schema version mismatch, or missing docling-core dependency; logs warning on failure; never raises
- `write(source_key, text, meta, docling_document=None)` — extended: when `docling_document` is not None, calls `write_docling` after writing markdown+metadata; `write_docling` failure is non-fatal (logged at ERROR, markdown+metadata preserved)
- `delete(source_key)` — extended to also remove `{key}.docling.json` (silently ignores missing file)
- Serialization envelope format: `{"_schema_version": "docling-native-v1", "document": <model_dump_json output>}`
- Atomic write: `.docling.json.tmp` written first, then renamed into place

**Out of scope:**
- Markdown and metadata write logic (existing `write()` behavior — not changed)
- `DoclingDocument` content correctness (tested by docling library, not this module)
- Phase 2 state initialization (orchestrator concern)

#### Mock/Stub: DoclingDocument (for this module's tests)

**What it replaces:** `docling_core.types.doc.DoclingDocument` — the native Docling document object.

**Interface to mock:**
```python
# Minimal mock for write_docling tests:
mock_doc = MagicMock()
mock_doc.model_dump_json.return_value = '{"body": {"children": []}}'

# For read_docling tests: a real DoclingDocument deserialized from JSON,
# or a mock returned by DoclingDocument.model_validate_json()
```

**Happy path return:** `mock_doc.model_dump_json()` → `'{"body": {"children": []}}'`

**Error path returns:**
- `mock_doc.model_dump_json.side_effect = ValueError("unpicklable")` → triggers `ValueError` in `write_docling`
- `DoclingDocument.model_validate_json.side_effect = Exception("schema changed")` → triggers fallback to `None` in `read_docling`

#### Happy path scenarios

| Scenario | Input | Expected output |
|----------|-------|-----------------|
| write_docling succeeds | `source_key="doc1"`, valid `docling_document` mock | `{store_dir}/doc1.docling.json` exists; content is `{"_schema_version": "docling-native-v1", "document": {...}}`; no `.tmp` file left |
| read_docling finds existing file | `source_key="doc1"` with valid `.docling.json` written by write_docling | Returns deserialized DoclingDocument (or mock equivalent); does not raise |
| read_docling returns None for missing file | `source_key="nonexistent"` — no `.docling.json` file | Returns `None`; no exception; no warning logged |
| write() with docling_document calls write_docling | `write("doc1", text, meta, docling_document=mock_doc)` | All three files written: `.md`, `.meta.json`, `.docling.json` |
| write() without docling_document skips write_docling | `write("doc1", text, meta)` (no docling_document) | Only `.md` and `.meta.json` written; no `.docling.json` |
| delete() removes all three files | `delete("doc1")` when all three exist | All three files removed |

#### Error scenarios

| Error type | Trigger condition | Expected behavior |
|-----------|------------------|-------------------|
| `OSError` from `write_docling` | OS error on `.tmp` write or rename | `write_docling` raises `OSError` with message matching `"Failed to write DoclingDocument to {path}"` |
| `ValueError` from `write_docling` | `model_dump_json()` raises | `write_docling` raises `ValueError` with message matching `"Failed to serialize DoclingDocument"` |
| `write()` with write_docling failure | `write_docling` raises during `write()` | `.md` and `.meta.json` are preserved; error logged at ERROR level; `write()` does not re-raise |
| `read_docling` with invalid JSON | `.docling.json` contains `"not json{"` | Returns `None`; warning logged; no exception propagates |
| `read_docling` with schema version mismatch | `.docling.json` has `"_schema_version": "docling-native-v2"` (unknown version) | Returns `None`; warning logged |
| `read_docling` with missing docling-core | `DoclingDocument` import fails (`ImportError`) | Returns `None`; warning logged |
| `delete()` with missing `.docling.json` | Only `.md` and `.meta.json` exist | Removes the two present files; silently ignores missing `.docling.json`; no exception |

#### Boundary conditions

Derived from FR-2005, FR-2007, FR-2009, NFR-2911:

- `write_docling` leaves no `.tmp` file after successful write (atomic rename completes)
- `write_docling` leaves no `.docling.json` file if the rename fails mid-write (atomic guarantee)
- `read_docling` with `_schema_version` key present but value `"docling-native-v1"` → succeeds
- `read_docling` with `_schema_version` key absent → returns `None`, logs warning (malformed envelope)
- `read_docling` with `document` key absent but `_schema_version` correct → returns `None`, logs warning
- Source key with path-unsafe characters (e.g., `/`, `:`) → key is sanitized to safe filename (existing `clean_store` behavior — `.docling.json` must use same sanitization)

#### Integration points

- Called by `structure_detection_node` (Phase 1) to persist the DoclingDocument after processing
- Called by Phase 2 orchestrator via `read_docling()` to load DoclingDocument into `EmbeddingPipelineState`
- `write()` is the primary entry point for Phase 1 boundary writes; `write_docling` is also callable independently
- On `write_docling` failure: Phase 2 orchestrator will receive `None` from `read_docling` and use markdown fallback

#### Known test gaps

- Atomic write guarantee under concurrent access is difficult to test at unit level — requires integration or stress tests
- `DoclingDocument.model_validate_json()` behavior with a real (not mocked) `docling-core` library requires the `docling-core` package to be installed in the test environment — mark such tests with `@pytest.mark.requires_docling`
- The key sanitization behavior (for path-unsafe characters) is inherited from existing `CleanDocumentStore` logic; testing it for `.docling.json` is a regression guard, not a new behavior test

#### Agent isolation contract (include verbatim in write-module-tests dispatch)

> **Agent isolation contract:** This agent receives ONLY:
> 1. This module test spec section
> 2. Phase 0 contract files (for import surface only — do not infer behavior from stubs)
>
> **Must NOT receive:** Source implementation files (`src/`), Phase B implementation code,
> other modules' test specs, or the engineering guide directly.

**Test file:** `tests/ingest/test_docling_chunking_clean_store.py`

---

### `src/ingest/support/docling.py` — parse_with_docling + DoclingParseResult

**Module purpose:** Wraps the Docling library. `DoclingParseResult` gained a new `docling_document: Any` field. `parse_with_docling()` accepts a `vlm_mode` parameter; when `"builtin"`, configures SmolVLM picture description inside `DocumentConverter`. `warmup_docling_models()` accepts `with_smolvlm: bool` to optionally download SmolVLM artifacts.

**In scope:**
- `DoclingParseResult.docling_document` field is always set to the native `DoclingDocument` from `result.document` on success; `None` only in error recovery paths
- `parse_with_docling(file_path, config=..., vlm_mode="disabled")` — `vlm_mode` parameter dispatch: `"builtin"` → `PdfPipelineOptions(do_picture_description=True, ...)` before `DocumentConverter`; `"external"` or `"disabled"` → `do_picture_description=False`
- SmolVLM errors during builtin parse are caught and logged as warnings — parse continues without picture description (does not raise)
- `warmup_docling_models(artifacts_path="", with_smolvlm=False)` — when `with_smolvlm=True`, SmolVLM artifacts downloaded; when `False`, SmolVLM is NOT downloaded
- When `docling_strict=True` and conversion fails: raises `RuntimeError("Docling conversion failed: {detail}")`
- When `docling_strict=False` and conversion fails: returns a fallback result (with `docling_document=None`)

**Out of scope:**
- `structure_detection_node` routing logic (owned by `nodes/structure_detection.py`)
- `CleanDocumentStore` persistence (owned by `clean_store.py`)
- VLM enrichment post-chunking (owned by `vlm_enrichment.py`)

#### Mock/Stub: DocumentConverter (for this module's tests)

Uses the **Mock: DocumentConverter (Docling)** defined in the Mock/Stub Interface Specifications section above.

#### Happy path scenarios

| Scenario | Input | Expected output |
|----------|-------|-----------------|
| Successful parse, disabled VLM | `file_path=..., config=..., vlm_mode="disabled"` | Returns `DoclingParseResult` with `docling_document` set to `result.document`; `do_picture_description=False` |
| Successful parse, external VLM | `vlm_mode="external"` | Returns `DoclingParseResult` with `docling_document` set; `do_picture_description=False` (same as disabled at parse time) |
| Successful parse, builtin VLM | `vlm_mode="builtin"` | `DocumentConverter` constructed with `do_picture_description=True` and SmolVLM preset; `docling_document` populated |
| warmup with SmolVLM disabled | `warmup_docling_models(with_smolvlm=False)` | Returns artifacts path; SmolVLM download NOT triggered |
| warmup with SmolVLM enabled | `warmup_docling_models(with_smolvlm=True)` | Returns artifacts path; SmolVLM download triggered |

#### Error scenarios

| Error type | Trigger condition | Expected behavior |
|-----------|------------------|-------------------|
| `RuntimeError` | `DocumentConverter.convert()` raises AND `config.docling_strict=True` | `parse_with_docling` raises `RuntimeError("Docling conversion failed: ...")` |
| Fallback (non-strict) | `DocumentConverter.convert()` raises AND `config.docling_strict=False` | Returns `DoclingParseResult` with `docling_document=None`; does not raise |
| SmolVLM error during builtin parse | SmolVLM raises during picture description | Caught; logged as WARNING; parse continues; `docling_document` populated without picture descriptions |

#### Boundary conditions

Derived from FR-2001, FR-2211:

- `DoclingParseResult.docling_document` is never `None` when parse succeeds (regardless of `vlm_mode`)
- `parse_with_docling` with `vlm_mode="builtin"` → DocumentConverter receives `do_picture_description=True`
- `parse_with_docling` with `vlm_mode="disabled"` → DocumentConverter receives `do_picture_description=False`
- `parse_with_docling` with `vlm_mode="external"` → DocumentConverter receives `do_picture_description=False` (external enrichment is post-chunking, not at parse time)
- `warmup_docling_models(with_smolvlm=False)` → SmolVLM artifacts NOT downloaded (per FR-2211 AC)
- `warmup_docling_models(with_smolvlm=True)` → SmolVLM artifacts downloaded

#### Integration points

- Called by `structure_detection_node` with `vlm_mode=config.vlm_mode`
- Returns `DoclingParseResult` whose `.docling_document` is stored in `DocumentProcessingState`
- On `RuntimeError` (strict): `structure_detection_node` catches and sets `should_skip=True`
- On fallback (non-strict): `structure_detection_node` uses regex heuristics instead

#### Known test gaps

- Testing actual Docling model artifact downloads (`warmup_docling_models`) requires network access and disk space — mark as `@pytest.mark.integration` or `@pytest.mark.slow`; unit tests must mock the download call
- Testing SmolVLM picture description quality requires real SmolVLM artifacts — unit tests mock the `DocumentConverter` and verify only the configuration flags passed to it
- `parse_with_docling` with real PDF files: these are integration tests, not unit tests — unit tests mock `DocumentConverter.convert()`

#### Agent isolation contract (include verbatim in write-module-tests dispatch)

> **Agent isolation contract:** This agent receives ONLY:
> 1. This module test spec section
> 2. Phase 0 contract files (for import surface only — do not infer behavior from stubs)
>
> **Must NOT receive:** Source implementation files (`src/`), Phase B implementation code,
> other modules' test specs, or the engineering guide directly.

**Test file:** `tests/ingest/test_docling_chunking_parse.py`

---

### `src/ingest/doc_processing/nodes/structure_detection.py` — DoclingDocument Propagation

**Module purpose:** Sets the `structure["docling_document_available"]` routing flag and propagates the `DoclingDocument` object from `DoclingParseResult` into pipeline state. On successful Docling parse, stores `parsed.docling_document` in the returned state update under key `"docling_document"` and sets the flag to `True`. On failure (strict mode), returns `{"errors": [...], "should_skip": True}`. On failure (non-strict mode), falls back to regex heuristics, sets flag to `False`, and does NOT include `"docling_document"` in the state update.

**In scope:**
- State update key `"docling_document"` set to `parsed.docling_document` on success
- `structure["docling_document_available"] = True` on success
- `structure["docling_document_available"] = False` on fallback/disabled
- Strict mode failure: `{"errors": [...], "should_skip": True}` returned; `processing_log` ends with `structure_detection:failed`
- Non-strict mode failure: regex fallback runs; `docling_document` key ABSENT from state update
- `text_cleaning_node` and `document_refactoring_node` are skipped downstream when flag is `True` — this node sets the flag; routing tested here by verifying the flag value

**Out of scope:**
- `parse_with_docling` internals (mocked in these tests)
- `CleanDocumentStore.write()` (called by the broader pipeline, not directly by this node)
- Regex heuristics detail (FIGURE_PATTERN, HEADING_PATTERN) — pre-existing behavior, tested by existing tests

#### Mock/Stub: parse_with_docling (for this module's tests)

Uses the **Mock: parse_with_docling** defined in the Mock/Stub Interface Specifications section above.

#### Happy path scenarios

| Scenario | Input | Expected output |
|----------|-------|-----------------|
| Docling parse succeeds, Docling enabled | `state` with valid `source_path`; `config.enable_docling_parser=True`; mock returns DoclingParseResult with non-None `docling_document` | State update contains `"docling_document"` key with the mock document; `structure["docling_document_available"] == True` |
| Docling disabled in config | `config.enable_docling_parser=False` | State update does NOT contain `"docling_document"` key; `structure["docling_document_available"] == False`; regex fallback runs |

#### Error scenarios

| Error type | Trigger condition | Expected behavior |
|-----------|------------------|-------------------|
| Strict failure | `parse_with_docling` raises `RuntimeError`; `config.docling_strict=True` | Returns `{"errors": [...], "should_skip": True}`; `"docling_document"` NOT in returned update; `processing_log` ends with `structure_detection:failed` |
| Non-strict fallback | `parse_with_docling` raises; `config.docling_strict=False` | Falls back to regex; `"docling_document"` key ABSENT from state update; `structure["docling_document_available"] == False`; warning logged |

#### Boundary conditions

Derived from FR-2003, FR-2505:

- When parse succeeds: `state_update["docling_document"]` is the exact object returned by `parsed.docling_document` (identity check)
- When parse fails non-strict: `"docling_document"` key is absent (not present as `None`) — the key should not be explicitly set to `None`
- `structure["docling_document_available"]` is always a `bool` in the returned update (`True` or `False`, not truthy/falsy)
- `processing_log` on success contains an entry ending with `structure_detection:ok`
- `processing_log` on strict failure contains an entry ending with `structure_detection:failed`

#### Integration points

- Calls `parse_with_docling(file_path, config=config, vlm_mode=config.vlm_mode)` — mock this in all tests
- Returns `dict[str, Any]` as partial state update consumed by the Phase 1 LangGraph DAG
- Downstream routing in Phase 1 workflow reads `structure["docling_document_available"]` to skip `text_cleaning_node` and `document_refactoring_node`
- `docling_document` value flows to `CleanDocumentStore.write()` at Phase 1 boundary — not tested here

#### Known test gaps

- Testing the downstream routing skip behavior (text_cleaning, doc_refactoring skipped) requires integration testing with the full Phase 1 graph, not just this node in isolation
- Regex fallback behavior detail (FIGURE_PATTERN, HEADING_PATTERN, heading detection) is covered by existing pre-redesign tests; new tests here focus only on the Docling-path behavior

#### Agent isolation contract (include verbatim in write-module-tests dispatch)

> **Agent isolation contract:** This agent receives ONLY:
> 1. This module test spec section
> 2. Phase 0 contract files (for import surface only — do not infer behavior from stubs)
>
> **Must NOT receive:** Source implementation files (`src/`), Phase B implementation code,
> other modules' test specs, or the engineering guide directly.

**Test file:** `tests/ingest/doc_processing/test_docling_chunking_structure_detection.py`

---

### `src/ingest/embedding/nodes/chunking.py` — Dual-Path Chunking

**Module purpose:** Implements the dual-path chunking strategy. When `state["docling_document"]` is not `None`, attempts `HybridChunker`. On any `HybridChunker` exception, falls back to the markdown path non-fatally. When `state["docling_document"]` is `None`, uses the markdown fallback path directly. Both paths apply `_normalize_chunk_text()` to every chunk. The Docling path extracts `section_path`, `heading`, `heading_level` from `chunk.meta.headings` via `_extract_docling_section_metadata()`.

**In scope:**
- Path selection: `docling_document` not None → Docling path; `None` → markdown path
- Docling path: `HybridChunker(max_tokens=config.hybrid_chunker_max_tokens).chunk(dl_doc=...)` → `ProcessedChunk` list
- `_extract_docling_section_metadata(chunk)` → `section_path`, `heading`, `heading_level` from `chunk.meta.headings`
- `_normalize_chunk_text(text)` applied to every chunk text (NFC normalization + control char removal) on both paths
- `processing_log` entries: `"hybrid_chunker:ok"` (Docling success), `"hybrid_chunker:error"` + `"chunking:fallback_to_markdown"` (Docling failure), `"chunking:markdown_fallback"` (no docling_document)
- HybridChunker exception → fallback to markdown (non-fatal); outer exception → `{"errors": [...]}` (fatal for document)
- Output `ProcessedChunk` metadata schema: `source`, `source_uri`, `source_key`, `source_id`, `connector`, `source_version`, `section_path`, `heading`, `heading_level`, `chunk_index`, `total_chunks`

**Out of scope:**
- VLM enrichment (owned by `vlm_enrichment.py`)
- Semantic splitting behavior (pre-redesign path; not called for Docling documents)
- Embedding storage and downstream nodes

#### Mock/Stub: HybridChunker (for this module's tests)

Uses the **Mock: HybridChunker (Docling)** defined in the Mock/Stub Interface Specifications section above.

#### Happy path scenarios

| Scenario | Input | Expected output |
|----------|-------|-----------------|
| Docling path — single chunk | `state["docling_document"]` = mock doc; HybridChunker returns 1 chunk | Returns `{"chunks": [ProcessedChunk(...)]}` with `section_path="Chapter 1 > Background"`, `heading="Background"`, `heading_level=2`; `processing_log` contains `"hybrid_chunker:ok"` |
| Docling path — multiple chunks | HybridChunker returns 3 chunks | All 3 ProcessedChunks in output; `chunk_index` in [0,1,2]; `total_chunks=3` |
| Docling path — chunk with no headings | `mock_chunk.meta.headings = []` | `section_path=""`, `heading=""`, `heading_level=0` |
| Markdown fallback — no docling_document | `state["docling_document"] = None` | Markdown path runs; `processing_log` contains `"chunking:markdown_fallback"`; `ProcessedChunk` list returned |
| NFC normalization applied | Chunk text contains `"caf\u0065\u0301"` (NFD "café") | Output chunk text is NFC-normalized `"café"` (single code point) |
| Control char removal | Chunk text contains `"\x00hello\x1fworld"` | Output is `"helloworld"` (control chars removed, newlines preserved) |

#### Error scenarios

| Error type | Trigger condition | Expected behavior |
|-----------|------------------|-------------------|
| HybridChunker raises ValueError | `HybridChunker.chunk()` raises `ValueError`; `docling_document` not None | Falls back to markdown path; `processing_log` contains `"hybrid_chunker:error"` AND `"chunking:fallback_to_markdown"`; valid chunks returned |
| HybridChunker raises RuntimeError | `HybridChunker.chunk()` raises `RuntimeError` | Same fallback behavior as ValueError |
| Outer exception (metadata assembly fails) | `base_metadata` construction raises | Returns `{"errors": [...], "processing_log": updated}`; no chunks produced |

#### Boundary conditions

Derived from FR-2101, FR-2111, FR-2305, FR-2307, FR-2015:

- `state["docling_document"] = None` → markdown path, regardless of config flags (FR-2307)
- `state["docling_document"] = <valid mock>` → Docling path attempted first
- `chunk_index` is 0-based; `total_chunks` equals `len(chunks)`
- Empty chunk list from HybridChunker → returns `{"chunks": []}` (valid empty list, not an error)
- `_normalize_chunk_text("")` → `""` (empty string passes through)
- `_normalize_chunk_text("\n\r")` → `"\n\r"` (newlines preserved)
- `_normalize_chunk_text("\x00")` → `""` (null byte removed)
- `_extract_docling_section_metadata` with `chunk.meta = None` → `section_path=""`, `heading=""`, `heading_level=0`
- `_extract_docling_section_metadata` with `chunk.meta.headings = ["Top"]` → `section_path="Top"`, `heading="Top"`, `heading_level=1`
- `_extract_docling_section_metadata` with `chunk.meta.headings = ["A", "B", "C"]` → `section_path="A > B > C"`, `heading="C"`, `heading_level=3`

#### Integration points

- Reads `state["docling_document"]` (set by Phase 2 orchestrator from `CleanDocumentStore.read_docling()`)
- Reads `state["config"]` for `hybrid_chunker_max_tokens`
- Returns `{"chunks": list[ProcessedChunk], "processing_log": updated}`
- Consumed downstream by `vlm_enrichment_node`, `chunk_enrichment_node`, `metadata_generation_node`
- On HybridChunker import failure (docling not installed): mock as `ImportError` — chunking_node must catch and fall back to markdown

#### Known test gaps

- Testing that HybridChunker respects document item boundaries (no table rows split mid-cell) requires a real `DoclingDocument` with table items — integration test only
- Testing `semchunk` internal forced splitting behavior (FR-2109) requires an oversized item in a real `DoclingDocument` — integration test only
- `_semantic_split` is NOT called for Docling-path documents (FR-2109 AC): verifying this requires `patch` + `assert_not_called()`

#### Agent isolation contract (include verbatim in write-module-tests dispatch)

> **Agent isolation contract:** This agent receives ONLY:
> 1. This module test spec section
> 2. Phase 0 contract files (for import surface only — do not infer behavior from stubs)
>
> **Must NOT receive:** Source implementation files (`src/`), Phase B implementation code,
> other modules' test specs, or the engineering guide directly.

**Test file:** `tests/ingest/embedding/test_docling_chunking_node.py`

---

### `src/ingest/embedding/nodes/vlm_enrichment.py` — External VLM Post-Chunking Enrichment

**Module purpose:** Post-chunking VLM enrichment node. For `vlm_mode="external"`: scans each chunk's text for `![alt](src)` image placeholders, calls LiteLLM vision model per placeholder, replaces placeholder with VLM description. Respects `vision_max_figures` per-document budget. Per-chunk and per-placeholder failures are non-fatal. For `vlm_mode="builtin"` or `"disabled"`: immediate no-op. The node never raises — all exceptions are caught at the outer level and the original chunks are returned.

**In scope:**
- `vlm_enrichment_node(state)` — mode dispatch; no-op for disabled/builtin; active for external
- `_find_image_placeholders(chunk_text)` — detects `![alt](src)` patterns using `_IMAGE_REF_PATTERN`
- `_replace_placeholder(chunk_text, match, description)` — replaces matched span with description; preserves surrounding text
- `_enrich_chunk_external(chunk, config, figures_processed_count)` — per-chunk enrichment; respects `vision_max_figures`; returns `(original_chunk, count)` on failure or budget exceeded
- `processing_log` entries: `"vlm_enrichment:skipped"` (disabled/builtin), `"vlm_enrichment:external:ok"` or `"vlm_enrichment:external:error"` for external mode
- Per-placeholder VLM failure: placeholder preserved in chunk text; WARNING logged; continues to next placeholder
- Outer unexpected exception: ERROR logged; original chunks returned unchanged

**Out of scope:**
- Builtin SmolVLM behavior (runs inside `parse_with_docling` at parse time, not here)
- Chunk splitting or chunk metadata (owned by `chunking.py`)
- LiteLLM routing configuration

#### Mock/Stub: LiteLLM Vision API (for this module's tests)

Uses the **Mock: LiteLLM Vision API** defined in the Mock/Stub Interface Specifications section above.

#### Happy path scenarios

| Scenario | Input | Expected output |
|----------|-------|-----------------|
| vlm_mode="disabled" | `state["config"].vlm_mode = "disabled"`, any chunks | Returns chunks unchanged; `processing_log` contains `"vlm_enrichment:skipped"` |
| vlm_mode="builtin" | `state["config"].vlm_mode = "builtin"`, any chunks | Returns chunks unchanged; `processing_log` contains `"vlm_enrichment:skipped"` |
| vlm_mode="external", no placeholders | `vlm_mode="external"`, chunks without `![...]()` patterns | Returns chunks unchanged; no LiteLLM calls made |
| vlm_mode="external", one placeholder replaced | Chunk text `"Some text ![Fig 1](img.png) more text"`, VLM returns `"a bar chart"` | Output chunk text `"Some text a bar chart more text"`; LiteLLM called once |
| vision_max_figures budget respected | 5 chunks each with 1 placeholder; `vision_max_figures=3` | First 3 placeholders replaced; chunks 4 and 5 placeholders left unchanged |
| _replace_placeholder preserves surrounding text | `"before ![x](y) after"` with description `"desc"` | Output is `"before desc after"` — no other text altered |

#### Error scenarios

| Error type | Trigger condition | Expected behavior |
|-----------|------------------|-------------------|
| LiteLLM API error | `litellm.completion()` raises `Exception("timeout")` | Original placeholder preserved in chunk; WARNING logged; continues to next chunk; node returns all chunks |
| vision_max_figures=0 | `config.vision_max_figures=0` | All placeholders left unchanged; zero LiteLLM calls made |
| Outer unexpected exception | Something outside per-chunk loop raises unexpectedly | ERROR logged; original (pre-enrichment) chunks returned unchanged; node does not raise |

#### Boundary conditions

Derived from FR-2201, FR-2205, FR-2207, FR-2209:

- `_find_image_placeholders("")` → empty list (no matches)
- `_find_image_placeholders("no images here")` → empty list
- `_find_image_placeholders("![alt](path.png)")` → 1 match
- `_find_image_placeholders("![a](b.png) and ![c](d.png)")` → 2 matches
- `_replace_placeholder("![a](b)", match, "desc")` → `"desc"` (full string replaced with description)
- Text before and after placeholder is character-exact after replacement (no surrounding whitespace changes)
- `vision_max_figures=1` with 3-figure document → only first figure replaced; remaining 2 left as-is
- Empty `chunks` list → returns empty list; no iterations; no errors

#### Integration points

- Reads `state["chunks"]` (list of `ProcessedChunk`) produced by `chunking_node`
- Reads `state["config"]` for `vlm_mode`, `vision_max_figures`, `vision_max_image_bytes`, `vision_timeout_seconds`, `vision_max_tokens`, `vision_temperature`
- Calls `_IMAGE_REF_PATTERN` from `src/ingest/support/vision.py` (imported) — mock this pattern if needed to inject custom image references
- Returns `{"chunks": list[ProcessedChunk], "processing_log": updated}`
- Called after `chunking_node`, before `chunk_enrichment_node` in Phase 2 graph

#### Known test gaps

- `vision_strict=True` behavior (stop enrichment on VLM failure vs. continue) — the EG specifies `vision_strict` as a config field but does not specify `vlm_enrichment_node`'s behavior when `vision_strict=True`. Testing this requires reading the source — known gap: `vision_strict` behavior in this node is not documented in the EG. No tests written for `vision_strict=True` scenarios.
- Testing with real LiteLLM routing to a live vision model — integration test only; unit tests mock `litellm.completion`
- Testing image byte size validation (`vision_max_image_bytes`) requires understanding how the image bytes are loaded from the placeholder path — this detail is not specified in the EG for this module. Known gap.

#### Agent isolation contract (include verbatim in write-module-tests dispatch)

> **Agent isolation contract:** This agent receives ONLY:
> 1. This module test spec section
> 2. Phase 0 contract files (for import surface only — do not infer behavior from stubs)
>
> **Must NOT receive:** Source implementation files (`src/`), Phase B implementation code,
> other modules' test specs, or the engineering guide directly.

**Test file:** `tests/ingest/embedding/test_docling_chunking_vlm_enrichment.py`

---

### `src/ingest/impl.py` — Design Checks (`_check_docling_chunking_config`)

**Module purpose:** `verify_core_design(config)` calls `_check_docling_chunking_config(config)`, which enforces four rules:
1. `vlm_mode` must be one of `{"disabled", "builtin", "external"}` — hard error
2. `vlm_mode="builtin"` and `docling` not installed — hard error
3. `vlm_mode="external"` without vision model or router config — warning only
4. `hybrid_chunker_max_tokens > 512` — warning only

`_check_docling_chunking_config` returns `(errors: list[str], warnings: list[str])`. Hard errors prevent pipeline start. Warnings are logged but do not halt.

**In scope:**
- `_check_docling_chunking_config(config)` → `(list[str], list[str])` return contract
- Invalid `vlm_mode` → error message contains `"vlm_mode=... is not valid; must be one of [...]"`
- `vlm_mode="builtin"` + docling not installed → error message contains `"vlm_mode=builtin requires docling to be installed"`
- `vlm_mode="external"` without vision config → warning message contains `"vlm_mode=external"` and reference to skipping
- `hybrid_chunker_max_tokens > 512` → warning message contains `"hybrid_chunker_max_tokens"` and `"512"`
- `vlm_mode="disabled"` + any `hybrid_chunker_max_tokens <= 512` → no errors, no warnings
- `verify_core_design(config)` calls `_check_docling_chunking_config` and raises (or returns errors) when errors are non-empty

**Out of scope:**
- Pipeline orchestration (the full `verify_core_design` beyond design check delegation)
- Other design check functions not added in this redesign

#### Mock/Stub: docling import check (for this module's tests)

**What it replaces:** The import-time check for whether `docling` is installed.

**Interface to mock:**
```python
from unittest.mock import patch

# Simulate docling NOT installed:
with patch.dict("sys.modules", {"docling": None, "docling.document_converter": None}):
    ...

# Simulate docling installed:
# No patch needed — if docling is present in the test environment, no mock needed.
# Otherwise: provide a minimal module stub.
```

#### Happy path scenarios

| Scenario | Input | Expected output |
|----------|-------|-----------------|
| All valid, disabled VLM | `IngestionConfig(vlm_mode="disabled", hybrid_chunker_max_tokens=512)` | `errors=[]`, `warnings=[]` |
| Valid builtin, docling installed | `IngestionConfig(vlm_mode="builtin")`, docling importable | `errors=[]` |
| Valid external, vision model configured | `IngestionConfig(vlm_mode="external")`, vision model set | `errors=[]`, 0 warnings about external config |
| max_tokens at limit | `hybrid_chunker_max_tokens=512` | No warning for 512 (at limit, not above) |
| max_tokens below limit | `hybrid_chunker_max_tokens=256` | No warning |

#### Error scenarios

| Error type | Trigger condition | Expected behavior |
|-----------|------------------|-------------------|
| Invalid vlm_mode | `IngestionConfig(vlm_mode="invalid_mode")` | `errors` list is non-empty; error message contains `"vlm_mode=invalid_mode"` and `"not valid"` |
| builtin without docling | `vlm_mode="builtin"`, docling not installed (mocked) | `errors` list non-empty; message contains `"vlm_mode=builtin requires docling"` |
| external without vision config | `vlm_mode="external"`, no vision model env var | `warnings` list non-empty; `errors` is empty; warning message contains `"vlm_mode=external"` |
| max_tokens exceeds limit | `hybrid_chunker_max_tokens=1024` | `warnings` list non-empty; `errors` is empty; warning message contains `"hybrid_chunker_max_tokens"` |
| max_tokens at exactly 513 | `hybrid_chunker_max_tokens=513` | `warnings` list non-empty (513 > 512) |

#### Boundary conditions

Derived from FR-2409, EG Section 4.4:

- `vlm_mode=""` (empty string) → in `errors` (not one of the valid set)
- `vlm_mode="DISABLED"` (uppercase) → in `errors` (case-sensitive comparison)
- `hybrid_chunker_max_tokens=512` → no warning (at limit, not over)
- `hybrid_chunker_max_tokens=513` → warning
- `hybrid_chunker_max_tokens=1` → no warning (valid low value)
- `vlm_mode="builtin"` with docling installed → no error for this check
- Multiple invalid conditions simultaneously → both errors returned in the same list

#### Integration points

- Called by `verify_core_design(config)` which is invoked at pipeline start
- Returns `(errors, warnings)` — caller raises or records design check failure if `errors` is non-empty
- Depends on `IngestionConfig` fields: `vlm_mode`, `hybrid_chunker_max_tokens`, (and implicitly vision model config for external mode check)

#### Known test gaps

- `vlm_mode="external"` warning logic depends on how the "no vision model configured" condition is detected — the EG says "no vision model or router config" but the exact condition (env var check, config field presence, etc.) is not specified in the EG for this function. Known gap: exact condition for the external warning. Tests verify the warning IS produced when vision model is not configured; exact trigger criterion needs EG clarification.
- Testing `verify_core_design` raising the design check exception requires knowing the exception class name — the EG mentions raising on errors, but the exception class is not confirmed from Phase 0 contracts alone. Known gap.

#### Agent isolation contract (include verbatim in write-module-tests dispatch)

> **Agent isolation contract:** This agent receives ONLY:
> 1. This module test spec section
> 2. Phase 0 contract files (for import surface only — do not infer behavior from stubs)
>
> **Must NOT receive:** Source implementation files (`src/`), Phase B implementation code,
> other modules' test specs, or the engineering guide directly.

**Test file:** `tests/ingest/test_docling_chunking_design_checks.py`

---

### `src/ingest/doc_processing/nodes/structure_detection.py` — Input Format Routing

**Module purpose:** Validates that different input file formats route correctly through the ingestion pipeline — Docling-supported formats go through the native HybridChunker path, unsupported formats fall back to the regex/markdown pipeline, and format errors are distinguished from real parser failures.

**In scope:**
- Format routing: supported extensions (`.md`, `.pdf`, `.docx`, `.pptx`, `.html`, `.csv`, `.xlsx`, `.asciidoc`, `.latex`) → Docling native path
- Format routing: unsupported extensions (`.txt`, `.log`, `.json`, `.yaml`, `.yml`, `.ini`, `.cfg`, `.toml`) → regex/markdown fallback
- Format error vs parser error distinction under `docling_strict=True`
- Docling disabled → all formats use regex

**Out of scope:**
- Actual Docling parsing behavior (mocked — covered by module 4)
- Chunk quality from either path (covered by module 6)
- VLM enrichment (covered by module 7)

#### Happy path scenarios

| Scenario | Input | Expected output |
|----------|-------|-----------------|
| Supported format uses Docling | `test_doc.md` with mocked successful parse | `docling_document_available=True`, `docling_document` present |
| Supported format calls parse_with_docling | `test_doc.pdf` | `parse_with_docling` called exactly once |
| Disabled Docling skips all formats | `doc.md` with `enable_docling_parser=False` | `parse_with_docling` never called, `docling_document_available=False` |

#### Error scenarios

| Error type | Trigger condition | Expected behavior |
|-----------|------------------|-------------------|
| Format not supported (strict) | `parse_with_docling` raises `RuntimeError("File format not allowed: data.txt")` with `docling_strict=True` | Falls back to regex — does NOT set `should_skip=True` |
| Format not supported (non-strict) | Same error with `docling_strict=False` | Falls back to regex |
| Real parser error (strict) | `parse_with_docling` raises `RuntimeError("Segfault in PDF parser")` with `docling_strict=True` | Sets `should_skip=True`, error in `errors` list |
| Real parser error (non-strict) | Same error with `docling_strict=False` | Falls back to regex, does NOT skip |

#### Boundary conditions

- Unsupported format with `docling_strict=True` → fallback (not skip) — format errors are not parser bugs
- Fallback path preserves original `raw_text` unchanged
- Fallback path still extracts headings and figure references via regex
- Format error and parser error produce different outcomes in strict mode (explicitly tested)

#### Integration points

- Calls `parse_with_docling()` — mocked for all tests
- Returns state update consumed by downstream nodes (`text_cleaning_node`, `chunking_node`)

#### Known test gaps

- Does not test actual Docling format detection (e.g., Docling misidentifying a `.txt` as `xml_uspto`) — would require live Docling, covered by integration tests only
- Does not verify the exact error message format from Docling across versions

#### Agent isolation contract

> **Agent isolation contract:** This agent receives ONLY:
> 1. This module test spec section
> 2. Phase 0 contract files (for import surface only — do not infer behavior from stubs)
>
> **Must NOT receive:** Source implementation files (`src/`), Phase B implementation code,
> other modules' test specs, or the engineering guide directly.

**Test file:** `tests/ingest/test_input_format_routing.py`

---

## Integration Test Specifications

These tests span the Phase 1/Phase 2 boundary and exercise multiple modules together. They complement unit tests by verifying end-to-end data flow and cross-module contracts.

---

### Integration: Happy Path — Docling Document Through Full Pipeline

**Scenario:** A PDF document is parsed by Docling, the DoclingDocument survives the Phase 1/Phase 2 boundary via CleanDocumentStore, and HybridChunker produces structure-aware chunks in Phase 2.

**Entry point:** `structure_detection_node(state)` (Phase 1) → `CleanDocumentStore.write()` → `CleanDocumentStore.read_docling()` (Phase 2 init) → `chunking_node(state)` → `vlm_enrichment_node(state)` (no-op, disabled)

**Flow:**
1. `structure_detection_node` calls `parse_with_docling(file_path, config, vlm_mode="disabled")` → `DoclingParseResult` with `docling_document=mock_doc`
2. Node sets `state["docling_document"] = mock_doc` and `structure["docling_document_available"] = True`
3. `CleanDocumentStore.write(key, text, meta, docling_document=mock_doc)` writes `.md`, `.meta.json`, `.docling.json`
4. Phase 2 init: `CleanDocumentStore.read_docling(key)` returns the deserialized DoclingDocument → stored in `EmbeddingPipelineState["docling_document"]`
5. `chunking_node(state)` sees `docling_document` is not None → calls `HybridChunker(max_tokens=512).chunk(dl_doc=...)` → returns 2 chunks
6. `vlm_enrichment_node(state)` with `vlm_mode="disabled"` → no-op; chunks pass through unchanged
7. Final output: 2 `ProcessedChunk` objects with `section_path`, `chunk_index`, `total_chunks` populated

**What to assert:**
- `state["structure"]["docling_document_available"]` is `True` after `structure_detection_node`
- `state["docling_document"]` is not `None` after `structure_detection_node`
- `.docling.json` file exists in `CleanDocumentStore` directory
- After `read_docling()`, `EmbeddingPipelineState["docling_document"]` is not `None`
- `chunking_node` output `chunks` has length 2
- `chunks[0].metadata["section_path"]` is non-empty string
- `chunks[0].metadata["chunk_index"] == 0`, `chunks[0].metadata["total_chunks"] == 2`
- `processing_log` contains `"hybrid_chunker:ok"` and does NOT contain `"chunking:fallback_to_markdown"`
- `processing_log` contains `"vlm_enrichment:skipped"`

**Mocks required:** Mock: DocumentConverter (Docling), Mock: HybridChunker (Docling)

---

### Integration: Error Path — HybridChunker Failure Falls Back to Markdown

**Scenario:** DoclingDocument is present in Phase 2 state, but HybridChunker raises an exception. The pipeline falls back to the markdown path non-fatally and produces valid chunks.

**Entry point:** `chunking_node(state)` with `state["docling_document"]` not None and HybridChunker mocked to raise.

**Flow:**
1. `chunking_node` reads `state["docling_document"]` → not None → Docling path
2. `HybridChunker.chunk()` raises `ValueError("unsupported item type")`
3. `chunking_node` catches exception, logs `"hybrid_chunker:error"`, logs `"chunking:fallback_to_markdown"`
4. Falls back to `_chunk_with_markdown(state, config, base_metadata)` — produces chunks from markdown text
5. `vlm_enrichment_node` runs (no-op for disabled mode)
6. Final output: valid `ProcessedChunk` list from markdown path

**What to assert:**
- `chunking_node` does NOT raise (non-fatal)
- `output["chunks"]` is a non-empty list of `ProcessedChunk` objects
- `processing_log` contains `"hybrid_chunker:error"`
- `processing_log` contains `"chunking:fallback_to_markdown"`
- `processing_log` does NOT contain `"hybrid_chunker:ok"`
- Chunks have valid `ProcessedChunk` metadata (all required fields present: `source`, `source_uri`, `source_key`, etc.)

**Mocks required:** Mock: HybridChunker (Docling) (mocked to raise)

---

### Integration: Error Path — Corrupt DoclingDocument JSON at Phase 2 Init

**Scenario:** Phase 1 writes a `.docling.json` file, but the file becomes corrupt between Phase 1 and Phase 2. `CleanDocumentStore.read_docling()` returns `None`, and Phase 2 uses markdown fallback.

**Entry point:** `CleanDocumentStore.read_docling(source_key)` with a corrupt `.docling.json` file → `chunking_node(state)` with `docling_document=None`

**Flow:**
1. `.docling.json` file exists at store path but contains invalid JSON (`"not json{"`)
2. `read_docling(source_key)` catches `json.JSONDecodeError`, logs warning, returns `None`
3. Phase 2 orchestrator sets `EmbeddingPipelineState["docling_document"] = None`
4. `chunking_node(state)` sees `docling_document` is `None` → markdown fallback path
5. `processing_log` records `"chunking:markdown_fallback"`
6. Output: valid `ProcessedChunk` list from markdown path

**What to assert:**
- `read_docling()` returns `None` (no exception raised)
- A warning is logged (check log capture for warning-level message referencing the source key)
- `chunking_node` output `processing_log` contains `"chunking:markdown_fallback"`
- `output["chunks"]` is a valid non-empty list
- No `"errors"` key in `chunking_node` output

**Mocks required:** None (uses real `CleanDocumentStore` with a tmp directory fixture and a written-then-corrupted file)

---

### Integration: Happy Path — External VLM Enrichment Replaces Placeholders

**Scenario:** `vlm_mode="external"`. `chunking_node` produces chunks with image placeholders. `vlm_enrichment_node` replaces placeholders with VLM descriptions via mocked LiteLLM.

**Entry point:** `vlm_enrichment_node(state)` with chunks containing `![Figure 1](fig1.png)`

**Flow:**
1. `chunking_node` produces 3 chunks; chunk index 1 contains `"See ![Figure 1](fig1.png) for details."`
2. `vlm_enrichment_node` with `vlm_mode="external"` and `vision_max_figures=4`
3. Detects placeholder in chunk 1
4. Calls `_enrich_chunk_external(chunk_1, config, figures_processed_count=0)`
5. Mocked LiteLLM returns `"a system architecture diagram"`
6. Chunk 1 text becomes `"See a system architecture diagram for details."`
7. Chunks 0 and 2 (no placeholders) pass through unchanged

**What to assert:**
- `output["chunks"][1].text == "See a system architecture diagram for details."`
- `output["chunks"][0].text` unchanged from input
- `output["chunks"][2].text` unchanged from input
- LiteLLM mock called exactly once

**Mocks required:** Mock: LiteLLM Vision API

---

### Integration: Fallback Path — Non-Docling Document Uses Markdown Pipeline

**Scenario:** `structure_detection_node` runs with `enable_docling_parser=False`. No DoclingDocument is produced. Phase 2 uses markdown chunking. `text_cleaning_node` and `document_refactoring_node` run normally.

**Entry point:** `structure_detection_node(state)` with `config.enable_docling_parser=False`

**Flow:**
1. `structure_detection_node` runs regex heuristics (Docling disabled)
2. `structure["docling_document_available"] = False`; `"docling_document"` key absent from state update
3. Phase 1 routing: `text_cleaning_node` runs; `document_refactoring_node` runs (if enabled)
4. `CleanDocumentStore.write(key, text, meta)` — no `docling_document` arg → no `.docling.json` written
5. `CleanDocumentStore.read_docling(key)` returns `None` (no file)
6. `chunking_node` with `docling_document=None` → markdown fallback path
7. `processing_log` contains `"chunking:markdown_fallback"` and NOT `"hybrid_chunker:ok"`

**What to assert:**
- No `.docling.json` file exists after Phase 1 write
- `read_docling()` returns `None`
- `chunking_node` `processing_log` contains `"chunking:markdown_fallback"`
- `chunks` is a valid `ProcessedChunk` list

**Mocks required:** None for this scenario (Docling path disabled, no Docling mocks needed)

---

### Integration: Docling Parse Failure (Strict Mode) Halts Document

**Scenario:** Docling parsing fails with `docling_strict=True` due to a real parser error (not a format error). `structure_detection_node` returns `should_skip=True`. Document does not proceed to Phase 2.

**Entry point:** `structure_detection_node(state)` with `config.docling_strict=True` and mocked `parse_with_docling` that raises.

**Flow:**
1. `parse_with_docling()` raises `RuntimeError("Docling conversion failed: password protected")`
2. `structure_detection_node` catches, identifies this as a real parser error (not format), returns `{"errors": ["..."], "should_skip": True}`
3. Phase 1 workflow routes to end — document skipped

**What to assert:**
- Return value contains `"should_skip": True`
- Return value contains non-empty `"errors"` list
- `"docling_document"` key NOT in return value
- `structure["docling_document_available"]` is `False` or key absent

**Mocks required:** Mock: parse_with_docling (mocked to raise RuntimeError)

---

### Integration: Unsupported Format Falls Back (Even in Strict Mode)

**Scenario:** A `.txt` file is ingested with `docling_strict=True`. Docling raises "File format not allowed". The pipeline recognizes this as a format limitation (not a parser bug) and falls back to regex/markdown pipeline instead of halting.

**Entry point:** `structure_detection_node(state)` with `config.docling_strict=True` and a `.txt` source file.

**Flow:**
1. `parse_with_docling()` raises `RuntimeError("File format not allowed: notes.txt")`
2. `structure_detection_node` catches, identifies the error as a format error
3. Falls back to regex heuristics — extracts headings and figures from `raw_text`
4. `structure["docling_document_available"] = False`; `"docling_document"` absent
5. Phase 2: `chunking_node` with `docling_document=None` → markdown fallback path
6. `processing_log` contains `"structure_detection:ok"` and `"chunking:markdown_fallback"`

**What to assert:**
- `should_skip` is NOT True (document is not halted)
- `structure["docling_document_available"]` is `False`
- Regex heuristics still extract headings/figures from raw text
- Chunks are produced via markdown fallback path
- `processing_log` does not contain `"structure_detection:failed"`

**Mocks required:** Mock: parse_with_docling (mocked to raise RuntimeError with "File format not allowed")

**Distinction from "Docling Parse Failure" scenario:** This scenario tests that format errors are NOT treated as parser bugs. A format error with `docling_strict=True` must fall back, not halt.

---

## FR-to-Test Traceability Matrix

Every FR and NFR from the spec appears below. If a requirement is not covered, it is explicitly noted as a known gap with the reason.

| FR | Priority | Acceptance Criteria Summary | Module Test | Integration Test |
|----|----------|-----------------------------|-------------|-----------------|
| FR-2001 | MUST | `DoclingParseResult.docling_document` non-None after successful parse; None when disabled | `support/docling.py` — happy path (all vlm_modes) | integration_happy_path |
| FR-2003 | MUST | `structure_detection_node` stores `docling_document` in state on success; absent on fallback | `structure_detection.py` — happy path, non-strict fallback | integration_happy_path |
| FR-2005 | MUST | `CleanDocumentStore.write()` persists `.docling.json`; `read_docling()` returns DoclingDocument | `clean_store.py` — write/read happy paths | integration_happy_path (store boundary) |
| FR-2007 | MUST | `.docling.json` written atomically via tmp-then-rename | `clean_store.py` — boundary condition (no .tmp left after success) | Not covered at integration level — unit boundary is sufficient |
| FR-2009 | SHOULD | `persist_docling_document=false` → no `.docling.json` written; Phase 2 uses markdown fallback | `clean_store.py` — `write()` without `docling_document` | integration_fallback_nondocling |
| FR-2011 | MUST | Docling-path documents skip `text_cleaning_node` | `structure_detection.py` — flag set True correctly | integration_happy_path (assert no text_cleaning in log) |
| FR-2013 | MUST | Docling-path documents skip `document_refactoring_node` | `structure_detection.py` — flag set True correctly | integration_happy_path (assert no doc_refactoring in log) |
| FR-2015 | MUST | NFC normalization and control char removal on every chunk, both paths | `chunking.py` — NFC and control char boundary conditions | integration_happy_path (verify output chunk text) |
| FR-2101 | MUST | `chunking_node` uses HybridChunker when `docling_document` not None | `chunking.py` — Docling path happy path | integration_happy_path |
| FR-2103 | MUST | HybridChunker configured with `max_tokens` from config; no chunk exceeds limit | `chunking.py` — HybridChunker instantiated with correct max_tokens | Known gap: asserting no chunk exceeds token limit requires real HybridChunker — integration test only |
| FR-2105 | MUST | Each chunk has `section_path` from heading hierarchy | `chunking.py` — section_path extraction scenarios | integration_happy_path |
| FR-2107 | MUST | Multi-chunk tables include header row in every chunk | Known gap: requires real DoclingDocument with table items — integration test only | Known gap |
| FR-2109 | MUST | Oversized items split by semchunk; `_semantic_split` NOT called for Docling docs | `chunking.py` — assert `_semantic_split` not called (`patch` + `assert_not_called()`) | Known gap: semchunk behavior requires real oversized DoclingDocument |
| FR-2111 | MUST | ProcessedChunk metadata contains all required keys | `chunking.py` — metadata schema check on output chunks | integration_happy_path |
| FR-2113 | SHOULD | Undersized items merged up to max_tokens | Known gap: requires real DoclingDocument with short consecutive items — integration test only | Known gap |
| FR-2115 | SHOULD | Code blocks kept whole when ≤ max_tokens; split at line boundary when > max_tokens | Known gap: requires real DoclingDocument with code block items — integration test only | Known gap |
| FR-2201 | MUST | VLM enrichment placed after chunking in DAG | `vlm_enrichment.py` — node is a no-op for disabled/builtin | integration_external_vlm (VLM runs after chunks exist) |
| FR-2203 | MUST | vlm_mode="builtin" → SmolVLM; "external" → LiteLLM; "disabled" → no-op; invalid → error | `vlm_enrichment.py` — disabled/builtin no-op, external active; `impl.py` — invalid mode error | integration_happy_path (disabled), integration_external_vlm (external) |
| FR-2205 | MUST | Image placeholder `![alt](src)` replaced with VLM description; surrounding text unchanged | `vlm_enrichment.py` — replace_placeholder happy path | integration_external_vlm |
| FR-2207 | MUST | VLM failure for one image → placeholder preserved; warning logged; other chunks unaffected | `vlm_enrichment.py` — error scenario (LiteLLM raises) | integration_external_vlm (error path) |
| FR-2209 | SHOULD | `vision_max_figures` limit respected; at most N images processed | `vlm_enrichment.py` — budget boundary condition | integration_external_vlm |
| FR-2211 | SHOULD | SmolVLM artifacts downloaded only when `vlm_mode="builtin"` | `support/docling.py` — warmup with_smolvlm scenarios | Not covered at integration level |
| FR-2301 | MUST | `docling_document=None` in state → markdown chunking path used | `chunking.py` — markdown fallback path | integration_fallback_nondocling, integration_corrupt_json |
| FR-2303 | MUST | Fallback path: `text_cleaning_node` and `document_refactoring_node` run normally | `structure_detection.py` — flag=False (regex path) | integration_fallback_nondocling |
| FR-2305 | MUST | Fallback path output semantically identical to pre-redesign except unicode normalization | `chunking.py` — markdown path produces same metadata schema | Known gap: byte-identical comparison requires pre-redesign snapshot — regression test |
| FR-2307 | MUST | Path selection based solely on `docling_document` presence; no additional flag | `chunking.py` — None → markdown; not-None → Docling (regardless of other flags) | integration_happy_path, integration_corrupt_json |
| FR-2401 | MUST | `IngestionConfig.vlm_mode` with valid values; default "disabled" | `types.py` — field presence and defaults | `impl.py` — invalid mode raises error |
| FR-2403 | MUST | `IngestionConfig.hybrid_chunker_max_tokens`; default 512 | `types.py` — field presence, default value | — |
| FR-2405 | MUST | `RAG_INGESTION_VLM_MODE` sets `vlm_mode`; `RAG_INGESTION_HYBRID_CHUNKER_MAX_TOKENS` sets max_tokens | `settings.py` — env var override scenarios | — |
| FR-2407 | MUST | `IngestionConfig.persist_docling_document`; default True; False → no `.docling.json` | `types.py` — field presence and default; `settings.py` — env var; `clean_store.py` — no docling.json when persist=False | — |
| FR-2409 | SHOULD | Config validation detects contradictory settings and fails fast | `impl.py` — all four validation rule scenarios | — |
| FR-2501 | MUST | `DocumentProcessingState` has `docling_document: Optional[Any]` defaulting to None | `structure_detection.py` — key present in state update on success | — |
| FR-2503 | MUST | `EmbeddingPipelineState` has `docling_document: Optional[Any]`; populated from CleanDocumentStore | `clean_store.py` — read_docling returns document or None; `chunking.py` — reads field from state | integration_happy_path, integration_corrupt_json |
| FR-2505 | MUST | `structure["docling_document_available"]` is True on success, False on fallback | `structure_detection.py` — both paths assert flag value | integration_happy_path, integration_fallback_nondocling |
| FR-2601 | MUST | HybridChunker exception → fallback to markdown; `processing_log` records error + fallback | `chunking.py` — error scenario (HybridChunker raises) | integration_hybridchunker_failure |
| FR-2603 | MUST | Corrupt `.docling.json` → `read_docling` returns None; document proceeds via markdown path | `clean_store.py` — invalid JSON error scenario | integration_corrupt_json |
| NFR-2901 | SHOULD | Performance targets (HybridChunker <2s, serialization <1s, deserialization <1s) | Known gap: performance testing requires real DoclingDocument + real HybridChunker — benchmark tests only | Known gap |
| NFR-2903 | MUST | `IngestionConfig()` with no args → identical behavior to pre-redesign | `types.py` — default construction; `settings.py` — defaults when no env vars set | — |
| NFR-2905 | MUST | All new parameters loaded from env vars; no hardcoding | `settings.py` — all three env var read scenarios | — |
| NFR-2907 | MUST | Docling-native chunks indistinguishable from fallback chunks at ProcessedChunk contract level | `chunking.py` — metadata schema check applies to both paths | integration_happy_path |
| NFR-2909 | SHOULD | `processing_log` entries for chunking path and VLM mode | `chunking.py` — log entries for both paths; `vlm_enrichment.py` — log entries for all modes | integration_happy_path, integration_external_vlm |
| NFR-2911 | SHOULD | `.docling.json` contains `_schema_version` key; deserialization checks version | `clean_store.py` — schema version in envelope; schema mismatch → None + warning | — |
| NFR-2913 | MAY | Parallel VLM processing for multiple images | Not covered — MAY requirement; parallel VLM not implemented. No test written. | Known gap |

### Summary of Known Gaps

| Gap | FR / NFR | Reason |
|-----|----------|--------|
| HybridChunker token-limit enforcement | FR-2103 | Requires real HybridChunker + tokenizer — integration test only |
| Table header repetition in multi-chunk tables | FR-2107 | Requires real DoclingDocument with table items — integration test only |
| semchunk forced split behavior | FR-2109 | Requires real oversized DoclingDocument item — integration test only |
| Undersized item merging | FR-2113 | Requires real DoclingDocument with short consecutive items — integration test only |
| Code block line-boundary splitting | FR-2115 | Requires real DoclingDocument with code block — integration test only |
| Fallback path byte-identical output | FR-2305 | Requires pre-redesign snapshot comparison — regression test |
| Performance benchmarks | NFR-2901 | Requires real 100-page document + timed execution — benchmark only |
| Parallel VLM processing | NFR-2913 | MAY requirement; not implemented — no test written |
| vision_strict=True behavior in vlm_enrichment_node | (vlm_enrichment) | EG does not specify node behavior for vision_strict=True — source read required |
| vision_max_image_bytes enforcement | (vlm_enrichment) | Image byte loading mechanism not specified in EG — source read required |
| verify_core_design exception class name | (impl.py) | Exception class name not confirmed from Phase 0 contracts alone |
| Full backward-compat enumeration of IngestionConfig fields | (types.py) | Complete pre-redesign field list not available without reading source |

---

## Verification Commands

```bash
# Run all Docling-native chunking pipeline tests:
pytest tests/ingest/test_docling_chunking_settings.py -v
pytest tests/ingest/test_docling_chunking_types.py -v
pytest tests/ingest/test_docling_chunking_clean_store.py -v
pytest tests/ingest/test_docling_chunking_parse.py -v
pytest tests/ingest/doc_processing/test_docling_chunking_structure_detection.py -v
pytest tests/ingest/embedding/test_docling_chunking_node.py -v
pytest tests/ingest/embedding/test_docling_chunking_vlm_enrichment.py -v
pytest tests/ingest/test_docling_chunking_design_checks.py -v

# Run all together:
pytest tests/ingest/ -k "docling_chunking" -v

# Skip tests requiring live Docling models:
pytest tests/ingest/ -k "docling_chunking" -m "not requires_docling and not integration and not slow" -v
```
