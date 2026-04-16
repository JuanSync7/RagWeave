> **⚠ DRAFT — PRE-IMPLEMENTATION DESIGN RATIONALE**
>
> This document was authored **before** source code existed and has not been validated against a running implementation. File paths, CLI syntax, error messages, and troubleshooting sections are **speculative**. Sections that claim post-implementation knowledge (Operations, Troubleshooting, exact module paths, performance numbers) are provisional until the code lands.
>
> To be **fully rewritten post-implementation** using `/write-engineering-guide` (which now enforces a non-skippable existence check). For authoritative content prior to rewrite, consult the companion `DOCUMENT_PARSING_SPEC.md`, `DOCUMENT_PARSING_DESIGN.md`, and `DOCUMENT_PARSING_IMPLEMENTATION.md`.
>
> **Salvage audit:** Architecture Overview (§1), Data Flow (§2), Extension Guide (§4), and Test Fixtures (§6.2) survive rewrite. Troubleshooting (§3/§5) will be regenerated from real code.

---

> **Document type:** Engineering guide (Layer 5)
> **Upstream:** DOCUMENT_PARSING_IMPLEMENTATION.md
> **Last updated:** 2026-04-15
> **Status:** DRAFT (pre-implementation)

# Document Parsing Abstraction — Engineering Guide (v1.0.0-draft)

## 1. Architecture Overview

The Document Parsing Abstraction replaces the former Docling-coupled parsing path with a pluggable strategy system. Instead of every pipeline node importing `parse_with_docling()` directly and passing `DoclingDocument` through LangGraph state, all parsing now flows through a single `DocumentParser` protocol. The pipeline never sees parser-internal types.

Three problems drove this design:

1. **Docling lock-in.** `DoclingDocument` had leaked into `IngestState`, `EmbeddingPipelineState`, and two pipeline nodes. Swapping parsers required modifying every consumer.
2. **No code or plain text support.** Source code and markdown files were forced through Docling's OCR/layout path, wasting compute and losing AST structure.
3. **Silent double VLM processing.** `vlm_mode="builtin"` and `enable_multimodal_processing=true` could both be active with no warning.

### 1.1 Parser Strategy Families

| Strategy | Parser Class | Input Formats | Chunking Approach | External Deps |
|----------|-------------|---------------|-------------------|---------------|
| **Document** | `DoclingParser` | `.pdf`, `.docx`, `.pptx`, `.png`, `.jpg`, `.jpeg`, `.tiff`, `.bmp` | `HybridChunker` (Docling native) | `docling`, `docling-core` |
| **Code** | `CodeParser` | `.py`, `.rs`, `.go`, `.ts`, `.tsx`, `.js`, `.jsx`, `.java`, `.c`, `.h`, `.cpp`, `.hpp`, `.cc`, `.cxx`, `.cs`, `.rb`, `.kt`, `.swift`, `.scala`, `.sh`, `.bash`, `.zsh`, `.yaml`, `.yml`, `.toml`, `.json`, `Dockerfile`, `Makefile` | One chunk per top-level function/class (AST-guided) | `tree-sitter`, language grammar packages |
| **Plain Text** | `PlainTextParser` | `.md`, `.txt`, `.rst`, `.html`, `.htm` | Heading-aware markdown splitter | None (optional: `markdownify`, `pypandoc`) |

### 1.2 Key Architecture Decisions

| Decision | Rationale |
|----------|-----------|
| **`Protocol` over ABC** | Structural subtyping avoids forced inheritance. Parsers need only satisfy the method signatures. No base class import required. |
| **Per-document parser instances** | Eliminates state-leakage bugs between documents. `parse()` populates internal state, `chunk()` consumes it. A new parser instance is created per document. |
| **`parser_instance` in LangGraph state** | Transient, never serialised. Carries opaque internal state between `structure_detection_node` and `chunking_node` within a single document's processing. |
| **Chunker override is external to parsers** | Parsers always implement native chunking. The `chunker="markdown"` override is applied by the calling node (`chunking_node`), not inside each parser. Parsers do not need to know about the override. |
| **Backward-compatible aliases** | Existing callers of `parse_with_docling()`, `ensure_docling_ready()`, and `DoclingParseResult` continue to work. The new class is purely additive. |

