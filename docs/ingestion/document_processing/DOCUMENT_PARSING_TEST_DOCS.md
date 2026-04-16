> **⚠ DRAFT — PRE-IMPLEMENTATION TEST PLAN**
>
> This test plan was authored **before** source code existed. Test **strategy, scope, coverage, and requirement traceability** are appropriately pre-impl and will survive as-is. However, **specific module paths, fixture names, helper function signatures, and import statements** in integration test sections reference code that has not yet been written and may drift during implementation.
>
> To be **reconciled post-implementation** using `/write-test-docs` (which requires the post-impl engineering guide as input — transitively protected by the non-skippable existence check in `/write-engineering-guide`). Integration test module paths and fixtures will be refreshed against real code at that time.

---

> **Document type:** Test documentation (Layer 6)
> **Upstream:** DOCUMENT_PARSING_ENGINEERING_GUIDE.md
> **Last updated:** 2026-04-15
> **Status:** DRAFT (pre-implementation)

# Document Parsing Abstraction — Test Documentation (v1.0.0-draft)

## 1. Test Strategy Overview

### 1.1 Scope

This document defines the test plan for the Document Parsing Abstraction, which replaces the former Docling-coupled parsing path with a pluggable strategy system. The test surface covers:

1. Protocol compliance: every parser implements `DocumentParser`
2. `ParseResult` and `Chunk` contracts: required fields, types, serialisability
3. Docling adapter: wraps existing Docling correctly, encapsulates `DoclingDocument`
4. Code parser: tree-sitter AST chunking, KG triple extraction
5. Plain text parser: heading detection, format handling
6. Parser registry: extension routing, override, unknown fallback
7. VLM mode guard: mutual exclusion validation

### 1.2 Test Categories

| Category | Purpose | Infrastructure Required |
|----------|---------|------------------------|
| **Unit** | Verify individual parsers, registry routing, and VLM guard in isolation | None (tree-sitter required for code parser tests) |
| **Integration** | Verify parser-to-pipeline-node handoff, chunking override in pipeline context | None |
| **Contract** | Verify `DocumentParser` protocol compliance, `ParseResult`/`Chunk` invariants, serialisability | None |
| **End-to-end** | Full document through `structure_detection_node` -> `chunking_node` with each parser type | None |

### 1.3 Dependencies and Fixtures

**External dependencies (unit tests):**
- `tree-sitter` + `tree-sitter-python` (code parser tests)
- `docling` + `docling-core` (Docling parser tests, can be mocked for contract tests)

**Shared fixtures:**
- `mock_config` — minimal `IngestionConfig` with `parser_strategy="auto"`, `chunker="native"`, `vlm_mode="disabled"`
- `sample_python_file` — Python file with 2 functions, 1 class, imports, and decorators
- `sample_markdown_file` — Markdown with headings, a table, and an image reference
- `ParserContractTests` — reusable mixin class for protocol compliance testing

---

## 2. Unit Tests

### 2.1 Module: `src/ingest/support/parser_base.py`

**Test file:** `tests/ingest/support/test_parser_base.py`

**Test class:** `TestParseResultContract`

| Test Method | Assertions | Mocks | FR |
|-------------|-----------|-------|-----|
| `test_parse_result_round_trips_through_json` | `json.dumps(asdict(ParseResult(...)))` succeeds and deserialises to identical values. | None | FR-3201 |
| `test_parse_result_has_four_required_fields` | `ParseResult` has exactly `markdown` (str), `headings` (list), `has_figures` (bool), `page_count` (int). | None | FR-3201 |
| `test_chunk_round_trips_through_json` | `json.dumps(asdict(Chunk(...)))` succeeds, including `extra_metadata` dict. | None | FR-3202 |
| `test_chunk_has_six_required_fields` | `Chunk` has `text`, `section_path`, `heading`, `heading_level`, `chunk_index`, `extra_metadata`. | None | FR-3202 |
| `test_chunk_extra_metadata_rejects_non_serialisable` | `Chunk` with a callable in `extra_metadata` fails `json.dumps`. | None | FR-3202 |
| `test_stub_class_satisfies_document_parser_protocol` | A minimal stub with `parse()`, `chunk()`, `ensure_ready()`, `warmup()` passes `isinstance(stub, DocumentParser)`. | None | FR-3200 |
| `test_protocol_is_runtime_checkable` | `DocumentParser` has `runtime_checkable` decorator. | None | FR-3200 |

