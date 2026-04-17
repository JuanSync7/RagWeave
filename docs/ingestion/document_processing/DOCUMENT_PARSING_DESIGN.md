> **Document type:** Design document (Layer 4)
> **Upstream:** DOCUMENT_PARSING_SPEC.md
> **Downstream:** DOCUMENT_PARSING_IMPLEMENTATION.md
> **Last updated:** 2026-04-15

# Document Parsing Abstraction — Design (v1.0.0)

| Field | Value |
|-------|-------|
| **Document** | Document Parsing Abstraction Design Document |
| **Version** | 1.0.0 |
| **Status** | Draft |
| **Spec Reference** | `DOCUMENT_PARSING_SPEC.md` v1.0.0 (FR-3200–FR-3342) |
| **Companion Documents** | `DOCUMENT_PARSING_SPEC.md`, `DOCUMENT_PARSING_SPEC_SUMMARY.md`, `DOCUMENT_PROCESSING_DESIGN.md`, `DOCLING_CHUNKING_DESIGN.md`, `DOCLING_CHUNKING_SPEC.md` |
| **Created** | 2026-04-15 |
| **Last Updated** | 2026-04-15 |

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2026-04-15 | Initial design covering pluggable parser interface, three strategy parsers, registry routing, chunker override, VLM guard, and migration path from current Docling-coupled implementation. |

> **Document Intent.** This document translates the requirements defined in `DOCUMENT_PARSING_SPEC.md`
> (FR-3200–FR-3342) into a task-oriented implementation plan with concrete file paths, interface
> contracts, dependency ordering, and migration steps. Each task maps to one or more spec requirements
> and includes subtasks, complexity estimates, and testing strategies.

---

## 1. Overview

The Document Parsing Abstraction introduces a pluggable parser interface that decouples the ingestion pipeline from Docling as the sole document parser. The current system has three problems this design addresses:

1. **Docling lock-in.** `DoclingDocument` has leaked into pipeline state (`IngestState`, `EmbeddingPipelineState`), LangGraph node signatures (`structure_detection_node`, `chunking_node`), and the `DoclingParseResult` dataclass. Every downstream consumer is coupled to Docling internals.

2. **No code or plain text support.** All files pass through Docling's document parsing path regardless of type. Source code files and markdown/txt files gain nothing from OCR or layout analysis.

3. **VLM double processing.** `vlm_mode="builtin"` and `enable_multimodal_processing=true` can both be active, causing figures to be described by two independent VLM pipelines with no warning.

This design introduces:

- An abstract `DocumentParser` protocol with `parse()` and `chunk()` methods (FR-3200).
- `ParseResult` and `Chunk` dataclasses as the sole pipeline boundary contract (FR-3201, FR-3202).
- Three concrete parsers: Docling document parser, tree-sitter code parser, and plain text parser.
- A `ParserRegistry` that routes files to parsers by extension (FR-3303, FR-3300).
- A `chunker` config override to force markdown-based chunking on any parser (FR-3320).
- A VLM mutual exclusion guard integrated into `verify_core_design()` (FR-3340, FR-3341).

---

## 2. Current State Analysis

### 2.1 Current Parsing Flow

The current parsing flow is tightly coupled to Docling:

1. `structure_detection_node` (`src/ingest/doc_processing/nodes/structure_detection.py`) calls `parse_with_docling()` directly, receiving a `DoclingParseResult` that includes the `DoclingDocument` object.
2. The `DoclingDocument` is injected into `IngestState` as `state["docling_document"]` and propagated across the Phase 1/Phase 2 boundary.
3. `chunking_node` (`src/ingest/embedding/nodes/chunking.py`) reads `state["docling_document"]` to decide between `_chunk_with_docling()` (HybridChunker) and `_chunk_with_markdown()` (fallback). The Docling path imports `HybridChunker` directly.
4. `EmbeddingPipelineState` (`src/ingest/embedding/state.py`) and `IngestState` (`src/ingest/common/types.py`) both carry a `docling_document` key.

### 2.2 Files to Modify or Replace

| File | Current Role | Change |
|------|-------------|--------|
| `src/ingest/support/docling.py` | Standalone functions: `parse_with_docling()`, `ensure_docling_ready()`, `warmup_docling_models()` | Wrap into `DoclingParser` class implementing `DocumentParser` protocol. Functions become methods. |
| `src/ingest/doc_processing/nodes/structure_detection.py` | Calls `parse_with_docling()` directly, injects `docling_document` into state | Delegate to parser registry; receive `ParseResult` (no `DoclingDocument`); store `ParseResult` in state instead. |
| `src/ingest/embedding/nodes/chunking.py` | Dual-path: checks `state["docling_document"]` for HybridChunker vs markdown fallback | Delegate to parser `chunk()` method (or markdown chunker if `chunker="markdown"`). Remove direct HybridChunker import. |
| `src/ingest/common/types.py` | `IngestState` has `docling_document` key; `IngestionConfig` lacks `parser_strategy` and `chunker` fields | Remove `docling_document` from state; add `parser_strategy` and `chunker` config fields. |
| `src/ingest/embedding/state.py` | `EmbeddingPipelineState` has `docling_document` key | Remove `docling_document`; add `parse_result` of type `ParseResult`. |
| `src/ingest/impl.py` | `verify_core_design()` validates config | Add VLM mutual exclusion check (FR-3340) and chunker validation (FR-3322). |

### 2.3 New Files