### 1.3 Component Map

```
src/ingest/
├── support/
│   ├── parser_base.py          # Protocol, ParseResult, Chunk, chunk_with_markdown()
│   ├── parser_registry.py      # ParserRegistry (extension routing)
│   ├── parser_text.py          # PlainTextParser
│   ├── parser_code.py          # CodeParser (tree-sitter)
│   ├── docling.py              # DoclingParser + legacy standalone functions
│   └── markdown.py             # Shared markdown chunking (used by chunk_with_markdown)
├── common/
│   └── types.py                # IngestionConfig (parser_strategy, chunker fields), Runtime
├── doc_processing/
│   └── nodes/
│       └── structure_detection.py  # Calls registry.get_parser() + parser.parse()
├── embedding/
│   ├── state.py                # EmbeddingPipelineState (parse_result, parser_instance)
│   └── nodes/
│       └── chunking.py         # Calls parser.chunk() or chunk_with_markdown()
└── impl.py                     # Pipeline init, VLM guard, config validation
```

---

## 2. Data Flow

### 2.1 Document Parser Flow (PDF -> ParseResult -> Chunks)

```
report.pdf
    │
    ▼
ParserRegistry.get_parser("report.pdf")
    │  extension ".pdf" -> strategy "document" -> DoclingParser()
    ▼
DoclingParser.parse(file_path, config)
    │  Internally calls parse_with_docling()
    │  Stores DoclingDocument in self._docling_document (encapsulated)
    │  Returns ParseResult(markdown, headings, has_figures, page_count)
    ▼
structure_detection_node stores parse_result + parser_instance in state
    │
    ▼
chunking_node retrieves parse_result + parser_instance from state
    │
    ├── config.chunker == "native"?
    │       │
    │       ▼  YES
    │   DoclingParser.chunk(parse_result)
    │       │  Uses self._docling_document with HybridChunker
    │       │  Maps HybridChunker output to list[Chunk]
    │       │  section_path from meta.headings join
    │       ▼
    │   list[Chunk] -> map to ProcessedChunk -> downstream nodes
    │
    └── config.chunker == "markdown"?
            │
            ▼  YES
        chunk_with_markdown(parse_result, config)
            │  Heading-aware split on ParseResult.markdown
            ▼
        list[Chunk] -> map to ProcessedChunk -> downstream nodes
```

### 2.2 Code Parser Flow (source -> AST -> Chunks + KG triples)

```
utils.py
    │
    ▼
ParserRegistry.get_parser("utils.py")
    │  extension ".py" -> strategy "code" -> CodeParser()
    ▼
CodeParser.parse(file_path, config)
    │  Reads file bytes
    │  Loads tree-sitter Python grammar
    │  Parses into AST, stores self._tree (encapsulated)
    │  markdown = "```python\n<source>\n```"
    │  headings = [module docstring or filename]
    │  Returns ParseResult(markdown, headings, has_figures=False, page_count=0)
    ▼
CodeParser.chunk(parse_result)
    │  Walks self._tree root children
    │  One chunk per top-level function/class
    │  Module-level chunk for imports/constants
    │  extra_metadata: language, function_name, class_name, docstring,
    │                  imports, decorators, kg_relationships
    │
    │  KG relationships (deterministic, no LLM):
    │    - "import os"          -> {type: "imports", source: "module", target: "os"}
    │    - "class Dog(Animal)"  -> {type: "inherits", source: "Dog", target: "Animal"}
    │    - "process_data()"     -> {type: "calls", source: "run", target: "process_data"}
    ▼
list[Chunk] -> map to ProcessedChunk -> downstream nodes
```

### 2.3 Plain Text Parser Flow