### 2.2 Module: `src/ingest/support/docling.py`

**Test file:** `tests/ingest/support/test_parser_docling.py`

**Test class:** `TestDoclingParserContract` (extends `ParserContractTests`)

| Test Method | Assertions | Mocks | FR |
|-------------|-----------|-------|-----|
| `test_satisfies_protocol` | `isinstance(DoclingParser(), DocumentParser)` is `True`. | None | FR-3200, FR-3221 |
| `test_parse_returns_parse_result` | `DoclingParser.parse()` returns `ParseResult` with correct field types. | Mocked Docling internals | FR-3201, FR-3221 |
| `test_parse_result_has_no_docling_document_attribute` | Returned `ParseResult` has no `docling_document`, `_docling_document`, or `internal_doc` attribute. | Mocked Docling | FR-3205 |
| `test_parse_result_is_serialisable` | `json.dumps(asdict(result))` succeeds — no opaque Docling types leak. | Mocked Docling | FR-3201, FR-3205 |
| `test_chunk_returns_chunk_list` | `DoclingParser.chunk()` returns `list[Chunk]` with valid fields. | Mocked Docling | FR-3202, FR-3221 |
| `test_chunk_before_parse_raises_runtime_error` | `DoclingParser().chunk(dummy_parse_result)` raises `RuntimeError` with "before parse" message. | None | FR-3206 |
| `test_chunk_heading_metadata_present` | Each `Chunk` from `DoclingParser.chunk()` has `section_path` and `heading` populated from Docling heading hierarchy. | Mocked Docling | FR-3223 |
| `test_chunks_are_serialisable` | All chunks pass `json.dumps(asdict(c))`. | Mocked Docling | FR-3202 |
| `test_chunk_indices_are_sequential` | `chunk_index` values are `0, 1, 2, ...` in order. | Mocked Docling | FR-3202 |
| `test_ensure_ready_raises_without_docling` | With `docling` unimportable, `DoclingParser.ensure_ready()` raises `RuntimeError`. | `monkeypatch` import block | FR-3204 |

### 2.3 Module: `src/ingest/support/parser_code.py`

**Test file:** `tests/ingest/support/test_parser_code.py`

**Test class:** `TestCodeParserContract` (extends `ParserContractTests`)