| File | Purpose |
|------|---------|
| `src/ingest/support/parser_base.py` | `DocumentParser` Protocol, `ParseResult` dataclass, `Chunk` dataclass |
| `src/ingest/support/parser_registry.py` | `ParserRegistry` class: extension-to-strategy mapping, parser instantiation |
| `src/ingest/support/parser_text.py` | `PlainTextParser` implementation |
| `src/ingest/support/parser_code.py` | `CodeParser` (tree-sitter) implementation |
| `tests/ingest/test_parser_base.py` | Contract tests for `ParseResult`, `Chunk`, and protocol compliance |
| `tests/ingest/test_parser_registry.py` | Routing tests for extension mapping and override config |
| `tests/ingest/test_parser_docling.py` | Docling adapter contract tests |
| `tests/ingest/test_parser_text.py` | Plain text parser tests |
| `tests/ingest/test_parser_code.py` | Code parser tests |
| `tests/ingest/test_vlm_guard.py` | VLM mutual exclusion validation tests |

---

## 3. Task Decomposition

### 3.1 Task 1: Abstract Parser Interface (Protocol Class)

**Description:** Define the `DocumentParser` protocol and the `ParseResult`/`Chunk` data contracts that form the parser boundary.

**Spec requirements:** FR-3200, FR-3201, FR-3202, FR-3203, FR-3204, FR-3205, FR-3206, FR-3207

**Dependencies:** None (foundational)

**Complexity:** Low

**Target file:** `src/ingest/support/parser_base.py`

**Test file:** `tests/ingest/test_parser_base.py`

**Subtasks:**

1. Define `ParseResult` dataclass with exactly four fields: `markdown: str`, `headings: list[str]`, `has_figures: bool`, `page_count: int` (FR-3201). Verify JSON-serialisable by design (no opaque types).
2. Define `Chunk` dataclass with exactly six fields: `text: str`, `section_path: str`, `heading: str`, `heading_level: int`, `chunk_index: int`, `extra_metadata: dict[str, Any]` (FR-3202). Default `extra_metadata` to empty dict.
3. Define `DocumentParser` as a `typing.Protocol` with:
   - `parse(self, file_path: Path, config: IngestionConfig) -> ParseResult` (FR-3200)
   - `chunk(self, parse_result: ParseResult) -> list[Chunk]` (FR-3200)
   - `@classmethod ensure_ready(cls, config: IngestionConfig) -> None` (FR-3204)
   - `@classmethod warmup(cls, config: IngestionConfig) -> None` (FR-3207, SHOULD)
4. Add a module-level docstring documenting the encapsulation rule: parser-internal types (DoclingDocument, tree-sitter Tree) must not appear in `ParseResult` or `Chunk` (FR-3205).
5. Document the per-document instance lifecycle expectation: callers should create a new parser instance per document, calling `parse()` then `chunk()` sequentially (FR-3206).

**Testing strategy:**
- Verify `ParseResult` and `Chunk` are JSON-serialisable (`dataclasses.asdict()` + `json.dumps()`).
- Verify a minimal stub class satisfying `DocumentParser` protocol passes `isinstance` / `runtime_checkable` check.
- Verify `ParseResult` has no attribute named `docling_document`, `tree`, or `internal_doc`.

---

### 3.2 Task 2: ParseResult and Chunk Dataclasses

> Note: This task is co-located with Task 1 in `parser_base.py`. It is called out separately for traceability to FR-3201 and FR-3202 acceptance criteria.

**Spec requirements:** FR-3201, FR-3202

**Dependencies:** None

**Complexity:** Low

**Target file:** `src/ingest/support/parser_base.py` (same as Task 1)

**Subtasks:**

1. `ParseResult` acceptance criteria (FR-3201):
   - Exactly four fields: `markdown`, `headings`, `has_figures`, `page_count`.
   - No parser-internal types.
   - JSON-serialisable without custom serialisers.

2. `Chunk` acceptance criteria (FR-3202):
   - Exactly six fields: `text`, `section_path`, `heading`, `heading_level`, `chunk_index`, `extra_metadata`.
   - `extra_metadata` values must all be JSON-serialisable.
   - Code parser chunks carry `language`, `function_name`, `class_name`, `docstring`, `imports`, `decorators` keys.
   - Document parser chunks carry `section_path` from heading hierarchy.

3. Add a `validate_extra_metadata(meta: dict[str, Any]) -> None` utility that raises `ValueError` if any value is not JSON-serialisable. Called by parser implementations in debug/test mode.

**Testing strategy:**
- Round-trip `ParseResult` and `Chunk` through `json.dumps(dataclasses.asdict(...))`.
- Verify `validate_extra_metadata` rejects callables, objects with no `__dict__`.

---

### 3.3 Task 3: Docling Parser Adapter (Wrap Existing docling.py)

**Description:** Wrap the existing `parse_with_docling()`, `ensure_docling_ready()`, and `warmup_docling_models()` functions into a `DoclingParser` class that implements the `DocumentParser` protocol. The `DoclingDocument` stays encapsulated inside the class instance.

**Spec requirements:** FR-3221, FR-3223, FR-3224, FR-3205, FR-3206

**Dependencies:** Task 1

**Complexity:** Medium

**Target file:** `src/ingest/support/docling.py` (modify in-place)

**Test file:** `tests/ingest/test_parser_docling.py`

**Subtasks:**

1. Add `DoclingParser` class to `src/ingest/support/docling.py` implementing `DocumentParser`:
   - Instance attribute `_docling_document: Any = None` (internal, never exposed).
   - Instance attribute `_vlm_mode: str` (set from config in `parse()`).