```
README.md
    │
    ▼
ParserRegistry.get_parser("README.md")
    │  extension ".md" -> strategy "text" -> PlainTextParser()
    ▼
PlainTextParser.parse(file_path, config)
    │  Reads file as UTF-8
    │  .html -> convert with markdownify (or fallback tag stripper)
    │  .rst -> convert with pypandoc (or fallback heading heuristic)
    │  .md/.txt -> content as-is
    │  Extracts headings from markdown # patterns
    │  has_figures = scan for ![...](...)
    │  page_count = 0
    ▼
PlainTextParser.chunk(parse_result)
    │  Delegates to chunk_with_markdown(parse_result, config)
    │  Heading-aware split with section_path from heading hierarchy
    ▼
list[Chunk] -> map to ProcessedChunk -> downstream nodes
```

### 2.4 Chunker Override Flow

When `chunker="markdown"` is set in config, the override is applied in `chunking_node`, not inside parsers:

```
chunking_node receives parse_result + parser_instance from state
    │
    ├── config.chunker == "native"
    │       ▼
    │   parser_instance.chunk(parse_result)   # Each parser's native chunking
    │       │
    │       └── On failure: fall back to chunk_with_markdown()
    │
    └── config.chunker == "markdown"
            ▼
        chunk_with_markdown(parse_result, config)   # Uniform markdown splitting
        (Parser's native chunk() is never called)
```

The override trades structural richness for uniformity. Document chunks lose HybridChunker heading metadata. Code chunks lose AST-guided function boundaries.

---

## 3. How to Add a New Parser

### 3.1 Step-by-Step Guide (with code template)

**Example:** Adding a `DeepDocParser` for RAGFlow's DeepDoc backend.

**Step 1.** Create `src/ingest/support/parser_deepdoc.py`:

```python
# src/ingest/support/parser_deepdoc.py

# @summary
# DeepDoc parser for document formats using RAGFlow's DeepDoc backend.
# Exports: DeepDocParser
# Deps: pathlib, src.ingest.support.parser_base
# @end-summary

"""DeepDoc parser implementation."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from src.ingest.support.parser_base import Chunk, ParseResult

logger = logging.getLogger(__name__)


class DeepDocParser:
    """RAGFlow DeepDoc parser implementing DocumentParser protocol."""

    def __init__(self) -> None:
        self._internal_doc: Any = None   # DeepDoc internal state (never exposed)
        self._config: Any = None

    def parse(self, file_path: Path, config: Any) -> ParseResult:
        """Parse using DeepDoc. Returns ParseResult with no internal types."""
        self._config = config

        # --- Your parsing logic here ---
        # result = deepdoc_convert(file_path)
        # self._internal_doc = result.internal_document  # encapsulated

        return ParseResult(
            markdown="...",          # Document as markdown
            headings=["..."],        # Extracted headings
            has_figures=False,       # Whether figures were detected
            page_count=0,           # Page count (0 if not applicable)
        )

    def chunk(self, parse_result: ParseResult) -> list[Chunk]:
        """Chunk using DeepDoc's native chunking."""
        if self._internal_doc is None:
            raise RuntimeError(
                "DeepDocParser.chunk() called before parse()."
            )

        # --- Your chunking logic here ---
        # raw_chunks = deepdoc_chunk(self._internal_doc)

        chunks: list[Chunk] = []
        # for idx, raw in enumerate(raw_chunks):
        #     chunks.append(Chunk(
        #         text=raw.text,
        #         section_path="Chapter > Section",
        #         heading="Section Title",
        #         heading_level=2,
        #         chunk_index=idx,
        #         extra_metadata={},
        #     ))
        return chunks

    @classmethod
    def ensure_ready(cls, config: Any) -> None:
        """Verify DeepDoc is installed and functional."""
        try:
            import deepdoc  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "DeepDoc is required but not installed. "
                "Install with: uv add ragflow-deepdoc"
            ) from exc

    @classmethod
    def warmup(cls, config: Any) -> None:
        """Pre-download DeepDoc models if needed."""
        cls.ensure_ready(config)
```

**Key rules for the implementation:**

