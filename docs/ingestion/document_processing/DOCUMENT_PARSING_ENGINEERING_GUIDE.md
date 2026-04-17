> **Document type:** Engineering guide (Layer 5)
> **Upstream:** DOCUMENT_PARSING_IMPLEMENTATION.md
> **Last updated:** 2026-04-17
> **Status:** Authoritative (post-implementation)

# Document Parsing Engineering Guide

## 1. Overview

The Document Parsing Abstraction replaces the former Docling-coupled parsing path with a pluggable strategy system. All parsing now flows through a single `DocumentParser` protocol. Pipeline nodes never import concrete parser classes or handle parser-internal types (`DoclingDocument`, tree-sitter `Tree`).

**Functional requirements covered:** FR-3200–FR-3342.

Three problems drove this design:

1. **Docling lock-in.** `DoclingDocument` had leaked into `IngestState`, `EmbeddingPipelineState`, and two pipeline nodes. Swapping parsers required modifying every consumer.
2. **No code or plain text support.** Source code and markdown files were forced through Docling's OCR/layout path, wasting compute and losing AST structure.
3. **Silent double VLM processing.** `vlm_mode="builtin"` and `enable_multimodal_processing=true` could both be active with no warning.

---

## 2. Module Layout

```
src/ingest/
├── support/
│   ├── __init__.py                     # Re-exports: DocumentParser, ParseResult,
│   │                                   #   Chunk, chunk_with_markdown,
│   │                                   #   validate_extra_metadata, ParserRegistry
│   ├── parser_base.py                  # Protocol + dataclasses + shared helpers
│   ├── parser_registry.py              # ParserRegistry, get_parser_for(),
│   │                                   #   ensure_all_ready()
│   ├── parser_text.py                  # PlainTextParser (.md, .txt, .rst, .html)
│   ├── parser_code.py                  # CodeParser (tree-sitter AST)
│   └── docling.py                      # DoclingParser + legacy standalone functions
├── common/
│   └── types.py                        # IngestionConfig (parser_strategy, chunker),
│                                       #   Runtime (parser_registry field)
├── doc_processing/
│   └── nodes/
│       └── structure_detection.py      # Calls registry.get_parser() + parser.parse()
└── embedding/
    └── nodes/
        └── chunking.py                 # Calls parser.chunk() or chunk_with_markdown()
```

| File | Exports |
|------|---------|
| `parser_base.py` | `DocumentParser`, `ParseResult`, `Chunk`, `chunk_with_markdown`, `validate_extra_metadata` |
| `parser_registry.py` | `ParserRegistry`, `get_parser_for`, `ensure_all_ready` |
| `parser_text.py` | `PlainTextParser` |
| `parser_code.py` | `CodeParser` |
| `docling.py` | `DoclingParser`, `DoclingParseResult`, `parse_with_docling`, `ensure_docling_ready`, `warmup_docling_models` |

---

## 3. Key Abstractions

### 3.1 `DocumentParser` Protocol

```python
@runtime_checkable
class DocumentParser(Protocol):
    def parse(self, file_path: Path, config: Any) -> ParseResult: ...
    def chunk(self, parse_result: ParseResult) -> list[Chunk]: ...

    @classmethod
    def ensure_ready(cls, config: Any) -> None: ...

    @classmethod
    def warmup(cls, config: Any) -> None: ...
```

- `parse()` may retain internal state (e.g., `DoclingDocument`, AST) on the instance between calls. That state must never appear in `ParseResult`.
- `chunk()` before `parse()` must raise `RuntimeError`.
- `ensure_ready()` is called at pipeline startup to validate runtime dependencies.
- `warmup()` pre-downloads models; called during deployment. Implementations without expensive init are no-ops.
- `isinstance(obj, DocumentParser)` works at runtime because the protocol is `@runtime_checkable`.

### 3.2 `ParseResult` Dataclass

```python
@dataclass
class ParseResult:
    markdown: str
    headings: list[str]
    has_figures: bool
    page_count: int
```

All fields are JSON-serialisable. No parser-internal types may appear here (FR-3201).

### 3.3 `Chunk` Dataclass

```python
@dataclass
class Chunk:
    text: str
    section_path: str
    heading: str
    heading_level: int
    chunk_index: int
    extra_metadata: dict[str, Any] = field(default_factory=dict)
```