2. `DoclingParser.parse(file_path, config) -> ParseResult`:
   - Calls existing `parse_with_docling()` internally.
   - Stores `DoclingParseResult.docling_document` in `self._docling_document`.
   - Returns `ParseResult(markdown=..., headings=..., has_figures=..., page_count=...)` with no `DoclingDocument`.
   - Respects `config.vlm_mode` passthrough (FR-3224): `"builtin"` enables SmolVLM, `"external"`/`"disabled"` do not.
3. `DoclingParser.chunk(parse_result) -> list[Chunk]`:
   - If `self._docling_document` is not None, use `HybridChunker` on it (existing `_chunk_with_docling` logic).
   - Map HybridChunker output to `Chunk` dataclass: `section_path` from `meta.headings` join, `heading` from last heading, `heading_level` from headings length (FR-3223).
   - `extra_metadata` left empty for document chunks.
   - If `self._docling_document` is None (should not happen under normal flow), raise `RuntimeError`.
4. `DoclingParser.ensure_ready(config)`:
   - Delegates to existing `ensure_docling_ready()`.
5. `DoclingParser.warmup(config)`:
   - Delegates to existing `warmup_docling_models()`.
6. Preserve existing standalone functions (`parse_with_docling`, `ensure_docling_ready`, `warmup_docling_models`) as backward-compatible aliases for callers that have not migrated to the class-based API. Mark with deprecation comment.

**Testing strategy:**
- Contract test: `DoclingParser` satisfies `DocumentParser` protocol.
- Given a mock Docling `ConversionResult`, verify `parse()` returns `ParseResult` with no `docling_document` attribute.
- Verify `chunk()` returns `list[Chunk]` with populated `section_path`/`heading`/`heading_level`.
- Verify calling `chunk()` before `parse()` raises `RuntimeError`.
- Verify per-document isolation: parse doc A, parse doc B on same instance does not leak A's headings into B's chunks (FR-3206 — though SHOULD prefer new instances, sequential reuse must be safe).

---

### 3.4 Task 4: Plain Text Parser

**Description:** Implement `PlainTextParser` for `.md`, `.txt`, `.rst`, `.html`/`.htm` files. Minimal processing, heading-aware markdown chunking.

**Spec requirements:** FR-3280, FR-3281, FR-3282

**Dependencies:** Task 1

**Complexity:** Low–Medium

**Target file:** `src/ingest/support/parser_text.py`

**Test file:** `tests/ingest/test_parser_text.py`

**Subtasks:**

1. Implement `PlainTextParser` class satisfying `DocumentParser` protocol.
2. `parse(file_path, config) -> ParseResult`:
   - Read file content as UTF-8 text.
   - `.html`/`.htm`: convert to markdown using `markdownify` or equivalent (strip tags, preserve `<h1>`-`<h6>` as `#`-`######`). Add `markdownify` as dependency.
   - `.rst`: convert to markdown. Use `docutils` + custom writer or `rst-to-myst`/`pypandoc`. Evaluate lightweight options. If no converter available, treat as plain text with heading heuristic (underline patterns).
   - `.md`, `.txt`: use content as-is.
   - Extract headings from resulting markdown via `_extract_headings_from_markdown()` (reuse from `src/ingest/support/docling.py`; promote to shared utility).
   - Detect figures: scan for `![` markdown image syntax. Set `has_figures` accordingly (FR-3281 item 6).
   - Set `page_count = 0` (FR-3281 item 7).
3. `chunk(parse_result) -> list[Chunk]`:
   - Delegate to the shared markdown chunker (FR-3282, FR-3321).
   - Use existing `chunk_markdown()` from `src/ingest/support/markdown.py` as the base.
   - Map output to `Chunk` dataclass with `section_path`, `heading`, `heading_level` from header metadata.
   - `extra_metadata` is empty for plain text chunks.
   - Table atomicity: ensure markdown table blocks (`|...|` rows) are not split mid-row (FR-3282 item 4). This may require a pre-processing step that wraps table blocks into atomic markers before splitting.
4. `ensure_ready(config)`: No-op (no external dependencies for plain text parsing). Return immediately.
5. `warmup(config)`: No-op.

**Shared utility extraction:**
- Extract `_extract_headings_from_markdown()` from `src/ingest/support/docling.py` into `src/ingest/support/parser_base.py` or `src/ingest/common/shared.py`. Keep a backward-compatible alias in `docling.py`.

**Testing strategy:**
- Parse a markdown file with headings: verify `ParseResult.headings` populated correctly.
- Parse a plain text file with no headings: verify `ParseResult.headings == []`.
- Parse an HTML file with `<h1>`, `<h2>`: verify markdown conversion preserves heading structure.
- Chunk a markdown file: verify chunks align to heading boundaries, `section_path` is correct.
- Chunk a markdown file with a table: verify table is not split mid-row.
- Performance: `parse()` on a 10 KB markdown file completes in < 100ms (FR-3281 AC 1).

---

### 3.5 Task 5: Code Parser (tree-sitter)

**Description:** Implement `CodeParser` using tree-sitter for AST-aware parsing and chunking of source code files. Produces deterministic KG relationships from the AST.

**Spec requirements:** FR-3250, FR-3251, FR-3252, FR-3253, FR-3254, FR-3255, FR-3256

**Dependencies:** Task 1. Requires `tree-sitter` and language grammar packages.

**Complexity:** High

**Target file:** `src/ingest/support/parser_code.py`

**Test file:** `tests/ingest/test_parser_code.py`

**Subtasks:**