| Test Method | Assertions | Mocks | FR |
|-------------|-----------|-------|-----|
| `test_satisfies_protocol` | `isinstance(CodeParser(), DocumentParser)` is `True`. | None | FR-3200, FR-3250 |
| `test_parse_returns_parse_result` | `CodeParser.parse()` returns `ParseResult` with `has_figures=False`, `page_count=0`. | `sample_python_file` | FR-3256 |
| `test_parse_result_markdown_contains_code_fence` | `result.markdown` contains `` ```python `` fence block. | `sample_python_file` | FR-3256 |
| `test_chunk_produces_one_chunk_per_function` | A file with 2 functions and 1 class produces at least 3 chunks (2 function + 1 class), plus possible module-level chunk. | `sample_python_file` | FR-3252 |
| `test_chunk_extra_metadata_has_language` | Every chunk `extra_metadata` contains `"language": "python"`. | `sample_python_file` | FR-3253 |
| `test_chunk_extra_metadata_has_function_name` | Function chunks have `function_name` in `extra_metadata`. | `sample_python_file` | FR-3253 |
| `test_chunk_extra_metadata_has_class_name` | Class chunks have `class_name` in `extra_metadata`. | `sample_python_file` | FR-3253 |
| `test_chunk_extra_metadata_has_kg_relationships` | Chunks with imports have `kg_relationships` list in `extra_metadata` with `type: "imports"` entries. | `sample_python_file` | FR-3254 |
| `test_kg_relationships_include_inheritance` | A class `Dog(Animal)` produces `{type: "inherits", source: "Dog", target: "Animal"}`. | Custom fixture | FR-3254 |
| `test_kg_relationships_include_calls` | A function calling another produces `{type: "calls", source: ..., target: ...}`. | Custom fixture | FR-3254 |
| `test_kg_relationships_are_deterministic` | Parsing the same file twice produces identical `kg_relationships`. | `sample_python_file` | FR-3254 |
| `test_no_code_to_nl_translation` | `ParseResult.markdown` contains raw source code, not natural-language summary. | `sample_python_file` | FR-3255 |
| `test_chunk_before_parse_raises` | `CodeParser().chunk(dummy)` raises `RuntimeError`. | None | FR-3206 |
| `test_ensure_ready_raises_without_tree_sitter` | With `tree_sitter` unimportable, `CodeParser.ensure_ready()` raises `RuntimeError`. | `monkeypatch` | FR-3204 |

**Test class:** `TestCodeParserLanguages`

| Test Method | Assertions | Mocks | FR |
|-------------|-----------|-------|-----|
| `test_python_file_parse` | `.py` file parses and chunks correctly. | `tmp_path` fixture | FR-3251 |
| `test_javascript_file_parse` | `.js` file parses with `language: "javascript"` in metadata. | `tmp_path` fixture | FR-3251 |
| `test_rust_file_parse` | `.rs` file parses with `language: "rust"` in metadata. | `tmp_path` fixture | FR-3251 |
| `test_unsupported_grammar_falls_back_gracefully` | A language without installed grammar raises or falls back without crashing. | `tmp_path` fixture | FR-3250 |

### 2.4 Module: `src/ingest/support/parser_text.py`

**Test file:** `tests/ingest/support/test_parser_text.py`

**Test class:** `TestPlainTextParserContract` (extends `ParserContractTests`)

| Test Method | Assertions | Mocks | FR |
|-------------|-----------|-------|-----|
| `test_satisfies_protocol` | `isinstance(PlainTextParser(), DocumentParser)` is `True`. | None | FR-3200, FR-3280 |
| `test_parse_markdown_file` | `.md` file parsed, `result.markdown` matches file content. Headings extracted from `#` patterns. | `sample_markdown_file` | FR-3280, FR-3281 |
| `test_parse_txt_file` | `.txt` file parsed, content returned as-is. | `tmp_path` fixture | FR-3280 |
| `test_parse_html_file` | `.html` file converted to markdown (or tag-stripped fallback). | `tmp_path` fixture | FR-3280 |
| `test_parse_rst_file` | `.rst` file converted to markdown (or heading-heuristic fallback). | `tmp_path` fixture | FR-3280 |
| `test_heading_extraction_from_markdown` | File with `# H1`, `## H2`, `### H3` produces headings list with all three. | `tmp_path` fixture | FR-3281 |
| `test_has_figures_detects_image_syntax` | File containing `![alt](url)` sets `has_figures=True`. | `sample_markdown_file` | FR-3281 |
| `test_page_count_is_zero` | `page_count` is always `0` for plain text files. | Any text file | FR-3281 |
| `test_chunk_delegates_to_chunk_with_markdown` | `PlainTextParser.chunk()` produces heading-aware chunks with `section_path`. | `sample_markdown_file` | FR-3282 |
| `test_chunk_before_parse_raises` | `PlainTextParser().chunk(dummy)` raises `RuntimeError`. | None | FR-3206 |

### 2.5 Module: `src/ingest/support/parser_registry.py`

**Test file:** `tests/ingest/support/test_parser_registry.py`

**Test class:** `TestParserRegistry`

| Test Method | Assertions | Mocks | FR |
|-------------|-----------|-------|-----|
| `test_pdf_routes_to_docling_parser` | `registry.get_parser("report.pdf")` returns a `DoclingParser` instance. | `mock_config` | FR-3300 |
| `test_py_routes_to_code_parser` | `registry.get_parser("utils.py")` returns a `CodeParser` instance. | `mock_config` | FR-3300 |
| `test_md_routes_to_plain_text_parser` | `registry.get_parser("README.md")` returns a `PlainTextParser` instance. | `mock_config` | FR-3300 |
| `test_uppercase_extension_routes_correctly` | `registry.get_parser("REPORT.PDF")` returns `DoclingParser` (case-insensitive). | `mock_config` | FR-3300 |
| `test_unknown_extension_routes_to_plain_text_with_warning` | `registry.get_parser("config.ini")` returns `PlainTextParser`. Warning logged. | `mock_config`, `caplog` | FR-3302 |
| `test_config_override_forces_strategy` | With `parser_strategy="document"`, `.py` files route to `DoclingParser`. | Custom config | FR-3301 |
| `test_dockerfile_routes_to_code_parser` | `registry.get_parser("Dockerfile")` returns `CodeParser` (filename map). | `mock_config` | FR-3300 |
| `test_get_parser_returns_new_instance_each_call` | Two calls to `get_parser("a.py")` return different instances (no singleton). | `mock_config` | FR-3206 |
| `test_all_documented_extensions_are_registered` | Every extension listed in the spec (`.pdf`, `.docx`, `.py`, `.rs`, `.go`, `.md`, `.txt`, etc.) routes to a parser without error. | `mock_config` | FR-3300, FR-3303 |