`extra_metadata` values must be JSON-serialisable. Code parser chunks carry `language`, `function_name`, `class_name`, `docstring`, `imports`, `decorators`, `kg_relationships`. Document parser chunks typically leave `extra_metadata` empty (FR-3202).

### 3.4 `DoclingParser`

`src/ingest/support/docling.py`

```python
class DoclingParser:
    def __init__(self) -> None: ...
    def parse(self, file_path: Path, config: Any) -> ParseResult: ...
    def chunk(self, parse_result: ParseResult) -> list[Chunk]: ...
    @classmethod
    def ensure_ready(cls, config: Any) -> None: ...
    @classmethod
    def warmup(cls, config: Any) -> None: ...
```

- `parse()` calls `parse_with_docling()` internally, stores the `DoclingDocument` in `self._docling_document`. Returns `ParseResult` with no `docling_document` attribute.
- `chunk()` uses Docling's `HybridChunker(max_tokens=self._max_tokens, merge_peers=True)`. Heading hierarchy is derived from `HybridChunker` metadata's `headings` list: the last entry becomes `heading`, the full join becomes `section_path`, and the list length becomes `heading_level`.
- `ensure_ready()` delegates to `ensure_docling_ready()`.
- `warmup()` delegates to `warmup_docling_models()`. When `vlm_mode="builtin"`, `with_smolvlm=True` is passed.

Config fields consumed: `docling_model`, `docling_artifacts_path`, `vlm_mode`, `generate_page_images`, `hybrid_chunker_max_tokens`, `docling_auto_download`.

### 3.5 `PlainTextParser`

`src/ingest/support/parser_text.py`

```python
class PlainTextParser:
    def __init__(self) -> None: ...
    def parse(self, file_path: Path, config: Any) -> ParseResult: ...
    def chunk(self, parse_result: ParseResult) -> list[Chunk]: ...
    @classmethod
    def ensure_ready(cls, config: Any) -> None: ...   # no-op
    @classmethod
    def warmup(cls, config: Any) -> None: ...         # no-op
```

- `.md`, `.txt`: content used as-is.
- `.html`, `.htm`: converted via `markdownify` (optional); falls back to a regex tag stripper that preserves `<h1>`–`<h6>` as ATX headings.
- `.rst`: converted via `pypandoc` (optional); falls back to a heading heuristic that detects `===`, `---`, `~~~` underline patterns.
- `has_figures` is `True` when `![...](...) ` pattern is found.
- `page_count` is always `0`.
- `chunk()` delegates to `chunk_with_markdown(parse_result, config)`.
- No external dependencies required. `markdownify` and `pypandoc` are optional.

### 3.6 `CodeParser`

`src/ingest/support/parser_code.py`

```python
class CodeParser:
    def __init__(self) -> None: ...
    def parse(self, file_path: Path, config: Any) -> ParseResult: ...
    def chunk(self, parse_result: ParseResult) -> list[Chunk]: ...
    @classmethod
    def ensure_ready(cls, config: Any) -> None: ...
    @classmethod
    def warmup(cls, config: Any) -> None: ...
```

- `parse()` reads file bytes, loads the tree-sitter grammar for the file's language, and builds an AST stored in `self._tree`. `ParseResult.markdown` wraps the full source in a fenced code block (e.g., ` ```python\n<source>\n``` `). `has_figures` is always `False`, `page_count` is always `0`.
- `chunk()` walks `self._tree.root_node` children and produces one `Chunk` per top-level function or class definition, plus an optional module-level chunk for imports and top-level statements. Falls back to a single chunk when `self._tree` is `None` (tree-sitter parse failure).
- `extra_metadata` keys per function/class chunk: `language`, `file_path`, `function_name`, `class_name`, `docstring`, `imports`, `decorators`, `kg_relationships`.
- KG relationships are deterministic (no LLM): `imports`, `inherits`, `calls`.
- Grammar loading uses `importlib.import_module(f"tree_sitter_{language}")`. Grammars must be installed separately (e.g., `uv add tree-sitter-python`).
- `ensure_ready()` verifies `tree_sitter` is importable; raises `RuntimeError` with install instructions if not. Checks `tree_sitter_python` as a canary grammar (warning-only if absent).

### 3.7 `ParserRegistry`

`src/ingest/support/parser_registry.py`