- `parse()` returns `ParseResult` with exactly four fields. No internal types.
- `chunk()` returns `list[Chunk]` with exactly six fields per chunk. `extra_metadata` values must be JSON-serialisable.
- Internal state (`self._internal_doc`) stays on the instance. It never appears in `ParseResult`, `Chunk`, or LangGraph state.
- `chunk()` before `parse()` must raise `RuntimeError`.

### 3.2 Registration

**Step 2.** Register the parser in `ParserRegistry.__init__()` in `src/ingest/support/parser_registry.py`:

```python
# In ParserRegistry.__init__():

# Attempt to register DeepDoc parser
if getattr(config, "enable_deepdoc_parser", False):
    try:
        from src.ingest.support.parser_deepdoc import DeepDocParser
        self._strategy_map["document"] = DeepDocParser  # Replaces DoclingParser
    except ImportError:
        logger.info("DeepDoc not available; skipping.")
```

If DeepDoc should coexist with Docling as a separate strategy (rather than replacing it), use a distinct strategy name:

```python
self._strategy_map["deepdoc"] = DeepDocParser
```

And add extension mappings if needed, or use `parser_strategy="deepdoc"` as a config override.

**Step 3.** Add a config field if the parser needs a toggle:

```python
# config/settings.py
RAG_INGESTION_ENABLE_DEEPDOC_PARSER: bool = os.getenv(
    "RAG_INGESTION_ENABLE_DEEPDOC_PARSER", "false"
).lower() == "true"

# src/ingest/common/types.py, in IngestionConfig
enable_deepdoc_parser: bool = RAG_INGESTION_ENABLE_DEEPDOC_PARSER
```

### 3.3 Testing Your Parser

Write tests in `tests/ingest/test_parser_deepdoc.py`:

```python
import json
from dataclasses import asdict
from pathlib import Path

from src.ingest.support.parser_base import DocumentParser, ParseResult, Chunk


class TestDeepDocParserContract:
    """Verify DeepDocParser satisfies the DocumentParser protocol."""

    def test_satisfies_protocol(self):
        from src.ingest.support.parser_deepdoc import DeepDocParser
        parser = DeepDocParser()
        assert isinstance(parser, DocumentParser)

    def test_parse_result_has_no_internal_types(self, sample_pdf, mock_config):
        from src.ingest.support.parser_deepdoc import DeepDocParser
        parser = DeepDocParser()
        result = parser.parse(sample_pdf, mock_config)

        assert isinstance(result, ParseResult)
        assert not hasattr(result, "internal_doc")
        assert not hasattr(result, "deepdoc_document")
        # Must be JSON-serialisable
        json.dumps(asdict(result))

    def test_chunk_produces_valid_chunks(self, sample_pdf, mock_config):
        from src.ingest.support.parser_deepdoc import DeepDocParser
        parser = DeepDocParser()
        result = parser.parse(sample_pdf, mock_config)
        chunks = parser.chunk(result)

        assert all(isinstance(c, Chunk) for c in chunks)
        for c in chunks:
            json.dumps(asdict(c))  # All fields serialisable

    def test_chunk_before_parse_raises(self, mock_config):
        from src.ingest.support.parser_deepdoc import DeepDocParser
        parser = DeepDocParser()
        dummy = ParseResult(markdown="x", headings=[], has_figures=False, page_count=0)
        with pytest.raises(RuntimeError, match="before parse"):
            parser.chunk(dummy)
```

### 3.4 Common Pitfalls

| Pitfall | Symptom | Fix |
|---------|---------|-----|
| Leaking internal types into `ParseResult` | Downstream nodes crash with `AttributeError` when a different parser is swapped in | Return only the four `ParseResult` fields. Store internals on `self`. |
| Forgetting `extra_metadata` serialisability | `json.dumps()` fails on `Chunk` | Run `validate_extra_metadata()` in tests. No callables, no opaque objects. |
| Not raising on `chunk()` before `parse()` | Silent None dereference or stale state from a previous document | Check `self._internal_state is None` at the top of `chunk()`. |
| Importing concrete parser in pipeline nodes | Defeats the strategy pattern; breaks when parser is swapped | Pipeline nodes must use `registry.get_parser()` only. Never `from ... import DoclingParser`. |
| Singleton parser instance across documents | Headings from document A leak into document B's chunks | Always create a new parser instance per document (the registry does this automatically). |