### 2.6 Module: VLM Mode Guard (`src/ingest/impl.py`)

**Test file:** `tests/ingest/support/test_vlm_guard.py`

**Test class:** `TestVLMGuard`

| Test Method | Assertions | Mocks | FR |
|-------------|-----------|-------|-----|
| `test_builtin_plus_multimodal_raises_error` | `vlm_mode="builtin"` + `enable_multimodal_processing=True` produces a design check error. | Config fixture | FR-3340 |
| `test_builtin_without_multimodal_passes` | `vlm_mode="builtin"` + `enable_multimodal_processing=False` passes validation. | Config fixture | FR-3340 |
| `test_disabled_with_multimodal_passes` | `vlm_mode="disabled"` + `enable_multimodal_processing=True` passes validation. | Config fixture | FR-3340 |
| `test_disabled_without_multimodal_passes` | `vlm_mode="disabled"` + `enable_multimodal_processing=False` passes validation. | Config fixture | FR-3340 |
| `test_external_with_multimodal_passes_with_warning` | `vlm_mode="external"` + `enable_multimodal_processing=True` passes with a startup warning. | Config fixture, `caplog` | FR-3342 |
| `test_external_without_multimodal_passes` | `vlm_mode="external"` + `enable_multimodal_processing=False` passes validation. | Config fixture | FR-3340 |
| `test_guard_integrated_with_design_checks` | The VLM guard is invoked during `design_check_node` or pipeline init, not silently skipped. | Config fixture | FR-3341 |

### 2.7 Module: Chunker Override (`src/ingest/embedding/nodes/chunking.py`)

**Test file:** `tests/ingest/embedding/test_chunker_override.py`

**Test class:** `TestChunkerOverride`

| Test Method | Assertions | Mocks | FR |
|-------------|-----------|-------|-----|
| `test_markdown_override_bypasses_native_chunking` | With `chunker="markdown"`, `parser_instance.chunk()` is never called. `chunk_with_markdown()` is called instead. | Mock parser instance | FR-3320 |
| `test_native_chunker_calls_parser_chunk` | With `chunker="native"`, `parser_instance.chunk()` is called. | Mock parser instance | FR-3320 |
| `test_native_chunker_fallback_on_failure` | When `parser_instance.chunk()` raises, falls back to `chunk_with_markdown()`. | Mock parser that raises | FR-3321 |
| `test_markdown_override_applies_to_all_parser_types` | With `chunker="markdown"`, Docling, Code, and PlainText parsers all bypass native chunking. | Mock parsers | FR-3320 |

---

## 3. Integration Tests

### 3.1 Parser-to-Node Handoff

**Test file:** `tests/ingest/doc_processing/test_parser_integration.py`

**Setup:** Create sample files for each parser type. Run through `structure_detection_node` and `chunking_node`.

| Test Method | Steps | Verification |
|-------------|-------|-------------|
| `test_pdf_through_structure_and_chunking` | 1. Create sample PDF. 2. Run `structure_detection_node`. 3. Run `chunking_node`. | State has `parse_result` (ParseResult) and output chunks (list[Chunk]). No Docling types in state. |
| `test_python_through_structure_and_chunking` | 1. Create sample `.py` file. 2. Run `structure_detection_node`. 3. Run `chunking_node`. | Chunks have `language`, `function_name` in metadata. KG relationships present. |
| `test_markdown_through_structure_and_chunking` | 1. Create sample `.md` file. 2. Run `structure_detection_node`. 3. Run `chunking_node`. | Chunks have heading-aware `section_path`. |
| `test_chunker_override_in_pipeline_context` | 1. Set `chunker="markdown"`. 2. Run PDF through both nodes. | Chunks produced by `chunk_with_markdown`, not native DoclingParser chunking. |