```python
class ParserRegistry:
    def __init__(self, config: Any) -> None: ...
    def get_parser(self, file_path: Path, config: Any) -> DocumentParser: ...
    def ensure_all_ready(self, config: Any) -> None: ...
    def warmup_all(self, config: Any) -> None: ...

    @property
    def available_strategies(self) -> list[str]: ...
```

- Always registers `PlainTextParser` as `"text"` (no external deps, always available).
- Registers `DoclingParser` as `"document"` if `config.enable_docling_parser=True` and `docling` imports successfully.
- Registers `CodeParser` as `"code"` if `tree_sitter` imports successfully.
- `get_parser()` returns a new parser instance per call (per-document lifecycle, FR-3206).
- If the resolved strategy's dependency is missing, falls back to `"text"` with a warning.
- `warmup_all()` is non-fatal: warmup failures are logged but do not prevent startup.

### 3.8 `chunk_with_markdown`

```python
def chunk_with_markdown(parse_result: ParseResult, config: Any) -> list[Chunk]:
```

Shared markdown chunker used by `PlainTextParser.chunk()` and as a fallback/override in `chunking_node`. Wraps `chunk_markdown()` from `src.ingest.support.markdown` and maps output to `Chunk` with `section_path`, `heading`, and `heading_level` populated from the heading hierarchy.

### 3.9 `validate_extra_metadata`

```python
def validate_extra_metadata(meta: dict[str, Any]) -> None:
```

Validates that all `extra_metadata` values are JSON-serialisable. Raises `ValueError` if any value cannot be serialised. Called in debug/test mode by parser implementations.

---

## 4. Parser Selection Flow

`ParserRegistry.get_parser()` uses the following decision tree:

```
config.parser_strategy != "auto"?
    YES → Use forced strategy directly.
          Raise RuntimeError if strategy not registered.
    NO  →
          file_path.name in _FILENAME_MAP?
              YES → Use mapped strategy.
              NO  →
                    file_path.suffix.lower() in _EXTENSION_MAP?
                        YES → Use mapped strategy.
                        NO  → Warn "Unrecognised extension"; use "text" fallback.
                    |
                    Is resolved strategy registered?
                        YES → Instantiate and return.
                        NO  → Warn "Strategy not available; missing dependency";
                              fall back to "text".
```

### Extension mapping summary

| Strategy | Extensions | Special filenames |
|----------|-----------|-------------------|
| `document` | `.pdf`, `.docx`, `.pptx`, `.xlsx`, `.png`, `.jpg`, `.jpeg`, `.tiff`, `.bmp` | — |
| `code` | `.py`, `.rs`, `.go`, `.ts`, `.tsx`, `.js`, `.jsx`, `.java`, `.c`, `.h`, `.cpp`, `.hpp`, `.cc`, `.cxx`, `.cs`, `.rb`, `.kt`, `.swift`, `.scala`, `.sh`, `.bash`, `.zsh`, `.yaml`, `.yml`, `.toml`, `.json` | `Dockerfile`, `Makefile` |
| `text` | `.md`, `.txt`, `.rst`, `.html`, `.htm` | — |

Extensions are matched case-insensitively. Filenames in `_FILENAME_MAP` are case-sensitive.

---

## 5. Configuration

### `IngestionConfig` fields