---

## 4. How to Add a New Language to Code Parser

### 4.1 tree-sitter Grammar Installation

1. Install the grammar package:

```bash
uv add tree-sitter-haskell
```

2. Add the package to `pyproject.toml` optional dependencies:

```toml
[project.optional-dependencies]
parsers = [
    # ... existing grammars ...
    "tree-sitter-haskell",
]
```

3. Verify the grammar loads:

```python
import tree_sitter_haskell
import tree_sitter

lang = tree_sitter.Language(tree_sitter_haskell.language())
parser = tree_sitter.Parser(lang)
tree = parser.parse(b"main = putStrLn \"Hello\"")
print(tree.root_node.sexp())
```

### 4.2 AST Node Mapping

Add the extension mapping in `parser_code.py`:

```python
# In _EXTENSION_TO_LANGUAGE:
_EXTENSION_TO_LANGUAGE[".hs"] = "haskell"
```

Then check what node types tree-sitter uses for function and class/type definitions in that language. Use the tree-sitter playground or print the S-expression:

```python
tree = parser.parse(open("example.hs", "rb").read())
print(tree.root_node.sexp())
# Look for node types like "function", "function_declaration", "type_alias", etc.
```

Add the relevant node types to the internal helpers:

```python
# In CodeParser._is_function_def():
def _is_function_def(self, node_type: str) -> bool:
    return node_type in {
        # ... existing types ...
        "function",              # Haskell
    }

# In CodeParser._is_class_def():
def _is_class_def(self, node_type: str) -> bool:
    return node_type in {
        # ... existing types ...
        "type_alias_declaration",  # Haskell
        "data_declaration",        # Haskell
    }
```

### 4.3 KG Relationship Extraction

The `_extract_imports()` helper needs to recognise the language's import syntax. Add the relevant node type:

```python
# In CodeParser._extract_imports():
if child.type in (
    "import_statement",        # Python
    "import_from_statement",   # Python
    "use_declaration",         # Rust
    "import_declaration",      # Go, Java, Kotlin
    "import",                  # Haskell
):
    imports.append(self._node_text(child))
```

For inheritance, Haskell uses typeclasses, so you would also check for `class_declaration` or `instance_declaration` nodes and extract the typeclass relationship.

Write a test for the new language:

```python
def test_haskell_parse(tmp_path):
    hs_file = tmp_path / "Main.hs"
    hs_file.write_text('module Main where\n\nmain :: IO ()\nmain = putStrLn "Hello"\n')

    parser = CodeParser()
    result = parser.parse(hs_file, mock_config)

    assert result.has_figures is False
    assert result.page_count == 0
    assert "```haskell" in result.markdown

    chunks = parser.chunk(result)
    assert len(chunks) >= 1
    assert chunks[0].extra_metadata["language"] == "haskell"
