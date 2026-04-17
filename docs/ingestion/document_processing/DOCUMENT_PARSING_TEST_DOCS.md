> **Document type:** Test documentation (Layer 5)
> **Upstream:** DOCUMENT_PARSING_ENGINEERING_GUIDE.md
> **Last updated:** 2026-04-17
> **Status:** Authoritative (post-implementation)

# Document Parsing Test Documentation

## 1. Test Strategy

### What is tested

- **Integration tests** that exercise `structure_detection_node` and `chunking_node` with a real `ParserRegistry` attached to `Runtime`.
- **Parser dispatch correctness:** `.md`, `.txt`, `.py` extension routing to the expected strategy.
- **State contract:** `parse_result` and `parser_instance` are written to state on the parser-abstraction path.
- **Chunking wire-up:** `chunking_node` produces non-empty `ProcessedChunk` output when consuming a `ParseResult` from a parser.
- **Chunker override:** `chunker="markdown"` produces chunks even when the native chunker would be used otherwise.
- **Error paths:** missing dependencies fall back silently (code strategy → text fallback); plain-text ingestion never produces `should_skip`.

### What is not tested (requires Docling or tree-sitter)

The integration test suite is dependency-light by design. Tests that exercise `DoclingParser` directly (PDF parsing, `HybridChunker` output, SmolVLM mode) require `docling` and `docling-core` installed in the test environment and are not yet represented in the suite. The `CodeParser` AST path is tested opportunistically — tests accept either `"code"` or `"text"` strategy depending on whether tree-sitter grammars are installed.

### Mocking approach

- `MagicMock()` is used for `Runtime.embedder` and `Runtime.weaviate_client` — neither is exercised by the parser abstraction path.
- `Runtime.kg_builder=None` — not used in structure detection or chunking.
- No mocking of `ParserRegistry` or concrete parser classes — the real implementations run.
- `IngestionConfig(enable_docling_parser=False)` prevents any attempt to import Docling in environments where it is absent.

---

## 2. Test File Map

| File | Location | What it covers |
|------|----------|---------------|
| `test_parser_integration.py` | `tests/ingest/` | End-to-end parser registry dispatch, node wire-up, chunking output |

No unit tests for individual parser classes (`DoclingParser`, `PlainTextParser`, `CodeParser`) or `ParserRegistry` exist as separate test files at the time of writing. Contract-level coverage is provided through the integration tests and the shared fixtures.

---

## 3. Coverage by FR

| FR | Description | Test class / function |
|----|-------------|----------------------|
| FR-3200 | `DocumentParser` is a runtime-checkable protocol | Indirectly: `TestParserIntegrationMd.test_md_dispatches_to_text_parser` verifies a real parser instance is dispatched |
| FR-3201 | `ParseResult` contains no parser-internal types | `TestParserIntegrationMd.test_md_parse_result_fields_populated` asserts `.markdown`, `.headings`, `.page_count` |
| FR-3204 | `ensure_ready()` called at pipeline startup | `_make_registry()` verifies `"text"` strategy always available after `ParserRegistry.__init__()` |
| FR-3206 | Per-document parser instance lifecycle | `_make_registry()` / `registry.get_parser()` creates a new instance per call; no shared-instance tests yet |
| FR-3280 / FR-3281 | `PlainTextParser` handles `.md`, `.txt` | `TestParserIntegrationMd`, `TestParserIntegrationTxt` |
| FR-3282 | `PlainTextParser.chunk()` uses heading-aware markdown splitting | `TestParserIntegrationChunkingWireup.test_chunking_node_uses_parse_result` (`.md` file) |
| FR-3300 | `ParserRegistry` routes extensions to strategies | `TestParserIntegrationMd`, `TestParserIntegrationTxt`, `TestParserIntegrationPy` |
| FR-3301 | `config.parser_strategy` config field consumed | `IngestionConfig(enable_docling_parser=False)` forces Docling-absent registry; auto-routing confirmed |
| FR-3302 | Unknown extension falls back to `"text"` | Covered by registry init verification in `_make_registry()` asserting `"text"` always present |
| FR-3303 | Registry skips unavailable parsers silently | `TestParserIntegrationPy.test_py_no_error_on_code_strategy_fallback` verifies no error when code strategy absent |
| FR-3320 | `chunker="markdown"` override applies | `TestParserIntegrationChunkingWireup.test_chunking_node_with_markdown_override` |

---

## 4. Fixture Reference

All fixtures are inline within the test file (no shared `conftest.py` for the parser tests).

### `_make_registry(config)`

```python
def _make_registry(config: IngestionConfig) -> ParserRegistry:
```

Builds a `ParserRegistry` and asserts `"text"` strategy is always available. Used by all test classes.