### 3.2 Registry End-to-End

**Test file:** `tests/ingest/support/test_registry_integration.py`

| Test Method | Steps | Verification |
|-------------|-------|-------------|
| `test_registry_creates_and_routes_all_strategies` | 1. Instantiate `ParserRegistry(config)`. 2. Route files with diverse extensions. 3. Parse and chunk each. | Each file routed to correct parser. All parsers produce valid `ParseResult` and `Chunk` lists. |

---

## 4. Contract Tests

### 4.1 Interface Contracts

**Test file:** `tests/ingest/support/test_parser_contracts.py`

The `ParserContractTests` mixin is the canonical contract test suite. Every parser implementation subclasses it:

| Test Class | Parser | Fixtures |
|------------|--------|----------|
| `TestDoclingParserContract` | `DoclingParser` | Sample PDF (mocked) |
| `TestCodeParserContract` | `CodeParser` | `sample_python_file` |
| `TestPlainTextParserContract` | `PlainTextParser` | `sample_markdown_file` |

Each subclass inherits these contract tests:

| Contract Test | What It Validates | FR |
|---------------|-------------------|-----|
| `test_satisfies_protocol` | `isinstance(parser, DocumentParser)` | FR-3200 |
| `test_parse_returns_parse_result` | Return type and field types | FR-3201 |
| `test_parse_result_is_serialisable` | `json.dumps(asdict(result))` succeeds | FR-3201 |
| `test_parse_result_has_no_internal_types` | No `docling_document`, `tree`, `internal_doc` attributes | FR-3205 |
| `test_chunk_returns_chunk_list` | Return type and element type | FR-3202 |
| `test_chunks_are_serialisable` | `json.dumps(asdict(c))` succeeds for every chunk | FR-3202 |
| `test_chunk_before_parse_raises` | `RuntimeError` on `chunk()` without prior `parse()` | FR-3206 |
| `test_chunk_indices_are_sequential` | `chunk_index` values are `0, 1, 2, ...` | FR-3202 |

### 4.2 State Invariants

| Test Method | What It Validates | FR |
|-------------|-------------------|-----|
| `test_parser_instance_not_serialised_in_state` | `parser_instance` field in `EmbeddingPipelineState` is transient, not included in serialisation. | FR-3205 |
| `test_parse_result_in_state_is_dataclass` | `parse_result` in pipeline state is a `ParseResult` dataclass, not a raw dict. | FR-3201 |
| `test_no_docling_types_in_pipeline_state` | Scanning all state fields, no value is a `DoclingDocument` or Docling-internal type. | FR-3205 |

---

## 5. Requirement Traceability