```

---

## 5. Troubleshooting

### 5.1 Parser Selection Issues

**Problem:** A file is routed to the wrong parser.

**Diagnosis:** Check which strategy the registry selected:

```python
# In structure_detection_node, the strategy is logged in structure["parser_strategy"]
# Check the processing_log in pipeline output for "structure_detection:ok"
```

**Common causes:**

- **Case sensitivity.** Extensions are matched case-insensitively, but filenames in `_FILENAME_MAP` (e.g., `Dockerfile`) are case-sensitive. `dockerfile` (lowercase) will not match.
- **Unrecognised extension.** Falls back to `"text"` with a warning. Check logs for `"Unrecognised extension"`.
- **Config override active.** `parser_strategy="document"` forces all files through Docling, including `.py` files. Check `config.parser_strategy`.
- **Missing dependency.** If tree-sitter is not installed, `.py` files fall back to `"text"`. Check startup logs for `"tree-sitter not available"`.

**Fix:** Verify the extension mapping in `_EXTENSION_MAP` in `parser_registry.py`. Add missing extensions or adjust `_FILENAME_MAP`.

### 5.2 Chunking Quality Issues

**Problem:** Chunks are too large, too small, or split at bad boundaries.

| Parser | Expected Behaviour | Common Issue |
|--------|--------------------|-------------|
| **DoclingParser** | HybridChunker respects heading hierarchy and `max_tokens` | `hybrid_chunker_max_tokens` too high or too low. Check `config.hybrid_chunker_max_tokens`. |
| **CodeParser** | One chunk per function/class. Module-level chunk for imports. | Large classes produce a single chunk. Size-based method splitting is not yet implemented (see Implementation Notes). |
| **PlainTextParser** | Heading-boundary splits with `chunk_size`/`chunk_overlap` | Tables split mid-row. Check if `RecursiveCharacterTextSplitter` separator config handles `|` rows. |

**Debug approach:**

1. Check `processing_log` for the chunking path used: `chunking:native_ok`, `chunking:markdown_override`, or `chunking:fallback_to_markdown`.
2. If `chunking:fallback_to_markdown` appears, native chunking failed. Check the error log for the cause.
3. Test chunking in isolation:

```python
from src.ingest.support.parser_text import PlainTextParser
from src.ingest.support.parser_base import ParseResult

parser = PlainTextParser()
result = parser.parse(Path("problem_file.md"), config)
chunks = parser.chunk(result)
for c in chunks:
    print(f"[{c.chunk_index}] heading={c.heading} len={len(c.text)}")
    print(c.text[:200])
    print("---")
```

### 5.3 VLM Mode Conflicts

**Problem:** Pipeline fails at startup with a VLM mutual exclusion error.

**Cause:** `vlm_mode="builtin"` and `enable_multimodal_processing=true` are both set. This is always a configuration error because it causes figures to be described by two independent VLM pipelines.

**Fix:** Disable one:

```bash
# Option A: Use Docling's built-in SmolVLM (parse-time figure description)
RAG_VLM_MODE=builtin
RAG_ENABLE_MULTIMODAL_PROCESSING=false

# Option B: Use external VLM enrichment (post-chunking via LiteLLM)
RAG_VLM_MODE=external
RAG_ENABLE_MULTIMODAL_PROCESSING=false

# Option C: Use Phase 1 multimodal node (pre-chunking via vision.py)
RAG_VLM_MODE=disabled
RAG_ENABLE_MULTIMODAL_PROCESSING=true
```

**Valid combinations reference:**

| `vlm_mode` | `enable_multimodal_processing` | Result |
|------------|-------------------------------|--------|
| `disabled` | `false` | No VLM processing. |
| `disabled` | `true` | Phase 1 multimodal node only. |
| `builtin` | `false` | Docling SmolVLM at parse time. |
| `builtin` | `true` | **ERROR.** Mutual exclusion. |
| `external` | `false` | Post-chunking VLM enrichment only. |
| `external` | `true` | Both stages active (valid, with startup warning). |

### 5.4 tree-sitter Build Issues

**Problem:** `CodeParser.ensure_ready()` raises `RuntimeError: tree-sitter is required for code parsing but not installed`.

**Fix:**

```bash
uv add tree-sitter
uv add tree-sitter-python   # Minimum required grammar
```

**Problem:** Grammar loads but parsing produces an empty tree or unexpected node types.

**Diagnosis:**

```python
import tree_sitter
import tree_sitter_python