1. Add `tree-sitter` dependency to `pyproject.toml`. Add grammar packages for minimum required languages (FR-3251): `tree-sitter-python`, `tree-sitter-rust`, `tree-sitter-go`, `tree-sitter-typescript`, `tree-sitter-javascript`, `tree-sitter-java`, `tree-sitter-c`, `tree-sitter-cpp`, `tree-sitter-c-sharp`, `tree-sitter-ruby`, `tree-sitter-kotlin`, `tree-sitter-swift`, `tree-sitter-scala`, `tree-sitter-bash`, `tree-sitter-yaml`, `tree-sitter-toml`, `tree-sitter-json`.
2. Implement `CodeParser` class satisfying `DocumentParser` protocol.
   - Instance attribute `_tree: Any = None` (internal tree-sitter Tree, never exposed).
   - Instance attribute `_source_bytes: bytes = b""`.
   - Instance attribute `_language: str = ""`.
   - Instance attribute `_file_path: str = ""`.
3. Build an internal `_EXTENSION_TO_LANGUAGE` mapping covering all extensions in FR-3251. Include `Dockerfile` and `Makefile` (matched by filename, not extension).
4. `CodeParser.parse(file_path, config) -> ParseResult` (FR-3256):
   - Read file as bytes.
   - Determine language from extension via `_EXTENSION_TO_LANGUAGE`.
   - Load tree-sitter grammar for the language. Parse into AST. Store `self._tree` and `self._source_bytes`.
   - Build `markdown`: wrap source in a fenced code block with language identifier (e.g., `` ```python\n...\n``` ``).
   - Build `headings`: extract module docstring (Python: first expression statement that is a string) or use filename as single heading.
   - Set `has_figures = False`, `page_count = 0`.
   - Return `ParseResult`.
5. `CodeParser.chunk(parse_result) -> list[Chunk]` (FR-3252, FR-3253):
   - Walk `self._tree` root node's children.
   - Identify top-level function definitions and class definitions using tree-sitter node types (language-specific: `function_definition` for Python, `function_item` for Rust, etc.). Build a language-to-node-type lookup.
   - One chunk per top-level function or class. A module-level chunk for imports/constants/top-level statements that are not functions or classes.
   - For classes exceeding max chunk size: split into one chunk per method.
   - For functions exceeding max chunk size: split at major block boundaries. Log warning if splitting at line boundaries (FR-3252).
   - Populate `Chunk.extra_metadata` per FR-3253: `language`, `file_path`, `function_name`, `class_name`, `docstring`, `imports`, `decorators`.
   - Populate `section_path`: `"module > ClassName > method_name"` style hierarchy.
   - `heading`: function/class name. `heading_level`: 1 for module, 2 for class, 3 for method.
   - No code-to-NL translation (FR-3255): `Chunk.text` is raw source code.
6. KG relationship extraction (FR-3254):
   - Walk AST for import statements -> produce `{type: "imports", source: module_name, target: imported_name}`.
   - Walk class definitions for base classes -> produce `{type: "inherits", source: class_name, target: base_name}`.
   - Walk function call expressions -> produce `{type: "calls", source: enclosing_function, target: called_name}`.
   - Store relationships in `extra_metadata["kg_relationships"]` on the relevant chunk (or on a module-level chunk).
   - All extraction is deterministic — no LLM calls. Re-parsing the same file produces identical results.
7. `CodeParser.ensure_ready(config)`:
   - Verify `tree_sitter` is importable.
   - Verify at least one language grammar can be loaded.
   - Raise `RuntimeError` with install instructions if unavailable (FR-3203).
8. `CodeParser.warmup(config)`:
   - Pre-load grammars for all configured languages. This compiles shared objects if needed.

**Testing strategy:**
- Parse a Python file with 3 functions: verify `chunk()` produces 3 function chunks + 1 module-level chunk.
- Parse a Python class with 5 methods: verify single class chunk or per-method split depending on size.
- Verify no chunk contains a partial function body (FR-3252 AC 3).
- Verify `extra_metadata` on a decorated method contains `function_name`, `class_name`, `decorators`.
- Verify KG relationships: `import os` produces `{type: "imports", source: module, target: "os"}`.
- Verify `class Dog(Animal)` produces `{type: "inherits", source: "Dog", target: "Animal"}`.
- Parse a Rust file and a Go file: verify valid `ParseResult` and `Chunk` objects (FR-3250 AC 2).
- Verify `Chunk.text` is raw source code, not natural language (FR-3255).
- Verify `has_figures=False`, `page_count=0` for all code files (FR-3256).

---

### 3.6 Task 6: Parser Registry and Extension-Based Routing

**Description:** Implement the `ParserRegistry` that maps file extensions to parser strategies and provides parser instances to pipeline nodes.

**Spec requirements:** FR-3300, FR-3301, FR-3302, FR-3303

**Dependencies:** Tasks 1, 3, 4, 5

**Complexity:** Medium

**Target file:** `src/ingest/support/parser_registry.py`

**Test file:** `tests/ingest/test_parser_registry.py`

**Subtasks:**

1. Define `ParserRegistry` class with:
   - `_strategy_map: dict[str, type[DocumentParser]]` — maps strategy name (`"document"`, `"code"`, `"text"`) to concrete parser class.
   - `_extension_map: dict[str, str]` — maps lowercase extension (`.pdf`, `.py`, `.md`) to strategy name. Populated from Appendix A of the spec.
   - `_filename_map: dict[str, str]` — maps exact filenames (`Dockerfile`, `Makefile`) to strategy name.
2. `ParserRegistry.__init__(config: IngestionConfig)`:
   - Register available parsers. Attempt to import each parser class; if import fails (missing dependency), log and skip.
   - At minimum `"text"` strategy must be available (it has no external dependencies). If no strategy is available, raise `RuntimeError` (FR-3203).
   - Build `_extension_map` from the canonical mapping in Appendix A of the spec (FR-3300).