| Field | Type | Default | Env var | Description |
|-------|------|---------|---------|-------------|
| `parser_strategy` | `str` | `"auto"` | `RAG_INGESTION_PARSER_STRATEGY` | `"auto"` routes by extension; `"document"`, `"code"`, or `"text"` forces a strategy for all files. |
| `chunker` | `str` | `"native"` | `RAG_INGESTION_CHUNKER` | `"native"` uses each parser's internal chunker; `"markdown"` forces heading-aware markdown splitting for all parsers. |
| `enable_docling_parser` | `bool` | `True` | `RAG_INGESTION_DOCLING_ENABLED` | When `False`, `DoclingParser` is not registered and `.pdf`/`.docx` etc. fall back to `"text"`. |
| `docling_model` | `str` | — | `RAG_INGESTION_DOCLING_MODEL` | Docling model identifier. Required by `DoclingParser.ensure_ready()`. |
| `docling_artifacts_path` | `str` | `""` | `RAG_INGESTION_DOCLING_ARTIFACTS_PATH` | Directory for Docling model artifacts. Empty string uses Docling/HF default cache. |
| `docling_auto_download` | `bool` | `True` | `RAG_INGESTION_DOCLING_AUTO_DOWNLOAD` | Auto-download missing Docling models on `ensure_ready()`. |
| `docling_strict` | `bool` | `False` | `RAG_INGESTION_DOCLING_STRICT` | When `True`, parser failures in `structure_detection_node` set `should_skip=True` instead of falling back to regex. |
| `hybrid_chunker_max_tokens` | `int` | `512` | `RAG_INGESTION_HYBRID_CHUNKER_MAX_TOKENS` | Max tokens per chunk for Docling's `HybridChunker`. |
| `vlm_mode` | `str` | `"disabled"` | `RAG_INGESTION_VLM_MODE` | `"builtin"` activates Docling's SmolVLM at parse time. `"external"` or `"disabled"` leaves `do_picture_description=False`. |
| `chunk_size` | `int` | `CHUNK_SIZE` | — | Max characters per chunk for markdown splitter. Used by `chunk_with_markdown()`. |
| `chunk_overlap` | `int` | `CHUNK_OVERLAP` | — | Overlap characters for markdown splitter. Used by `chunk_with_markdown()`. |

### VLM mode exclusion constraint

Setting `vlm_mode="builtin"` and `enable_multimodal_processing=True` simultaneously is invalid. The pipeline raises an `IngestionDesignCheck` error at startup. Valid combinations:

| `vlm_mode` | `enable_multimodal_processing` | Result |
|------------|-------------------------------|--------|
| `disabled` | `false` | No VLM processing. |
| `disabled` | `true` | Phase 1 multimodal node only. |
| `builtin` | `false` | Docling SmolVLM at parse time. |
| `builtin` | `true` | **ERROR** — mutual exclusion. |
| `external` | `false` | Post-chunking VLM enrichment only. |
| `external` | `true` | Both stages active (valid). |

---

## 6. Adding a New Parser

### Step 1: Implement the class

Create `src/ingest/support/parser_<name>.py`:

```python
# @summary
# <Name> parser implementing DocumentParser protocol.
# Exports: <Name>Parser
# Deps: pathlib, src.ingest.support.parser_base
# @end-summary

from __future__ import annotations
from pathlib import Path
from typing import Any
from src.ingest.support.parser_base import Chunk, ParseResult

class <Name>Parser:
    def __init__(self) -> None:
        self._internal_doc: Any = None   # Never exposed in ParseResult or Chunk
        self._config: Any = None

    def parse(self, file_path: Path, config: Any) -> ParseResult:
        self._config = config
        # ... parse file, store internal state on self ...
        return ParseResult(
            markdown="...",
            headings=["..."],
            has_figures=False,
            page_count=0,
        )

    def chunk(self, parse_result: ParseResult) -> list[Chunk]:
        if self._internal_doc is None:
            raise RuntimeError("<Name>Parser.chunk() called before parse().")
        # ... chunk using self._internal_doc ...
        return [
            Chunk(
                text="...",
                section_path="...",
                heading="...",
                heading_level=1,
                chunk_index=idx,
                extra_metadata={},  # Must be JSON-serialisable
            )
            for idx, ... in enumerate(...)
        ]

    @classmethod
    def ensure_ready(cls, config: Any) -> None:
        try:
            import <dependency>  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "<Dependency> is required but not installed. "
                "Install with: uv add <package>"
            ) from exc

    @classmethod
    def warmup(cls, config: Any) -> None:
        cls.ensure_ready(config)
```

**Rules:**
- `parse()` returns `ParseResult` with exactly four fields. No internal types.
- `chunk()` returns `list[Chunk]`. All `extra_metadata` values must pass `json.dumps()`.
- `chunk()` before `parse()` must raise `RuntimeError`.
- Internal state stays on `self`. It must not appear in `ParseResult`, `Chunk`, or pipeline state.

### Step 2: Register in `ParserRegistry`

In `src/ingest/support/parser_registry.py`, add to `ParserRegistry.__init__()`:

```python
# Attempt to register <Name> parser
if getattr(config, "enable_<name>_parser", False):
    try:
        from src.ingest.support.parser_<name> import <Name>Parser
        self._strategy_map["<strategy>"] = <Name>Parser
    except ImportError:
        logger.info("<Name> not available; '<strategy>' parser strategy disabled.")
```