lang = tree_sitter.Language(tree_sitter_python.language())
parser = tree_sitter.Parser(lang)
tree = parser.parse(b"def foo(): pass")
print(tree.root_node.sexp())
# Expected: (module (function_definition ...))
```

If the S-expression looks wrong, the grammar version may be incompatible with the installed `tree-sitter` version. Pin compatible versions:

```bash
uv add "tree-sitter>=0.21,<0.23" "tree-sitter-python>=0.21"
```

**Problem:** `_load_grammar()` raises `ModuleNotFoundError` for a specific language.

**Cause:** The grammar package name does not match the expected `tree_sitter_{language}` pattern. Some languages use different naming:

- C# grammar: package is `tree-sitter-c-sharp`, module is `tree_sitter_c_sharp`
- C++ grammar: package is `tree-sitter-cpp`, module is `tree_sitter_cpp`

Check the `_load_grammar()` method's special-case handling and add new cases if needed.

---

## 6. Testing Guide

### 6.1 Critical Test Scenarios

These are the scenarios that must pass before any parser change is merged.

| # | Test | What It Validates | File |
|---|------|-------------------|------|
| 1 | `ParseResult` round-trips through `json.dumps(asdict(...))` | No opaque types in the boundary contract (FR-3201) | `test_parser_base.py` |
| 2 | `Chunk` round-trips through `json.dumps(asdict(...))` | `extra_metadata` is serialisable (FR-3202) | `test_parser_base.py` |
| 3 | Stub class satisfies `isinstance(stub, DocumentParser)` | Protocol is `runtime_checkable` and correctly defined (FR-3200) | `test_parser_base.py` |
| 4 | `DoclingParser.parse()` returns `ParseResult` with no `docling_document` attribute | Encapsulation rule enforced (FR-3205) | `test_parser_docling.py` |
| 5 | `DoclingParser.chunk()` before `parse()` raises `RuntimeError` | Lifecycle guard (FR-3206) | `test_parser_docling.py` |
| 6 | `CodeParser.chunk()` produces one chunk per function in a 3-function file | AST-guided chunking works (FR-3252) | `test_parser_code.py` |
| 7 | `CodeParser` chunk `extra_metadata` contains `language`, `function_name`, `kg_relationships` | Code metadata contract (FR-3253, FR-3254) | `test_parser_code.py` |
| 8 | `ParserRegistry` routes `.pdf` to `DoclingParser`, `.py` to `CodeParser`, `.md` to `PlainTextParser` | Extension routing (FR-3300) | `test_parser_registry.py` |
| 9 | `ParserRegistry` routes `.PDF` (uppercase) to `DoclingParser` | Case-insensitive matching (FR-3300 AC 4) | `test_parser_registry.py` |
| 10 | Unknown extension `.ini` routes to `PlainTextParser` with warning | Fallback behaviour (FR-3302) | `test_parser_registry.py` |
| 11 | `vlm_mode="builtin"` + `enable_multimodal_processing=true` produces design check error | VLM mutual exclusion (FR-3340) | `test_vlm_guard.py` |
| 12 | `chunker="markdown"` overrides native chunking for all parser types | Chunker override (FR-3320) | `test_chunker_override.py` |

### 6.2 Test Fixtures

**Reusable config fixture:**

```python
@pytest.fixture
def mock_config():
    """Minimal IngestionConfig for parser tests."""
    from src.ingest.common.types import IngestionConfig
    return IngestionConfig(
        parser_strategy="auto",
        chunker="native",
        vlm_mode="disabled",
        enable_multimodal_processing=False,
        chunk_size=1000,
        chunk_overlap=200,
        hybrid_chunker_max_tokens=512,
        docling_model="default",
        docling_artifacts_path="",
        docling_auto_download=False,
        enable_docling_parser=True,
        generate_page_images=False,
    )
```

**Sample Python file fixture for CodeParser tests:**

```python
@pytest.fixture
def sample_python_file(tmp_path):
    """Python file with functions, a class, imports, and decorators."""
    content = '''"""Utility helpers."""

import os
from pathlib import Path


def read_file(path: str) -> str:
    """Read a file and return its contents."""
    return Path(path).read_text()


def write_file(path: str, content: str) -> None:
    """Write content to a file."""
    Path(path).write_text(content)


class FileProcessor:
    """Processes files in a directory."""

    def __init__(self, root: str):
        self.root = root

    @staticmethod
    def list_files(directory: str) -> list[str]:
        """List all files in directory."""
        return os.listdir(directory)
'''
    f = tmp_path / "utils.py"
    f.write_text(content)
    return f