3. `ParserRegistry.get_parser(file_path: Path, config: IngestionConfig) -> DocumentParser`:
   - If `config.parser_strategy != "auto"`, use the forced strategy (FR-3301). Raise `ConfigurationError` if the forced strategy is not registered.
   - Otherwise, look up extension (case-insensitive) in `_extension_map`. Check filename in `_filename_map` for extensionless files.
   - If extension not found, fall back to `"text"` strategy and log warning with filename and extension (FR-3302).
   - Instantiate and return a new parser instance (per-document lifecycle, FR-3206).
4. `ParserRegistry.ensure_all_ready(config: IngestionConfig)`:
   - Call `ensure_ready(config)` on each registered parser class. Called at pipeline startup before any file is processed (FR-3204).
5. `ParserRegistry.warmup_all(config: IngestionConfig)`:
   - Call `warmup(config)` on each registered parser class. For container/deployment pre-warming.

**Integration point:** The registry instance is created during pipeline initialisation in `src/ingest/impl.py` and attached to `Runtime` (or passed to nodes via config). Pipeline nodes call `registry.get_parser(file_path, config)` instead of importing `parse_with_docling` directly.

**Testing strategy:**
- Given `report.pdf`, registry returns `DoclingParser` instance.
- Given `main.py`, registry returns `CodeParser` instance.
- Given `README.md`, registry returns `PlainTextParser` instance.
- Given `REPORT.PDF` (uppercase), registry returns `DoclingParser` (case-insensitive, FR-3300 AC 4).
- Given `config.ini` (unknown extension), registry returns `PlainTextParser` and logs warning (FR-3302).
- Given `parser_strategy="document"` and a `.txt` file, registry returns `DoclingParser` (FR-3301).
- Given `parser_strategy="invalid"`, registry raises config error at startup (FR-3301 AC 3).
- Given Docling not installed, `"document"` strategy is absent from registry; `"text"` is still available.
- Verify pipeline nodes never import concrete parser classes (FR-3303 AC 2).

---

### 3.7 Task 7: Chunker Override Config

**Description:** Add the `chunker` configuration field to `IngestionConfig` and implement the override logic so `chunker="markdown"` forces all parsers to use the shared markdown chunker.

**Spec requirements:** FR-3320, FR-3321, FR-3322, FR-3323