If replacing the `"document"` strategy, use `self._strategy_map["document"] = <Name>Parser`. If adding a new strategy, use a distinct strategy name and add extension mappings to `_EXTENSION_MAP`.

### Step 3: Add config fields if needed

```python
# config/settings.py
RAG_INGESTION_ENABLE_<NAME>_PARSER: bool = os.getenv(
    "RAG_INGESTION_ENABLE_<NAME>_PARSER", "false"
).lower() == "true"

# src/ingest/common/types.py, in IngestionConfig
enable_<name>_parser: bool = RAG_INGESTION_ENABLE_<NAME>_PARSER
```

### Step 4: Test against the contract

Every parser implementation must pass the contract test suite in `tests/ingest/test_parser_integration.py`. Write additional unit tests verifying parser-specific behaviour.

---

## 7. Adding a New Language to CodeParser

**Step 1.** Install the grammar package:

```bash
uv add tree-sitter-<language>
```

**Step 2.** Add the extension mapping in `parser_code.py`:

```python
_EXTENSION_TO_LANGUAGE[".ext"] = "<language>"
```

**Step 3.** Identify AST node types for function and class/type definitions. Use the tree-sitter playground or inspect the S-expression:

```python
import tree_sitter, tree_sitter_<language>
lang = tree_sitter.Language(tree_sitter_<language>.language())
parser = tree_sitter.Parser(lang)
tree = parser.parse(open("example.<ext>", "rb").read())
print(tree.root_node.sexp())
```

**Step 4.** Add the relevant node types to `_is_function_def()` and `_is_class_def()`.

**Step 5.** If the language's import syntax uses a different node type, add it to `_extract_imports()`.

---

## 8. Node Integration

### `structure_detection_node`

`src/ingest/doc_processing/nodes/structure_detection.py`

This node selects one of three paths at runtime:

**Path 1 — Parser abstraction (primary):** `runtime.parser_registry` is set.
1. Calls `registry.get_parser(Path(state["source_path"]), config)` to get a parser instance.
2. Calls `parser_instance.parse(Path(state["source_path"]), config)` to get a `ParseResult`.
3. Stores `parse_result` and `parser_instance` in the state update.
4. Derives `has_figures`, `heading_count`, and `parser_strategy` from `ParseResult` fields.
5. On failure: if `config.docling_strict`, returns `should_skip=True`. Otherwise falls back to regex heuristics and sets `parser_strategy="regex_fallback"`.

**Path 2 — Legacy Docling (backward-compat):** `runtime.parser_registry` is `None` and `config.enable_docling_parser=True`.
- Calls `parse_with_docling()` directly. Emits a `DeprecationWarning`.
- Sets `docling_document` on state for downstream compatibility.
- Sets `parser_strategy="docling_legacy"`.

**Path 3 — Regex only:** No registry and Docling disabled.
- Applies `_FIGURE_PATTERN` and `_HEADING_PATTERN` regexes to `raw_text`.
- Sets `parser_strategy="regex"`.

`parse_result` and `parser_instance` are only present in state on Path 1.

### `chunking_node`

`src/ingest/embedding/nodes/chunking.py`

**Primary path** (when `parse_result` and `parser_instance` are both in state):
- `config.chunker == "native"` (default): calls `parser_instance.chunk(parse_result)`. On failure, falls back to `chunk_with_markdown(parse_result, config)` and appends `chunking:fallback_to_markdown` to the processing log.
- `config.chunker == "markdown"`: calls `chunk_with_markdown(parse_result, config)` directly, bypassing the parser's native chunker. Appends `chunking:markdown_override` to the processing log.

Maps `list[Chunk]` to `list[ProcessedChunk]`: merges `base_metadata` with `section_path`, `heading`, `heading_level`, `chunk_index`, `total_chunks`, and `extra_metadata` from each `Chunk`.

**Legacy fallback path** (when `parse_result` is absent from state):
- Calls `_chunk_with_markdown_legacy()` which chunks `refactored_text` or `cleaned_text` using the legacy `chunk_markdown()` path. Appends `chunking:legacy_markdown` to the log.

Chunk text normalization via `_normalize_chunk_text()`: applies NFC unicode normalization and strips C0/C1 control characters (preserves `\n`, `\r`, `\t`).

---