| FR | Description | Test Method | Test File |
|----|-------------|-------------|-----------|
| FR-3200 | Abstract parser interface | `test_stub_class_satisfies_document_parser_protocol`, `test_protocol_is_runtime_checkable`, `test_satisfies_protocol` (all 3 parsers) | `test_parser_base.py`, `test_parser_contracts.py` |
| FR-3201 | ParseResult contract | `test_parse_result_round_trips_through_json`, `test_parse_result_has_four_required_fields`, `test_parse_returns_parse_result`, `test_parse_result_is_serialisable` | `test_parser_base.py`, `test_parser_contracts.py` |
| FR-3202 | Chunk contract | `test_chunk_round_trips_through_json`, `test_chunk_has_six_required_fields`, `test_chunk_extra_metadata_rejects_non_serialisable`, `test_chunk_returns_chunk_list`, `test_chunks_are_serialisable`, `test_chunk_indices_are_sequential` | `test_parser_base.py`, `test_parser_contracts.py` |
| FR-3204 | Parser readiness check | `test_ensure_ready_raises_without_docling`, `test_ensure_ready_raises_without_tree_sitter` | `test_parser_docling.py`, `test_parser_code.py` |
| FR-3205 | Parser encapsulation | `test_parse_result_has_no_docling_document_attribute`, `test_parse_result_has_no_internal_types`, `test_no_docling_types_in_pipeline_state` | `test_parser_docling.py`, `test_parser_contracts.py` |
| FR-3206 | Instance lifecycle | `test_chunk_before_parse_raises_runtime_error`, `test_chunk_before_parse_raises` (all parsers), `test_get_parser_returns_new_instance_each_call` | `test_parser_docling.py`, `test_parser_code.py`, `test_parser_text.py`, `test_parser_registry.py` |
| FR-3221 | Docling implementation | `test_parse_returns_parse_result`, `test_chunk_returns_chunk_list` (Docling) | `test_parser_docling.py` |
| FR-3223 | Chunk heading metadata | `test_chunk_heading_metadata_present` | `test_parser_docling.py` |
| FR-3250 | Code parser (tree-sitter) | `test_satisfies_protocol` (Code), `test_unsupported_grammar_falls_back_gracefully` | `test_parser_code.py` |
| FR-3251 | Supported languages | `test_python_file_parse`, `test_javascript_file_parse`, `test_rust_file_parse` | `test_parser_code.py` |
| FR-3252 | AST-guided chunking | `test_chunk_produces_one_chunk_per_function` | `test_parser_code.py` |
| FR-3253 | Code chunk metadata | `test_chunk_extra_metadata_has_language`, `test_chunk_extra_metadata_has_function_name`, `test_chunk_extra_metadata_has_class_name` | `test_parser_code.py` |
| FR-3254 | Deterministic KG extraction | `test_chunk_extra_metadata_has_kg_relationships`, `test_kg_relationships_include_inheritance`, `test_kg_relationships_include_calls`, `test_kg_relationships_are_deterministic` | `test_parser_code.py` |
| FR-3255 | No code-to-NL | `test_no_code_to_nl_translation` | `test_parser_code.py` |
| FR-3256 | Code ParseResult | `test_parse_result_markdown_contains_code_fence`, `test_parse_returns_parse_result` (Code) | `test_parser_code.py` |
| FR-3280 | Plain text parser formats | `test_parse_markdown_file`, `test_parse_txt_file`, `test_parse_html_file`, `test_parse_rst_file` | `test_parser_text.py` |
| FR-3281 | Minimal processing | `test_heading_extraction_from_markdown`, `test_has_figures_detects_image_syntax`, `test_page_count_is_zero` | `test_parser_text.py` |
| FR-3282 | Markdown-based chunking | `test_chunk_delegates_to_chunk_with_markdown` | `test_parser_text.py` |
| FR-3300 | Extension-based routing | `test_pdf_routes_to_docling_parser`, `test_py_routes_to_code_parser`, `test_md_routes_to_plain_text_parser`, `test_uppercase_extension_routes_correctly`, `test_dockerfile_routes_to_code_parser`, `test_all_documented_extensions_are_registered` | `test_parser_registry.py` |
| FR-3301 | Parser override config | `test_config_override_forces_strategy` | `test_parser_registry.py` |
| FR-3302 | Unrecognised extension | `test_unknown_extension_routes_to_plain_text_with_warning` | `test_parser_registry.py` |
| FR-3303 | Parser strategy registry | `test_all_documented_extensions_are_registered` | `test_parser_registry.py` |
| FR-3320 | Chunker override setting | `test_markdown_override_bypasses_native_chunking`, `test_native_chunker_calls_parser_chunk`, `test_markdown_override_applies_to_all_parser_types` | `test_chunker_override.py` |
| FR-3321 | Markdown chunker fallback | `test_native_chunker_fallback_on_failure` | `test_chunker_override.py` |
| FR-3340 | VLM mutual exclusion guard | `test_builtin_plus_multimodal_raises_error`, `test_builtin_without_multimodal_passes`, `test_disabled_with_multimodal_passes`, `test_disabled_without_multimodal_passes`, `test_external_without_multimodal_passes` | `test_vlm_guard.py` |
| FR-3341 | Design check integration | `test_guard_integrated_with_design_checks` | `test_vlm_guard.py` |
| FR-3342 | External + multimodal info | `test_external_with_multimodal_passes_with_warning` | `test_vlm_guard.py` |