**Dependencies:** Tasks 1, 4 (plain text parser's markdown chunker is the shared implementation)

**Complexity:** Low–Medium

**Target file (config):** `src/ingest/common/types.py`

**Target file (chunker):** `src/ingest/support/markdown.py` (existing) + `src/ingest/support/parser_base.py`

**Target file (validation):** `src/ingest/impl.py`

**Test file:** `tests/ingest/test_chunker_override.py`

**Subtasks:**

1. Add `chunker: str = "native"` field to `IngestionConfig` in `src/ingest/common/types.py` (FR-3320). Add corresponding `RAG_INGESTION_CHUNKER` to `config/settings.py` with default `"native"`.
2. Add `parser_strategy: str = "auto"` field to `IngestionConfig` in `src/ingest/common/types.py` (FR-3301). Add corresponding `RAG_INGESTION_PARSER_STRATEGY` to `config/settings.py` with default `"auto"`.
3. Add chunker validation to `verify_core_design()` in `src/ingest/impl.py`: if `config.chunker` not in `{"native", "markdown"}`, append error "chunker must be 'native' or 'markdown'" (FR-3322).
4. Add parser strategy validation to `verify_core_design()`: if `config.parser_strategy` not in `{"auto", "document", "code", "text"}`, append error (FR-3301 AC 3).
5. Add chunker override warning: if `config.chunker == "markdown"`, log a WARNING at startup (FR-3323). Message: "Chunker override active: all parsers will use markdown-based chunking. Native chunking (with richer heading metadata) is disabled."
6. Extract the shared markdown chunker as a standalone function in `src/ingest/support/parser_base.py`:
   ```python
   def chunk_with_markdown(parse_result: ParseResult, config: IngestionConfig) -> list[Chunk]:
       ...
   ```
   This wraps the existing `chunk_markdown()` from `src/ingest/support/markdown.py` and maps output to `Chunk` dataclass (FR-3321).
7. Wire the override into parser `chunk()` calls: when `config.chunker == "markdown"`, the pipeline calls `chunk_with_markdown(parse_result, config)` instead of `parser.chunk(parse_result)`. This logic lives in the calling node, not inside each parser. Parsers always implement native chunking; the override is external.

**Testing strategy:**
- `chunker="native"` + Docling: verify HybridChunker used (FR-3320 AC 1).
- `chunker="markdown"` + Docling: verify markdown splitter used, not HybridChunker (FR-3320 AC 2).
- `chunker="markdown"` + code file: verify markdown splitter used (FR-3320 AC 3).
- `chunker="hybrid"` (invalid): verify config error at startup (FR-3322).
- `chunker="markdown"`: verify WARNING log emitted (FR-3323).
- `chunker="native"`: verify no override warning.

---

### 3.8 Task 8: VLM Mode Validation Guard

**Description:** Add the VLM mutual exclusion check that prevents `vlm_mode="builtin"` and `enable_multimodal_processing=true` from both being active. Integrate into the existing `verify_core_design()` validation framework.

**Spec requirements:** FR-3340, FR-3341, FR-3342

**Dependencies:** None (can be implemented independently)

**Complexity:** Low

**Target file:** `src/ingest/impl.py` (add to `verify_core_design()`)

**Test file:** `tests/ingest/test_vlm_guard.py`

**Subtasks:**

1. Add the mutual exclusion check to `verify_core_design()` in `src/ingest/impl.py` (FR-3340, FR-3341):
   ```python
   if config.vlm_mode == "builtin" and config.enable_multimodal_processing:
       errors.append(
           "vlm_mode='builtin' and enable_multimodal_processing=true are mutually "
           "exclusive. vlm_mode='builtin' describes figures at parse time via Docling "
           "SmolVLM. enable_multimodal_processing describes figures in the Phase 1 "
           "multimodal node via vision.py. Disable one to prevent double VLM "
           "processing of figure images."
       )
   ```
2. Add the informational coexistence log (FR-3342):
   ```python
   if config.vlm_mode == "external" and config.enable_multimodal_processing:
       warnings.append(
           "vlm_mode='external' and enable_multimodal_processing are both active. "
           "Phase 1 multimodal node will process figures pre-chunking; "
           "vlm_mode='external' will enrich chunks post-chunking. Both being active "
           "is valid but means figures are processed at two pipeline stages."
       )
   ```
   Note: this is a WARNING-level message via the design check `warnings` list. The spec says INFO level (FR-3342), but the `IngestionDesignCheck` framework surfaces these as warnings. This is consistent with the existing pattern.

**Testing strategy:**
- `vlm_mode="builtin"` + `enable_multimodal_processing=true`: verify `IngestionDesignCheck.ok == False` with descriptive error (FR-3340 AC 1).
- `vlm_mode="builtin"` + `enable_multimodal_processing=false`: verify ok (FR-3340 AC 3).
- `vlm_mode="disabled"` + `enable_multimodal_processing=true`: verify ok (FR-3340 AC 4).
- `vlm_mode="external"` + `enable_multimodal_processing=true`: verify ok with info warning (FR-3342).
- `vlm_mode="disabled"` + `enable_multimodal_processing=false`: verify ok, no warnings.
- `vlm_mode="external"` + `enable_multimodal_processing=false`: verify ok, no warnings.
- All six combinations from Appendix C of the spec are covered.

---

### 3.9 Task 9: Update structure_detection and chunking Nodes

**Description:** Modify the two pipeline nodes that currently couple directly to Docling to use the parser abstraction instead.

**Spec requirements:** FR-3200 (AC 4: no pipeline node imports concrete parser), FR-3205 (AC 2: no parser-internal objects in state), FR-3303 (AC 2: parsers obtained via registry)

**Dependencies:** Tasks 1, 3, 4, 5, 6, 7

**Complexity:** Medium

**Target files:**
- `src/ingest/doc_processing/nodes/structure_detection.py`
- `src/ingest/embedding/nodes/chunking.py`
- `src/ingest/common/types.py` (state schema changes)
- `src/ingest/embedding/state.py` (state schema changes)

**Subtasks:**

1. **State schema changes** (`src/ingest/common/types.py` and `src/ingest/embedding/state.py`):
   - Remove `docling_document` key from `IngestState` TypedDict.
   - Add `parse_result: ParseResult` key to `IngestState` (or a serialisable representation).
   - Remove `docling_document` key from `EmbeddingPipelineState`.
   - Add `parse_result` key to `EmbeddingPipelineState`.
   - Add `parser_instance` key (type `Any`) to carry the parser between `parse()` and `chunk()` calls. This is the parser object itself, which holds opaque internal state. It is NOT serialised or persisted — it only exists in the in-memory LangGraph state for the duration of one document's processing.

2. **Update `structure_detection_node`** (`src/ingest/doc_processing/nodes/structure_detection.py`):
   - Remove direct `from src.ingest.support import parse_with_docling` import.
   - Obtain parser via registry: `parser = registry.get_parser(Path(state["source_path"]), config)`.
   - The registry is accessed via `state["runtime"].parser_registry` (requires adding `parser_registry` attribute to `Runtime`).
   - Call `parse_result = parser.parse(Path(state["source_path"]), config)`.
   - Store `parse_result` in state update (not `docling_document`).
   - Store `parser` instance in state update as `parser_instance` for `chunking_node` to call `chunk()`.
   - Derive structure signals from `parse_result`: `has_figures = parse_result.has_figures`, headings from `parse_result.headings`.
   - Replace `structure["docling_document_available"]` routing flag with `structure["parser_strategy"]` (e.g., `"document"`, `"code"`, `"text"`) for downstream routing decisions.
   - Preserve fallback behaviour: if parser fails in non-strict mode, fall back to regex heuristics (existing pattern).
   - Update `raw_text` to `parse_result.markdown` (preserves existing downstream consumption).

3. **Update `chunking_node`** (`src/ingest/embedding/nodes/chunking.py`):
   - Remove direct `from docling_core.transforms.chunker import HybridChunker` import.
   - Remove `_chunk_with_docling()` function (its logic moves into `DoclingParser.chunk()`).
   - Retrieve `parser_instance` and `parse_result` from state.
   - If `config.chunker == "markdown"`: call `chunk_with_markdown(parse_result, config)`.
   - If `config.chunker == "native"`: call `parser_instance.chunk(parse_result)`.
   - Map `Chunk` objects to `ProcessedChunk` (existing downstream type), merging `Chunk` fields with `base_metadata`.
   - Preserve the `_normalize_chunk_text()` call on chunk text.
   - Error handling: if chunking fails, fall back to `chunk_with_markdown()` (preserves existing fallback pattern from current `_chunk_with_docling` error handling).

4. **Update `Runtime`** (`src/ingest/common/types.py`):
   - Add `parser_registry: Any` field to `Runtime` dataclass (typed as `Any` to avoid circular import; actual type is `ParserRegistry`).

5. **Update pipeline initialisation** (`src/ingest/impl.py`):
   - Create `ParserRegistry(config)` during pipeline setup.
   - Call `registry.ensure_all_ready(config)` at startup.
   - Pass registry into `Runtime`.

**Testing strategy:**
- End-to-end: ingest a PDF with the new parser abstraction; verify chunks are produced identically to the current system.
- End-to-end: ingest a markdown file; verify `PlainTextParser` is routed and chunks are correct.
- Verify `docling_document` no longer appears in pipeline state at any point.
- Verify `parse_result` is present in state after `structure_detection_node`.
- Verify `chunking_node` calls `parser.chunk()`, not HybridChunker directly.
- Verify `chunker="markdown"` override works end-to-end.

---

## 4. Interface Contracts (Python Protocol/ABC Definitions)

### 4.1 DocumentParser Protocol

```python
# src/ingest/support/parser_base.py

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from src.ingest.common.types import IngestionConfig


@dataclass
class ParseResult:
    """Unified output of parser.parse(). FR-3201.

    Contains parser-agnostic document metadata. No parser-internal
    types (DoclingDocument, tree-sitter Tree) may appear here.
    """

    markdown: str
    headings: list[str]
    has_figures: bool
    page_count: int


@dataclass
class Chunk:
    """Unified output element of parser.chunk(). FR-3202.

    extra_metadata values MUST be JSON-serialisable.
    """

    text: str
    section_path: str
    heading: str
    heading_level: int
    chunk_index: int
    extra_metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class DocumentParser(Protocol):
    """Abstract parser interface. FR-3200.

    Implementations MUST encapsulate parser-internal types.
    Pipeline nodes access parsers ONLY through this protocol.
    Per-document instance lifecycle is RECOMMENDED (FR-3206).
    """

    def parse(self, file_path: Path, config: IngestionConfig) -> ParseResult:
        """Parse a source file into a ParseResult.

        Internal state (e.g., DoclingDocument, AST) MAY be retained
        for use by chunk() but MUST NOT appear in ParseResult.
        """
        ...

    def chunk(self, parse_result: ParseResult) -> list[Chunk]:
        """Produce chunks from a previously parsed document.

        Uses parser-internal state retained from parse().
        """
        ...

    @classmethod
    def ensure_ready(cls, config: IngestionConfig) -> None:
        """Validate runtime dependencies. Called at pipeline startup. FR-3204."""
        ...

    @classmethod
    def warmup(cls, config: IngestionConfig) -> None:
        """Download/compile expensive assets. FR-3207. Optional."""
        ...
```

### 4.2 Chunk-to-ProcessedChunk Mapping

The existing `ProcessedChunk` type (`src/ingest/common/schemas.py`) is the downstream format consumed by embedding, KG, and quality validation nodes. The mapping from `Chunk` to `ProcessedChunk` is:

```python
def chunk_to_processed(chunk: Chunk, base_metadata: dict[str, Any]) -> ProcessedChunk:
    """Map parser Chunk to pipeline ProcessedChunk."""
    return ProcessedChunk(
        text=_normalize_chunk_text(chunk.text),
        metadata={
            **base_metadata,
            "section_path": chunk.section_path,
            "heading": chunk.heading,
            "heading_level": chunk.heading_level,
            "chunk_index": chunk.chunk_index,
            "total_chunks": 0,  # Set after all chunks are produced
            **chunk.extra_metadata,
        },
    )
```

This mapping lives in `chunking_node` and preserves the current `ProcessedChunk` contract for all downstream consumers. No downstream node changes are required.

### 4.3 ParserRegistry Interface

```python
# src/ingest/support/parser_registry.py

class ParserRegistry:
    """Maps file extensions to parser strategies. FR-3303."""

    def __init__(self, config: IngestionConfig) -> None:
        """Register available parsers. At least 'text' must be available."""
        ...

    def get_parser(self, file_path: Path, config: IngestionConfig) -> DocumentParser:
        """Return a new parser instance for the given file. FR-3300, FR-3301, FR-3302."""
        ...

    def ensure_all_ready(self, config: IngestionConfig) -> None:
        """Call ensure_ready() on all registered parsers. FR-3204."""
        ...

    def warmup_all(self, config: IngestionConfig) -> None:
        """Call warmup() on all registered parsers. FR-3207."""
        ...
```

---

## 5. Dependency Graph

```text
Task 1: Parser Interface (Protocol + ParseResult + Chunk)
    │
    ├──► Task 3: Docling Parser Adapter
    │        │
    ├──► Task 4: Plain Text Parser
    │        │
    ├──► Task 5: Code Parser (tree-sitter)
    │        │
    └──► Task 7: Chunker Override Config ──────────────────┐
              │                                             │
              ▼                                             │
         Task 6: Parser Registry ◄──────────────────────────┤
              │                                             │
              ▼                                             ▼
         Task 9: Update structure_detection + chunking nodes
              │
              ▼
         Pipeline works end-to-end with parser abstraction


Task 8: VLM Mode Validation Guard
    │
    └──► (Independent — can be implemented at any time)
```

**Recommended implementation order:**

| Phase | Tasks | Rationale |
|-------|-------|-----------|
| Phase A (Foundation) | Task 1, Task 8 | Define contracts and implement the zero-dependency VLM guard. Both are independently testable. |
| Phase B (Parsers) | Task 3, Task 4, Task 5 (parallel) | Implement all three parsers against the protocol. Each is independently testable with unit tests. |
| Phase C (Routing) | Task 6, Task 7 | Registry and config additions. Depends on at least one parser existing. |
| Phase D (Integration) | Task 9 | Wire everything into the pipeline. This is the riskiest change and should be last. |

---

## 6. Migration Path (Backward Compatibility)

### 6.1 Incremental Migration Strategy

The migration is designed to be non-breaking at each phase:

1. **Phase A (Foundation):** New files only. No existing code changes. `ParseResult`, `Chunk`, `DocumentParser` protocol are additive. VLM guard is a new validation check added to `verify_core_design()`.

2. **Phase B (Parsers):** `DoclingParser` is added to `src/ingest/support/docling.py` alongside the existing standalone functions. Existing callers of `parse_with_docling()` continue to work. The standalone functions are preserved as backward-compatible aliases with deprecation comments. `PlainTextParser` and `CodeParser` are new files with no existing callers.

3. **Phase C (Routing):** `ParserRegistry` is a new file. New config fields (`parser_strategy`, `chunker`) have defaults that preserve existing behaviour (`"auto"`, `"native"`). No existing behaviour changes.

4. **Phase D (Integration):** This is the breaking change:
   - `structure_detection_node` stops calling `parse_with_docling()` directly.
   - `chunking_node` stops importing `HybridChunker` directly.
   - `docling_document` is removed from pipeline state.
   - `parse_result` and `parser_instance` are added to pipeline state.

### 6.2 State Schema Migration

| Change | Old | New | Migration |
|--------|-----|-----|-----------|
| Remove `docling_document` | `IngestState["docling_document"]: Any` | Removed | Delete key from TypedDict. No serialisation impact (was never persisted to durable storage). |
| Add `parse_result` | N/A | `IngestState["parse_result"]: ParseResult` | Add key. Default: None until `structure_detection_node` runs. |
| Add `parser_instance` | N/A | `IngestState["parser_instance"]: Any` | Add key. Transient — only lives in in-memory LangGraph state. Never serialised. |
| Remove `docling_document` routing flag | `structure["docling_document_available"]: bool` | `structure["parser_strategy"]: str` | Downstream conditional edges updated to check strategy name instead of boolean. |

### 6.3 Config Field Migration

| Field | Default | Backward Compatible? |
|-------|---------|---------------------|
| `parser_strategy` | `"auto"` | Yes. `"auto"` preserves current extension-based routing (Docling for all). |
| `chunker` | `"native"` | Yes. `"native"` preserves current HybridChunker behaviour for Docling-parsed docs. |

### 6.4 Import Compatibility

The following imports are preserved as backward-compatible aliases in Phase B:

```python
# src/ingest/support/docling.py — preserved aliases
from src.ingest.support.docling import parse_with_docling       # Still works
from src.ingest.support.docling import ensure_docling_ready      # Still works
from src.ingest.support.docling import warmup_docling_models     # Still works
from src.ingest.support.docling import DoclingParseResult        # Still works
```

These aliases are marked with `# DEPRECATED: Use DoclingParser class instead` comments. They will be removed in a future release after all callers migrate.

### 6.5 Downstream Node Impact

| Node | Impact | Change Required? |
|------|--------|-----------------|
| `text_cleaning_node` | Reads `state["raw_text"]` (markdown) | No change. `raw_text` is still populated from `parse_result.markdown`. |
| `document_refactoring_node` | Reads `state["cleaned_text"]` | No change. |
| `vlm_enrichment_node` | Reads `state["chunks"]` | No change. Chunks are `ProcessedChunk` regardless of parser. |
| `chunk_enrichment_node` | Reads `state["chunks"]` | No change. |
| `metadata_generation_node` | Reads `state["chunks"]` | No change. |
| `knowledge_graph_extraction_node` | Reads `state["chunks"]`, extracts entities | May benefit from `extra_metadata["kg_relationships"]` for code chunks (FR-3254), but this is additive — existing LLM-based extraction still works for document/text chunks. |
| `quality_validation_node` | Reads `state["chunks"]` | No change. |
| `embedding_storage_node` | Reads `state["chunks"]` | No change. |

---

## 7. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| **HybridChunker behaviour changes when called from `DoclingParser` vs current inline path** | Low | Medium — different chunk boundaries could affect retrieval quality | Task 3 includes regression tests comparing chunk output before and after the adapter wrap. Run against a golden test corpus. |
| **tree-sitter grammar installation adds deployment complexity** | Medium | Medium — code parser unavailable in environments without grammars | `ensure_ready()` fails fast with clear install instructions. `PlainTextParser` fallback for unrecognised code extensions. Document grammar installation in deployment guide. |
| **`parser_instance` in LangGraph state is not serialisable** | Low | Low — only matters if LangGraph checkpointing is enabled (currently deferred per Gap 1) | Document that `parser_instance` is transient. If checkpointing is added later, the parser must be re-instantiated from `parse_result` on resume (re-parse the file). |
| **Removing `docling_document` from state breaks any external tool reading state** | Low | Medium — any monitoring/debugging tool inspecting state would break | The state key was always typed as `Any` with no guaranteed schema. No external tools are known to depend on it. Add migration note to engineering guide. |
| **Markdown chunker produces lower-quality heading metadata than HybridChunker** | Known | Low — this is the documented trade-off of `chunker="markdown"` | FR-3323 startup warning informs operators. `chunker="native"` remains the default. |
| **Large code files produce too many chunks (one per function)** | Medium | Low — many small chunks may crowd retrieval results | Configurable max chunk count per file (future enhancement). For now, this matches the spec's design intent: function-level granularity is correct for code search. |
| **RST-to-markdown conversion quality varies** | Medium | Low — RST files are a minority use case | Start with a lightweight converter. If quality is insufficient, users can override with `parser_strategy="document"` to route RST through Docling. |