## 9. Troubleshooting

### 9.1 File routed to wrong parser

Check `structure["parser_strategy"]` in the pipeline output. Common causes:

- **Uppercase extension.** Extensions are matched case-insensitively (`.PDF` maps to `.pdf`). Filenames in `_FILENAME_MAP` (e.g., `Dockerfile`) are case-sensitive — `dockerfile` (lowercase) will not match.
- **Unrecognised extension.** Falls back to `"text"` with a `logger.warning`. Look for `"Unrecognised extension"` in logs.
- **`parser_strategy` override active.** `parser_strategy="document"` forces all files through `DoclingParser` including `.py` files. Check `config.parser_strategy`.
- **Missing dependency.** If tree-sitter is absent, `.py` files fall back to `"text"`. Check startup logs for `"tree-sitter not available"`.

### 9.2 Chunking quality issues

| Parser | Expected behaviour | Common issue |
|--------|--------------------|-------------|
| `DoclingParser` | HybridChunker respects heading hierarchy and `max_tokens` | `hybrid_chunker_max_tokens` too high or low |
| `CodeParser` | One chunk per function/class; module-level chunk for imports | Large classes produce a single chunk; method-level splitting is not implemented |
| `PlainTextParser` | Heading-boundary splits with `chunk_size`/`chunk_overlap` | Tables may split mid-row |

Check `processing_log` for: `chunking:native_ok`, `chunking:markdown_override`, or `chunking:fallback_to_markdown`. If `chunking:fallback_to_markdown` appears, native chunking failed — check the error log for cause.

Test chunking in isolation:

```python
from pathlib import Path
from src.ingest.support.parser_text import PlainTextParser
from src.ingest.common.types import IngestionConfig

parser = PlainTextParser()
config = IngestionConfig(enable_docling_parser=False)
result = parser.parse(Path("problem_file.md"), config)
chunks = parser.chunk(result)
for c in chunks:
    print(f"[{c.chunk_index}] heading={c.heading!r} len={len(c.text)}")
```

### 9.3 `chunk()` called before `parse()`

All three parsers raise `RuntimeError` with a message containing `"called before parse()"`. This happens when a parser instance is reused across documents or when `parse()` was never called. `ParserRegistry.get_parser()` creates a new instance per call, so the usual cause is code that reuses an instance manually.

### 9.4 `extra_metadata` is not JSON-serialisable

Symptom: `TypeError` during chunk serialisation. Fix: ensure all values stored in `extra_metadata` are Python primitives (`str`, `int`, `float`, `bool`, `list`, `dict`, or `None`). Use `validate_extra_metadata(chunk.extra_metadata)` in tests to catch this early.

### 9.5 tree-sitter build issues

```bash
# Install core package and Python grammar (minimum required):
uv add tree-sitter tree-sitter-python

# Verify grammar loads:
python -c "
import tree_sitter, tree_sitter_python
lang = tree_sitter.Language(tree_sitter_python.language())
p = tree_sitter.Parser(lang)
tree = p.parse(b'def foo(): pass')
print(tree.root_node.sexp())
"
# Expected: (module (function_definition ...))
```

If the S-expression is unexpected, the grammar version may be incompatible. Pin:

```bash
uv add "tree-sitter>=0.21,<0.23" "tree-sitter-python>=0.21"
```

`ModuleNotFoundError` from `_load_grammar()` means the grammar package is not installed or uses a non-standard module name. Check the `tree_sitter_{language}` naming pattern against the installed package.

### 9.6 VLM mode conflict at startup

The pipeline raises an `IngestionDesignCheck` error if `vlm_mode="builtin"` and `enable_multimodal_processing=True` are both set. Fix:

```bash
# Use Docling's built-in SmolVLM (parse-time figure description):
RAG_VLM_MODE=builtin
RAG_ENABLE_MULTIMODAL_PROCESSING=false

# Or use external VLM enrichment (post-chunking):
RAG_VLM_MODE=external
RAG_ENABLE_MULTIMODAL_PROCESSING=false
```

### 9.7 Legacy deprecation warning

If logs show `DeprecationWarning: structure_detection_node: parser_registry is not set on Runtime`, the registry has not been initialized on the `Runtime` object. Ensure `ParserRegistry(config)` is created in `impl.py` and assigned to `runtime.parser_registry` before the pipeline graph runs.