### `_make_state(source_path, source_name, raw_text, config, registry)`

```python
def _make_state(
    source_path: str,
    source_name: str,
    raw_text: str,
    config: IngestionConfig,
    registry: ParserRegistry,
) -> dict:
```

Builds a minimal pipeline state dict for `structure_detection_node`. Attaches `registry` to `Runtime.parser_registry`.

### `_make_chunking_state(source_path, source_name, raw_text, config, parse_result, parser_instance)`

```python
def _make_chunking_state(
    source_path: str,
    source_name: str,
    raw_text: str,
    config: IngestionConfig,
    parse_result: ParseResult | None = None,
    parser_instance: object | None = None,
) -> dict:
```

Builds a minimal pipeline state dict for `chunking_node`. Includes all required `EmbeddingPipelineState` keys (`source_uri`, `source_key`, `source_id`, `connector`, `source_version`). Conditionally sets `parse_result` and `parser_instance` when provided.

### Inline `IngestionConfig` overrides used across tests

```python
config = IngestionConfig(enable_docling_parser=False)
# Prevents DoclingParser registration; ensures tests run without Docling installed.

config = IngestionConfig(enable_docling_parser=False, chunker="markdown")
# Forces markdown chunker override for test_chunking_node_with_markdown_override.
```

---

## 5. Test Classes

### `TestParserIntegrationMd`

Tests that `.md` files are dispatched to the `PlainTextParser` (text strategy) via the registry.

| Method | What it asserts |
|--------|----------------|
| `test_md_dispatches_to_text_parser` | `parse_result` and `parser_instance` in state update; `parser_strategy` not `"regex"`; `heading_count >= 2` |
| `test_md_parse_result_fields_populated` | `parse_result.markdown` non-empty; `parse_result.headings` has at least one entry; `page_count == 0` |
| `test_md_raw_text_replaced_with_parser_markdown` | `raw_text` in state update equals the parser's markdown output (for `.md`, content is passed through as-is) |

### `TestParserIntegrationTxt`

Tests that `.txt` files are dispatched to the `PlainTextParser` (text strategy).

| Method | What it asserts |
|--------|----------------|
| `test_txt_dispatches_to_text_parser` | `parse_result` and `parser_instance` present in state update |
| `test_txt_no_skip_produced` | `should_skip` is not `True`; no errors in state update |
| `test_txt_processing_log_ok` | `"structure_detection:ok"` appears in `processing_log` |

### `TestParserIntegrationPy`

Tests that `.py` files are dispatched to a parser (code strategy when available, text fallback otherwise) without errors.

| Method | What it asserts |
|--------|----------------|
| `test_py_dispatches_to_available_parser` | `parse_result` and `parser_instance` present regardless of tree-sitter availability |
| `test_py_produces_valid_parse_result` | `ParseResult` has all four required attributes |
| `test_py_no_error_on_code_strategy_fallback` | No errors; `should_skip` not `True` when code strategy unavailable |

### `TestParserIntegrationChunkingWireup`

End-to-end tests: structure detection → chunking. Verifies `chunking_node` consumes `parse_result` correctly.

| Method | What it asserts |
|--------|----------------|
| `test_chunking_node_uses_parse_result` | `chunks` is non-empty; first chunk has non-empty `text` |
| `test_chunking_node_with_markdown_override` | `chunker="markdown"` still produces non-empty chunks |
| `test_chunking_node_chunk_metadata_populated` | All chunks have non-empty `text` |
| `test_registry_path_parser_strategy_not_regex` | `structure["parser_strategy"]` is not `"regex"` or `"unknown"` when registry is active |

---

## 6. Running Tests

### All parser integration tests

```bash
pytest tests/ingest/test_parser_integration.py -v
```

### With stdout visible

```bash
pytest tests/ingest/test_parser_integration.py -v -s
```

### Single test class

```bash
pytest tests/ingest/test_parser_integration.py::TestParserIntegrationMd -v
pytest tests/ingest/test_parser_integration.py::TestParserIntegrationChunkingWireup -v
```

### Single test method

```bash
pytest tests/ingest/test_parser_integration.py::TestParserIntegrationPy::test_py_no_error_on_code_strategy_fallback -v
```

### With tree-sitter installed (code strategy active)

When `tree-sitter` and `tree-sitter-python` are installed, `TestParserIntegrationPy` exercises the real `CodeParser` path. The tests accept either strategy, so they pass with or without tree-sitter.

```bash
uv add tree-sitter tree-sitter-python
pytest tests/ingest/test_parser_integration.py::TestParserIntegrationPy -v
```

### Full ingest test suite

```bash
pytest tests/ingest/ -v
```