```

**Sample markdown file fixture:**

```python
@pytest.fixture
def sample_markdown_file(tmp_path):
    """Markdown file with headings, a table, and an image."""
    content = """# Project Overview

Some introductory text.

## Architecture

The system uses a layered design.

| Layer | Component |
|-------|-----------|
| API   | FastAPI   |
| Data  | Weaviate  |

## Screenshots

![Dashboard](./dashboard.png)

### Details

More detailed information here.
"""
    f = tmp_path / "README.md"
    f.write_text(content)
    return f
```

### 6.3 Parser Contract Tests

Every parser implementation must pass the same contract test suite. This pattern ensures swappability:

```python
import json
from dataclasses import asdict

import pytest

from src.ingest.support.parser_base import Chunk, DocumentParser, ParseResult


class ParserContractTests:
    """Mixin for testing any DocumentParser implementation.

    Subclass this and implement the parser_instance and sample_file fixtures.
    """

    @pytest.fixture
    def parser_instance(self):
        """Override: return a fresh parser instance."""
        raise NotImplementedError

    @pytest.fixture
    def sample_file(self, tmp_path):
        """Override: return a Path to a sample file for this parser."""
        raise NotImplementedError

    def test_satisfies_protocol(self, parser_instance):
        assert isinstance(parser_instance, DocumentParser)

    def test_parse_returns_parse_result(self, parser_instance, sample_file, mock_config):
        result = parser_instance.parse(sample_file, mock_config)
        assert isinstance(result, ParseResult)
        assert isinstance(result.markdown, str)
        assert isinstance(result.headings, list)
        assert isinstance(result.has_figures, bool)
        assert isinstance(result.page_count, int)

    def test_parse_result_is_serialisable(self, parser_instance, sample_file, mock_config):
        result = parser_instance.parse(sample_file, mock_config)
        serialised = json.dumps(asdict(result))
        assert serialised  # Non-empty JSON string

    def test_parse_result_has_no_internal_types(self, parser_instance, sample_file, mock_config):
        result = parser_instance.parse(sample_file, mock_config)
        assert not hasattr(result, "docling_document")
        assert not hasattr(result, "tree")
        assert not hasattr(result, "internal_doc")

    def test_chunk_returns_chunk_list(self, parser_instance, sample_file, mock_config):
        result = parser_instance.parse(sample_file, mock_config)
        chunks = parser_instance.chunk(result)
        assert isinstance(chunks, list)
        assert all(isinstance(c, Chunk) for c in chunks)

    def test_chunks_are_serialisable(self, parser_instance, sample_file, mock_config):
        result = parser_instance.parse(sample_file, mock_config)
        chunks = parser_instance.chunk(result)
        for c in chunks:
            json.dumps(asdict(c))

    def test_chunk_before_parse_raises(self, parser_instance):
        dummy = ParseResult(markdown="x", headings=[], has_figures=False, page_count=0)
        with pytest.raises(RuntimeError):
            parser_instance.chunk(dummy)

    def test_chunk_indices_are_sequential(self, parser_instance, sample_file, mock_config):
        result = parser_instance.parse(sample_file, mock_config)
        chunks = parser_instance.chunk(result)
        indices = [c.chunk_index for c in chunks]
        assert indices == list(range(len(chunks)))
```

Use it for each parser:

```python
class TestDoclingParserContract(ParserContractTests):
    @pytest.fixture
    def parser_instance(self):
        from src.ingest.support.docling import DoclingParser
        return DoclingParser()

    @pytest.fixture
    def sample_file(self, tmp_path):
        # Provide a small PDF fixture
        ...


class TestPlainTextParserContract(ParserContractTests):
    @pytest.fixture
    def parser_instance(self):
        from src.ingest.support.parser_text import PlainTextParser
        return PlainTextParser()

    @pytest.fixture
    def sample_file(self, sample_markdown_file):
        return sample_markdown_file


class TestCodeParserContract(ParserContractTests):
    @pytest.fixture
    def parser_instance(self):
        from src.ingest.support.parser_code import CodeParser
        return CodeParser()

    @pytest.fixture
    def sample_file(self, sample_python_file):
        return sample_python_file
```

This contract test pattern means adding a new parser automatically gets validated against the full protocol contract by subclassing `ParserContractTests` and providing two fixtures.
