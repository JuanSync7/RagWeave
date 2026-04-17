> **Document type:** Implementation document (Layer 5)
> **Upstream:** DOCUMENT_PARSING_DESIGN.md
> **Last updated:** 2026-04-15

# Document Parsing Abstraction — Implementation Guide (v1.0.0)

| Field | Value |
|-------|-------|
| **Document** | Document Parsing Abstraction Implementation Guide |
| **Version** | 1.0.0 |
| **Status** | Draft |
| **Spec Reference** | `DOCUMENT_PARSING_SPEC.md` v1.0.0 (FR-3200–FR-3342) |
| **Design Reference** | `DOCUMENT_PARSING_DESIGN.md` v1.0.0 (Tasks 1–9) |
| **Companion Documents** | `DOCUMENT_PARSING_SPEC.md`, `DOCUMENT_PARSING_DESIGN.md`, `DOCUMENT_PROCESSING_IMPLEMENTATION.md`, `DOCLING_CHUNKING_DESIGN.md` |
| **Created** | 2026-04-15 |
| **Last Updated** | 2026-04-15 |

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2026-04-15 | Initial implementation guide covering parser protocol, three parser implementations, registry, chunker override, VLM guard, and pipeline node migration. |

> **Document Intent.** This is the implementation source-of-truth for the Document Parsing Abstraction
> subsystem defined in `DOCUMENT_PARSING_SPEC.md` (FR-3200–FR-3342) and decomposed in
> `DOCUMENT_PARSING_DESIGN.md` (Tasks 1–9). It provides module layouts, interface code,
> dataclass definitions, adapter patterns, registry wiring, and pipeline node update procedures
> at the level of detail required to implement without further design decisions.

---

## 1. Implementation Overview

The Document Parsing Abstraction replaces the current Docling-coupled parsing path with a pluggable
strategy system. The implementation introduces seven new files and modifies six existing files,
organised into four phases that can be executed incrementally without breaking the existing pipeline
at any intermediate step.

**Phase A (Foundation):** `parser_base.py` (protocol + dataclasses) and VLM guard in `impl.py`.
New files only, no existing code changes.

**Phase B (Parsers):** `DoclingParser` adapter in `docling.py`, `PlainTextParser` in `parser_text.py`,
`CodeParser` in `parser_code.py`. All three can be implemented in parallel. Existing standalone
functions in `docling.py` are preserved as backward-compatible aliases.

**Phase C (Routing):** `ParserRegistry` in `parser_registry.py`, new config fields (`parser_strategy`,
`chunker`) in `types.py` and `settings.py`. Defaults preserve existing behaviour.

**Phase D (Integration):** Update `structure_detection_node` and `chunking_node` to use the parser
abstraction. Remove `docling_document` from pipeline state. This is the only phase with breaking
changes to existing node behaviour.

### Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| `Protocol` over ABC | Structural subtyping avoids forced inheritance. Parsers need only satisfy the method signatures. |
| Per-document parser instances | Eliminates state-leakage bugs between documents. `parse()` populates internal state, `chunk()` consumes it. |
| `parser_instance` in LangGraph state | Transient, never serialised. Carries opaque internal state between `structure_detection_node` and `chunking_node`. |
| Chunker override is external to parsers | Parsers always implement native chunking. The `chunker="markdown"` override is applied by the calling node, not inside each parser. |
| Backward-compatible aliases | Existing callers of `parse_with_docling()` continue to work throughout Phase B and C. |

---

## 2. Module Layout (new files under src/ingest/support/parsers/)

After implementation, the `src/ingest/support/` directory gains four new files. Existing files
are modified in place (no moves or renames).

```
src/ingest/
├── support/
│   ├── __init__.py                     # Add parser_base re-exports
│   ├── docling.py                      # MODIFIED: add DoclingParser class
│   ├── markdown.py                     # UNCHANGED (shared chunker)
│   ├── parser_base.py                  # NEW: Protocol, ParseResult, Chunk, chunk_with_markdown()
│   ├── parser_registry.py              # NEW: ParserRegistry
│   ├── parser_text.py                  # NEW: PlainTextParser
│   └── parser_code.py                  # NEW: CodeParser (tree-sitter)
├── common/
│   └── types.py                        # MODIFIED: add parser_strategy, chunker fields; add parser_registry to Runtime
├── doc_processing/
│   └── nodes/
│       └── structure_detection.py      # MODIFIED: delegate to parser registry
├── embedding/
│   ├── state.py                        # MODIFIED: replace docling_document with parse_result + parser_instance
│   └── nodes/
│       └── chunking.py                 # MODIFIED: delegate to parser.chunk() or chunk_with_markdown()
└── impl.py                             # MODIFIED: add VLM guard + chunker validation + registry init
```

### New File Responsibilities

| File | FR Coverage | Description |
|------|-------------|-------------|
| `parser_base.py` | FR-3200, FR-3201, FR-3202, FR-3204, FR-3207, FR-3321 | Protocol, dataclasses, shared markdown chunker, `validate_extra_metadata()` |
| `parser_registry.py` | FR-3300, FR-3301, FR-3302, FR-3303 | Extension-to-strategy mapping, parser instantiation, readiness orchestration |
| `parser_text.py` | FR-3280, FR-3281, FR-3282 | Plain text/markdown/HTML/RST parser with heading-aware chunking |
| `parser_code.py` | FR-3250–FR-3256 | tree-sitter AST parser with function-level chunking and deterministic KG extraction |

---

## 3. Abstract Parser Protocol Implementation

**File:** `src/ingest/support/parser_base.py`

**Design Task:** Task 1 + Task 2

This module is the foundation of the subsystem. It defines the three public types that form the
parser boundary contract and the protocol that all parsers implement.

```python
# src/ingest/support/parser_base.py

# @summary
# Abstract parser protocol and unified data contracts for the Document Parsing Abstraction.
# Exports: DocumentParser, ParseResult, Chunk, chunk_with_markdown, validate_extra_metadata
# Deps: dataclasses, pathlib, typing, src.ingest.common.types, src.ingest.support.markdown
# @end-summary

"""Abstract parser protocol and unified data contracts.

Encapsulation rule: parser-internal types (DoclingDocument, tree-sitter Tree,
DeepDoc internal objects) MUST NOT appear in ParseResult or Chunk. Parser
implementations retain internal state on the instance between parse() and
chunk() calls — the pipeline never inspects or serialises this state.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@dataclass
class ParseResult:
    """Unified output of parser.parse(). FR-3201.

    Contains parser-agnostic document metadata. No parser-internal types
    (DoclingDocument, tree-sitter Tree) may appear here. All fields are
    JSON-serialisable by design.

    Attributes:
        markdown: Document content as markdown text.
        headings: Heading text in document order.
        has_figures: Whether the parser detected figures or images.
        page_count: Total pages in source. 0 for code/text files.
    """

    markdown: str
    headings: list[str]
    has_figures: bool
    page_count: int


@dataclass
class Chunk:
    """Unified output element of parser.chunk(). FR-3202.

    extra_metadata values MUST be JSON-serialisable. Code parser chunks
    carry language, function_name, class_name, docstring, imports,
    decorators keys. Document parser chunks typically leave extra_metadata
    empty.

    Attributes:
        text: Chunk content (raw source code for code parsers, markdown
            segments for document/text parsers).
        section_path: Hierarchical breadcrumb (e.g., "Chapter > Section").
        heading: Nearest heading for this chunk. Empty string if none.
        heading_level: Depth of nearest heading (1=top, 0=none).
        chunk_index: Zero-based index within the document.
        extra_metadata: Parser-specific metadata. Must be JSON-serialisable.
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

    Implementations MUST encapsulate parser-internal types. Pipeline nodes
    access parsers ONLY through this protocol. Per-document instance
    lifecycle is RECOMMENDED (FR-3206): create a new parser instance per
    document, call parse() then chunk() sequentially.
    """

    def parse(self, file_path: Path, config: Any) -> ParseResult:
        """Parse a source file into a ParseResult.

        Internal state (e.g., DoclingDocument, AST) MAY be retained for use
        by chunk() but MUST NOT appear in ParseResult.

        Args:
            file_path: Path to the source file.
            config: IngestionConfig instance.

        Returns:
            ParseResult with parser-agnostic metadata.
        """
        ...

    def chunk(self, parse_result: ParseResult) -> list[Chunk]:
        """Produce chunks from a previously parsed document.

        Uses parser-internal state retained from parse(). Calling chunk()
        before parse() MUST raise RuntimeError.

        Args:
            parse_result: The ParseResult from a prior parse() call.

        Returns:
            List of Chunk objects with populated metadata.
        """
        ...

    @classmethod
    def ensure_ready(cls, config: Any) -> None:
        """Validate runtime dependencies. Called at pipeline startup. FR-3204.

        Raises:
            RuntimeError: If parser dependencies are missing.
        """
        ...

    @classmethod
    def warmup(cls, config: Any) -> None:
        """Download/compile expensive assets. FR-3207. Optional.

        Called during deployment or container startup, separate from
        ensure_ready(). Implementations without expensive init should no-op.
        """
        ...


def validate_extra_metadata(meta: dict[str, Any]) -> None:
    """Validate that all extra_metadata values are JSON-serialisable.

    Called by parser implementations in debug/test mode. Raises ValueError
    if any value cannot be serialised.

    Args:
        meta: The extra_metadata dict to validate.

    Raises:
        ValueError: If any value is not JSON-serialisable.
    """
    try:
        json.dumps(meta, default=str)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"extra_metadata contains non-JSON-serialisable value: {exc}"
        ) from exc


def chunk_with_markdown(parse_result: ParseResult, config: Any) -> list[Chunk]:
    """Shared markdown chunker. FR-3321.

    Wraps the existing chunk_markdown() from src.ingest.support.markdown and
    maps output to Chunk dataclass. Used by PlainTextParser.chunk() natively
    and by any parser when chunker="markdown" override is active.

    Args:
        parse_result: ParseResult whose markdown field is chunked.
        config: IngestionConfig with chunk_size, chunk_overlap settings.

    Returns:
        List of Chunk objects with section_path, heading, heading_level
        populated from markdown heading hierarchy.
    """
    from src.ingest.support.markdown import chunk_markdown, _build_section_metadata

    raw_chunks = chunk_markdown(
        parse_result.markdown,
        chunk_size=config.chunk_size,
        chunk_overlap=config.chunk_overlap,
        embedder=None,  # Semantic splitting handled at a higher level if needed
    )

    chunks: list[Chunk] = []
    for idx, raw in enumerate(raw_chunks):
        section_meta = _build_section_metadata(raw.get("header_metadata", {}))
        chunks.append(
            Chunk(
                text=raw["text"],
                section_path=section_meta["section_path"],
                heading=section_meta["heading"],
                heading_level=section_meta["heading_level"],
                chunk_index=idx,
                extra_metadata={},
            )
        )
    return chunks
```

### Implementation Notes

- `config` parameter is typed as `Any` in the protocol to avoid a circular import between
  `parser_base.py` and `src/ingest/common/types.py`. At runtime, callers pass `IngestionConfig`.
  Concrete parser implementations import `IngestionConfig` directly and can type-narrow.
- `ParseResult` and `Chunk` are plain dataclasses. Verify round-trip serialisation with
  `json.dumps(dataclasses.asdict(result))` in contract tests.
- `chunk_with_markdown()` imports `chunk_markdown` and `_build_section_metadata` lazily to avoid
  circular imports. These are existing functions in `src/ingest/support/markdown.py`.
- `validate_extra_metadata()` uses `json.dumps(meta, default=str)` as a lenient check. For strict
  validation (reject `default=str` coercion), use `json.dumps(meta)` without the default parameter.

---

## 4. ParseResult and Chunk Dataclasses

**Design Task:** Task 2 (co-located with Task 1 in `parser_base.py`)

The `ParseResult` and `Chunk` dataclasses are defined in Section 3 above. This section documents
acceptance criteria verification and the relationship to existing types.

### Mapping to Existing Types

| New Type | Replaces | Relationship |
|----------|----------|-------------|
| `ParseResult` | `DoclingParseResult` | `ParseResult` contains a strict subset of `DoclingParseResult` fields. `DoclingParseResult.text_markdown` maps to `ParseResult.markdown`. `DoclingParseResult.docling_document` is encapsulated inside `DoclingParser`, not exposed. |
| `Chunk` | Inline dict from `chunk_markdown()` / `HybridChunker` chunk | `Chunk` unifies the two chunk representations. `section_path`, `heading`, `heading_level` replace the varied `header_metadata` / `meta.headings` patterns. |
| `Chunk` -> `ProcessedChunk` | N/A | `Chunk` is the parser-boundary type. `ProcessedChunk` (`src/ingest/common/schemas.py`) is the pipeline-internal type consumed by embedding/KG nodes. The mapping is performed in `chunking_node`. |

### Chunk-to-ProcessedChunk Mapping

This mapping function lives in `chunking_node` and converts parser `Chunk` objects to the existing
`ProcessedChunk` type that all downstream nodes consume. No downstream node changes are required.

```python
from src.ingest.common import ProcessedChunk
from src.ingest.support.parser_base import Chunk

def chunk_to_processed(
    chunk: Chunk,
    base_metadata: dict[str, Any],
    total_chunks: int,
) -> ProcessedChunk:
    """Map parser Chunk to pipeline ProcessedChunk.

    Args:
        chunk: Parser-produced Chunk.
        base_metadata: Pre-built source metadata (source, source_uri,
            source_key, source_id, connector, source_version).
        total_chunks: Total number of chunks in this document.

    Returns:
        ProcessedChunk ready for embedding and downstream nodes.
    """
    return ProcessedChunk(
        text=_normalize_chunk_text(chunk.text),
        metadata={
            **base_metadata,
            "section_path": chunk.section_path,
            "heading": chunk.heading,
            "heading_level": chunk.heading_level,
            "chunk_index": chunk.chunk_index,
            "total_chunks": total_chunks,
            **chunk.extra_metadata,
        },
    )
```

---

## 5. Docling Parser Adapter

**File:** `src/ingest/support/docling.py` (modify in-place)

**Design Task:** Task 3

**FR Coverage:** FR-3221, FR-3223, FR-3224, FR-3205, FR-3206

The `DoclingParser` class wraps the existing standalone functions into the `DocumentParser` protocol.
The `DoclingDocument` stays encapsulated as `self._docling_document` — it never appears in
`ParseResult` or crosses the parser boundary.

### Class Structure

```python
# Added to src/ingest/support/docling.py, below existing standalone functions.

from src.ingest.support.parser_base import DocumentParser, ParseResult, Chunk


class DoclingParser:
    """Docling-based document parser implementing DocumentParser protocol.

    Wraps existing parse_with_docling(), ensure_docling_ready(), and
    warmup_docling_models() into a class with per-document instance lifecycle.

    Internal state:
        _docling_document: DoclingDocument retained between parse() and chunk().
            Never exposed via ParseResult or any public API. FR-3205.
        _vlm_mode: VLM mode from config, used during parse(). FR-3224.
        _max_tokens: HybridChunker max tokens from config.
    """

    def __init__(self) -> None:
        self._docling_document: Any = None
        self._vlm_mode: str = "disabled"
        self._max_tokens: int = 512

    def parse(self, file_path: Path, config: Any) -> ParseResult:
        """Parse a document using Docling. FR-3221.

        Calls existing parse_with_docling() internally. Stores the
        DoclingDocument in self._docling_document for use by chunk().
        Returns a ParseResult with no DoclingDocument attribute.

        Args:
            file_path: Path to the source document.
            config: IngestionConfig instance.

        Returns:
            ParseResult with markdown, headings, has_figures, page_count.
        """
        self._vlm_mode = getattr(config, "vlm_mode", "disabled")
        self._max_tokens = getattr(config, "hybrid_chunker_max_tokens", 512)

        result = parse_with_docling(
            file_path,
            parser_model=config.docling_model,
            artifacts_path=config.docling_artifacts_path,
            vlm_mode=self._vlm_mode,
            generate_page_images=config.generate_page_images,
        )

        # Encapsulate DoclingDocument — FR-3205
        self._docling_document = result.docling_document

        return ParseResult(
            markdown=result.text_markdown,
            headings=result.headings,
            has_figures=result.has_figures,
            page_count=result.page_count,
        )

    def chunk(self, parse_result: ParseResult) -> list[Chunk]:
        """Chunk using Docling's HybridChunker. FR-3223.

        Operates on self._docling_document (internal state from parse()).
        Maps HybridChunker output to Chunk dataclass with section_path
        derived from meta.headings.

        Args:
            parse_result: ParseResult from a prior parse() call.

        Returns:
            List of Chunk objects with heading hierarchy metadata.

        Raises:
            RuntimeError: If called before parse() (no DoclingDocument).
        """
        if self._docling_document is None:
            raise RuntimeError(
                "DoclingParser.chunk() called before parse(). "
                "Call parse() first to populate internal DoclingDocument."
            )

        from docling_core.transforms.chunker import HybridChunker

        chunker = HybridChunker(
            max_tokens=self._max_tokens,
            merge_peers=True,
        )
        chunk_iter = chunker.chunk(dl_doc=self._docling_document)
        raw_chunks = list(chunk_iter)

        chunks: list[Chunk] = []
        for idx, raw in enumerate(raw_chunks):
            # Extract heading hierarchy from HybridChunker metadata
            headings: list[str] = []
            meta = getattr(raw, "meta", None)
            if meta is not None:
                headings = list(getattr(meta, "headings", None) or [])

            heading = headings[-1] if headings else ""
            section_path = " > ".join(headings)
            heading_level = len(headings)

            chunks.append(
                Chunk(
                    text=raw.text,
                    section_path=section_path,
                    heading=heading,
                    heading_level=heading_level,
                    chunk_index=idx,
                    extra_metadata={},
                )
            )
        return chunks

    @classmethod
    def ensure_ready(cls, config: Any) -> None:
        """Validate Docling runtime. Delegates to ensure_docling_ready(). FR-3204."""
        ensure_docling_ready(
            parser_model=config.docling_model,
            artifacts_path=config.docling_artifacts_path,
            auto_download=config.docling_auto_download,
        )

    @classmethod
    def warmup(cls, config: Any) -> None:
        """Download Docling models. Delegates to warmup_docling_models(). FR-3207."""
        warmup_docling_models(
            artifacts_path=config.docling_artifacts_path,
            with_smolvlm=(config.vlm_mode == "builtin"),
        )
```

### Backward Compatibility

The existing standalone functions remain in `docling.py` and continue to work:

```python
# DEPRECATED: Use DoclingParser class instead. These aliases are preserved
# for backward compatibility with callers that have not migrated to the
# class-based API. Will be removed in a future release.

# parse_with_docling()       — still available
# ensure_docling_ready()     — still available
# warmup_docling_models()    — still available
# DoclingParseResult         — still available
```

No existing import statements break. The class is purely additive.

### Testing Checklist

- `DoclingParser` satisfies `isinstance(parser, DocumentParser)` (runtime_checkable protocol).
- `parse()` returns `ParseResult` with no `docling_document` attribute (verify `not hasattr(result, 'docling_document')`).
- `chunk()` returns `list[Chunk]` with populated `section_path`, `heading`, `heading_level`.
- Calling `chunk()` before `parse()` raises `RuntimeError`.
- Sequential reuse: `parse(doc_A)` then `parse(doc_B)` then `chunk()` uses doc_B's document, not doc_A's.

---

## 6. Plain Text Parser

**File:** `src/ingest/support/parser_text.py`

**Design Task:** Task 4

**FR Coverage:** FR-3280, FR-3281, FR-3282

```python
# src/ingest/support/parser_text.py

# @summary
# Plain text parser for .md, .txt, .rst, .html/.htm files.
# Exports: PlainTextParser
# Deps: pathlib, re, src.ingest.support.parser_base
# @end-summary

"""Plain text parser implementation.

Handles markdown, plain text, reStructuredText, and HTML files with minimal
processing. Heading-aware markdown chunking via the shared chunk_with_markdown()
utility.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from src.ingest.support.parser_base import (
    Chunk,
    DocumentParser,
    ParseResult,
    chunk_with_markdown,
)

logger = logging.getLogger(__name__)

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
_IMAGE_RE = re.compile(r"!\[.*?\]\(.*?\)")


class PlainTextParser:
    """Plain text parser implementing DocumentParser protocol. FR-3280.

    Handles .md, .txt, .rst, .html/.htm with minimal processing.
    No external model or service is invoked. FR-3281 AC 3.
    """

    def __init__(self) -> None:
        self._config: Any = None

    def parse(self, file_path: Path, config: Any) -> ParseResult:
        """Read file, normalise to markdown, extract headings. FR-3281.

        - .md, .txt: content used as-is.
        - .html/.htm: convert to markdown (strip tags, preserve headings).
        - .rst: convert to markdown or treat as plain text with heading heuristic.

        Args:
            file_path: Path to the source file.
            config: IngestionConfig instance.

        Returns:
            ParseResult with headings extracted and page_count=0.
        """
        self._config = config
        content = file_path.read_text(encoding="utf-8", errors="replace")
        suffix = file_path.suffix.lower()

        if suffix in (".html", ".htm"):
            content = self._html_to_markdown(content)
        elif suffix == ".rst":
            content = self._rst_to_markdown(content)
        # .md, .txt: use content as-is

        headings = self._extract_headings(content)
        has_figures = bool(_IMAGE_RE.search(content))

        return ParseResult(
            markdown=content,
            headings=headings,
            has_figures=has_figures,
            page_count=0,
        )

    def chunk(self, parse_result: ParseResult) -> list[Chunk]:
        """Chunk using shared markdown chunker. FR-3282.

        Delegates to chunk_with_markdown() which uses heading-aware splitting
        with MarkdownHeaderTextSplitter + RecursiveCharacterTextSplitter.

        Args:
            parse_result: ParseResult from a prior parse() call.

        Returns:
            List of Chunk objects with section_path from heading hierarchy.
        """
        if self._config is None:
            raise RuntimeError(
                "PlainTextParser.chunk() called before parse(). "
                "Call parse() first to populate config."
            )
        return chunk_with_markdown(parse_result, self._config)

    @classmethod
    def ensure_ready(cls, config: Any) -> None:
        """No-op. Plain text parsing has no external dependencies. FR-3204."""
        pass

    @classmethod
    def warmup(cls, config: Any) -> None:
        """No-op. No expensive assets to pre-load. FR-3207."""
        pass

    @staticmethod
    def _extract_headings(text: str) -> list[str]:
        """Extract markdown heading text in document order.

        Reuses the same regex pattern as docling.py's
        _extract_headings_from_markdown().
        """
        headings: list[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                heading = stripped.lstrip("#").strip()
                if heading:
                    headings.append(heading)
        return headings

    @staticmethod
    def _html_to_markdown(html: str) -> str:
        """Convert HTML to markdown. FR-3281 item 2.

        Uses markdownify if available, otherwise falls back to a minimal
        regex-based tag stripper that preserves heading structure.
        """
        try:
            from markdownify import markdownify as md
            return md(html, heading_style="ATX", strip=["script", "style"])
        except ImportError:
            logger.warning(
                "markdownify not installed; falling back to basic HTML stripping. "
                "Install with: uv add markdownify"
            )
            # Minimal fallback: convert <h1>-<h6> to # headings, strip other tags
            import re as _re
            text = html
            for level in range(1, 7):
                text = _re.sub(
                    rf"<h{level}[^>]*>(.*?)</h{level}>",
                    lambda m, lv=level: "#" * lv + " " + m.group(1),
                    text,
                    flags=_re.IGNORECASE | _re.DOTALL,
                )
            text = _re.sub(r"<[^>]+>", "", text)  # Strip remaining tags
            return text.strip()

    @staticmethod
    def _rst_to_markdown(rst: str) -> str:
        """Convert reStructuredText to markdown. FR-3281 item 3.

        Uses pypandoc if available, otherwise applies a heading heuristic
        that detects RST underline patterns (===, ---, ~~~).
        """
        try:
            import pypandoc
            return pypandoc.convert_text(rst, "md", format="rst")
        except (ImportError, OSError):
            logger.warning(
                "pypandoc not installed; falling back to RST heading heuristic. "
                "Install with: uv add pypandoc"
            )
            # Heuristic: lines followed by ===, ---, or ~~~ are headings
            import re as _re
            lines = rst.splitlines()
            result: list[str] = []
            i = 0
            while i < len(lines):
                if (
                    i + 1 < len(lines)
                    and lines[i].strip()
                    and _re.match(r"^[=\-~]{3,}$", lines[i + 1].strip())
                ):
                    char = lines[i + 1].strip()[0]
                    level = {"=": 1, "-": 2, "~": 3}.get(char, 2)
                    result.append("#" * level + " " + lines[i].strip())
                    i += 2
                else:
                    result.append(lines[i])
                    i += 1
            return "\n".join(result)
```

### Implementation Notes

- `markdownify` and `pypandoc` are optional dependencies. The parser degrades gracefully with
  fallback heuristics when they are absent. Document this in `pyproject.toml` as optional extras
  (e.g., `[project.optional-dependencies] parsers = ["markdownify", "pypandoc"]`).
- Table atomicity (FR-3282 item 4) is handled by the existing `chunk_markdown()` implementation
  in `src/ingest/support/markdown.py`, which uses `RecursiveCharacterTextSplitter` with newline
  separators. If table-splitting issues are observed, add a pre-processing step that wraps
  `|...|` table blocks into atomic markers before splitting.
- Performance target: `parse()` on a 10 KB markdown file should complete in under 100ms since
  no model loading or OCR is involved (FR-3281 AC 1).

---

## 7. Code Parser (tree-sitter)

**File:** `src/ingest/support/parser_code.py`

**Design Task:** Task 5

**FR Coverage:** FR-3250, FR-3251, FR-3252, FR-3253, FR-3254, FR-3255, FR-3256

### Dependencies

Add to `pyproject.toml`:

```toml
[project.optional-dependencies]
parsers = [
    "tree-sitter>=0.21",
    "tree-sitter-python",
    "tree-sitter-javascript",
    "tree-sitter-typescript",
    "tree-sitter-rust",
    "tree-sitter-go",
    "tree-sitter-java",
    "tree-sitter-c",
    "tree-sitter-cpp",
    "tree-sitter-c-sharp",
    "tree-sitter-ruby",
    "tree-sitter-kotlin",
    "tree-sitter-swift",
    "tree-sitter-scala",
    "tree-sitter-bash",
    "tree-sitter-yaml",
    "tree-sitter-toml",
    "tree-sitter-json",
    "markdownify",
    "pypandoc",
]
```

### Extension-to-Language Mapping

```python
# Internal mapping — not exposed via ParseResult or Chunk.

_EXTENSION_TO_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".rs": "rust",
    ".go": "go",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".java": "java",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".cs": "c_sharp",
    ".rb": "ruby",
    ".kt": "kotlin",
    ".swift": "swift",
    ".scala": "scala",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".json": "json",
}

_FILENAME_TO_LANGUAGE: dict[str, str] = {
    "Dockerfile": "dockerfile",
    "Makefile": "bash",
}
```

### Class Structure

```python
# src/ingest/support/parser_code.py

# @summary
# Code parser using tree-sitter for AST-aware parsing and chunking.
# Exports: CodeParser
# Deps: tree_sitter, pathlib, src.ingest.support.parser_base
# @end-summary

"""Code parser implementation using tree-sitter.

Produces one chunk per top-level function or class definition (FR-3252).
Extracts deterministic KG relationships from the AST (FR-3254).
Code chunks contain raw source code, not natural language (FR-3255).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from src.ingest.support.parser_base import Chunk, DocumentParser, ParseResult

logger = logging.getLogger(__name__)


class CodeParser:
    """tree-sitter code parser implementing DocumentParser protocol. FR-3250."""

    def __init__(self) -> None:
        self._tree: Any = None           # tree-sitter Tree (internal, never exposed)
        self._source_bytes: bytes = b""
        self._language: str = ""
        self._file_path: str = ""
        self._config: Any = None

    def parse(self, file_path: Path, config: Any) -> ParseResult:
        """Parse source file into AST and produce ParseResult. FR-3256.

        The markdown field contains source wrapped in a fenced code block.
        Headings contain the module docstring or filename. has_figures is
        always False. page_count is always 0.
        """
        import tree_sitter

        self._config = config
        self._file_path = str(file_path)
        self._source_bytes = file_path.read_bytes()
        source_text = self._source_bytes.decode("utf-8", errors="replace")

        # Determine language from extension or filename
        suffix = file_path.suffix.lower()
        self._language = _EXTENSION_TO_LANGUAGE.get(
            suffix,
            _FILENAME_TO_LANGUAGE.get(file_path.name, ""),
        )

        # Load tree-sitter grammar and parse
        if self._language:
            try:
                language_module = self._load_grammar(self._language)
                lang = tree_sitter.Language(language_module)
                parser = tree_sitter.Parser(lang)
                self._tree = parser.parse(self._source_bytes)
            except Exception as exc:
                logger.warning(
                    "tree-sitter parse failed for %s (%s): %s — "
                    "code will be treated as a single chunk.",
                    file_path, self._language, exc,
                )
                self._tree = None

        # Build markdown: fenced code block with language identifier
        lang_id = self._language or "text"
        markdown = f"```{lang_id}\n{source_text}\n```"

        # Extract headings: module docstring or filename
        headings = self._extract_module_heading(source_text, file_path.name)

        return ParseResult(
            markdown=markdown,
            headings=headings,
            has_figures=False,
            page_count=0,
        )

    def chunk(self, parse_result: ParseResult) -> list[Chunk]:
        """Produce one chunk per top-level function/class. FR-3252, FR-3253.

        Falls back to a single chunk if tree-sitter parsing failed.
        Populates extra_metadata with language, function_name, class_name,
        docstring, imports, decorators, and kg_relationships.
        """
        if self._config is None:
            raise RuntimeError(
                "CodeParser.chunk() called before parse(). "
                "Call parse() first."
            )

        source_text = self._source_bytes.decode("utf-8", errors="replace")

        if self._tree is None:
            # Fallback: single chunk for the whole file
            return [
                Chunk(
                    text=source_text,
                    section_path=self._file_path,
                    heading=Path(self._file_path).name,
                    heading_level=1,
                    chunk_index=0,
                    extra_metadata={
                        "language": self._language,
                        "file_path": self._file_path,
                        "function_name": "",
                        "class_name": "",
                        "docstring": "",
                        "imports": [],
                        "decorators": [],
                    },
                )
            ]

        chunks: list[Chunk] = []
        root = self._tree.root_node

        # Collect module-level imports for all chunks
        module_imports = self._extract_imports(root)

        # Collect top-level definitions and module-level code
        module_lines: list[str] = []
        definitions: list[dict[str, Any]] = []

        for child in root.children:
            node_type = child.type
            if self._is_function_def(node_type):
                definitions.append({
                    "kind": "function",
                    "node": child,
                    "class_name": "",
                })
            elif self._is_class_def(node_type):
                definitions.append({
                    "kind": "class",
                    "node": child,
                    "class_name": self._get_name(child),
                })
            else:
                # Module-level code (imports, constants, etc.)
                text = self._node_text(child)
                if text.strip():
                    module_lines.append(text)

        # Module-level chunk (imports, constants, top-level statements)
        if module_lines:
            chunks.append(
                Chunk(
                    text="\n".join(module_lines),
                    section_path=self._file_path,
                    heading=Path(self._file_path).name,
                    heading_level=1,
                    chunk_index=len(chunks),
                    extra_metadata={
                        "language": self._language,
                        "file_path": self._file_path,
                        "function_name": "",
                        "class_name": "",
                        "docstring": "",
                        "imports": module_imports,
                        "decorators": [],
                    },
                )
            )

        # Function and class chunks
        for defn in definitions:
            node = defn["node"]
            name = self._get_name(node)
            text = self._node_text(node)
            docstring = self._extract_docstring(node)
            decorators = self._extract_decorators(node)

            if defn["kind"] == "class":
                class_name = name
                function_name = ""
                heading_level = 2
                section_path = f"{self._file_path} > {name}"

                # Extract KG relationships from the class
                kg_rels = self._extract_kg_relationships(node, name, module_imports)

                chunks.append(
                    Chunk(
                        text=text,
                        section_path=section_path,
                        heading=name,
                        heading_level=heading_level,
                        chunk_index=len(chunks),
                        extra_metadata={
                            "language": self._language,
                            "file_path": self._file_path,
                            "function_name": "",
                            "class_name": class_name,
                            "docstring": docstring,
                            "imports": module_imports,
                            "decorators": decorators,
                            "kg_relationships": kg_rels,
                        },
                    )
                )
            else:
                function_name = name
                heading_level = 2
                section_path = f"{self._file_path} > {name}"

                kg_rels = self._extract_kg_relationships(node, name, module_imports)

                chunks.append(
                    Chunk(
                        text=text,
                        section_path=section_path,
                        heading=name,
                        heading_level=heading_level,
                        chunk_index=len(chunks),
                        extra_metadata={
                            "language": self._language,
                            "file_path": self._file_path,
                            "function_name": function_name,
                            "class_name": defn["class_name"],
                            "docstring": docstring,
                            "imports": module_imports,
                            "decorators": decorators,
                            "kg_relationships": kg_rels,
                        },
                    )
                )

        return chunks

    @classmethod
    def ensure_ready(cls, config: Any) -> None:
        """Verify tree-sitter is importable and at least one grammar loads."""
        try:
            import tree_sitter  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "tree-sitter is required for code parsing but not installed. "
                "Install with: uv add tree-sitter"
            ) from exc
        # Verify at least one grammar can load (Python as canary)
        try:
            import tree_sitter_python  # noqa: F401
        except ImportError:
            logger.warning(
                "tree-sitter-python grammar not installed. "
                "Code parser will be limited. "
                "Install with: uv add tree-sitter-python"
            )

    @classmethod
    def warmup(cls, config: Any) -> None:
        """Pre-load grammars. tree-sitter grammars are compiled .so files,
        so warmup ensures they are importable."""
        cls.ensure_ready(config)

    # --- Internal helpers (language-specific node type resolution) ---

    @staticmethod
    def _load_grammar(language: str) -> Any:
        """Dynamically import tree-sitter grammar module for the given language."""
        module_name = f"tree_sitter_{language}"
        if language == "c_sharp":
            module_name = "tree_sitter_c_sharp"
        elif language == "cpp":
            module_name = "tree_sitter_cpp"

        import importlib
        mod = importlib.import_module(module_name)
        return mod.language()

    def _is_function_def(self, node_type: str) -> bool:
        """Check if a node type represents a function definition."""
        return node_type in {
            "function_definition",    # Python, C, C++
            "function_item",          # Rust
            "function_declaration",   # Go, JS, TS, Java, C#, Swift, Kotlin
            "method_declaration",     # Java, C#
            "arrow_function",         # JS, TS
            "method_definition",      # Ruby
        }

    def _is_class_def(self, node_type: str) -> bool:
        """Check if a node type represents a class definition."""
        return node_type in {
            "class_definition",       # Python
            "class_declaration",      # Java, C#, TS, JS, Kotlin, Swift
            "struct_item",            # Rust
            "impl_item",             # Rust
            "type_declaration",       # Go
        }

    def _node_text(self, node: Any) -> str:
        """Extract source text for a tree-sitter node."""
        return self._source_bytes[node.start_byte:node.end_byte].decode(
            "utf-8", errors="replace"
        )

    def _get_name(self, node: Any) -> str:
        """Extract the name identifier from a definition node."""
        for child in node.children:
            if child.type in ("identifier", "name", "type_identifier"):
                return self._node_text(child)
        return "<anonymous>"

    def _extract_docstring(self, node: Any) -> str:
        """Extract docstring from a function/class definition (Python-specific)."""
        if self._language != "python":
            return ""
        body = None
        for child in node.children:
            if child.type == "block":
                body = child
                break
        if body is None:
            return ""
        for child in body.children:
            if child.type == "expression_statement":
                for grandchild in child.children:
                    if grandchild.type == "string":
                        raw = self._node_text(grandchild)
                        return raw.strip("\"'").strip()
            break  # Only check the first statement
        return ""

    def _extract_decorators(self, node: Any) -> list[str]:
        """Extract decorator names from a function/class definition."""
        decorators: list[str] = []
        for child in node.children:
            if child.type == "decorator":
                text = self._node_text(child).lstrip("@").split("(")[0].strip()
                if text:
                    decorators.append(text)
        return decorators

    def _extract_imports(self, root_node: Any) -> list[str]:
        """Extract import statements from the module root."""
        imports: list[str] = []
        for child in root_node.children:
            if child.type in (
                "import_statement",
                "import_from_statement",
                "use_declaration",        # Rust
                "import_declaration",     # Go, Java, Kotlin
            ):
                imports.append(self._node_text(child))
        return imports

    @staticmethod
    def _extract_module_heading(source_text: str, filename: str) -> list[str]:
        """Extract module docstring (Python) or use filename as heading."""
        lines = source_text.lstrip().splitlines()
        if lines and lines[0].startswith('"""'):
            # Multi-line or single-line docstring
            if lines[0].count('"""') >= 2:
                return [lines[0].strip('"""').strip()]
            for i, line in enumerate(lines[1:], 1):
                if '"""' in line:
                    docstring = " ".join(
                        l.strip() for l in lines[0:i + 1]
                    ).strip('"""').strip()
                    return [docstring] if docstring else [filename]
        return [filename]

    def _extract_kg_relationships(
        self, node: Any, enclosing_name: str, module_imports: list[str]
    ) -> list[dict[str, str]]:
        """Extract deterministic KG relationships from AST. FR-3254.

        Relationships:
        - imports: from import statements -> {type: "imports", source, target}
        - inherits: from class base classes -> {type: "inherits", source, target}
        - calls: from function call expressions -> {type: "calls", source, target}

        All extraction is deterministic — no LLM calls.
        """
        relationships: list[dict[str, str]] = []

        # Import relationships (from module-level imports)
        for imp in module_imports:
            # Parse "import X" or "from X import Y"
            parts = imp.split()
            if len(parts) >= 2 and parts[0] == "import":
                relationships.append({
                    "type": "imports",
                    "source": enclosing_name,
                    "target": parts[1].rstrip(","),
                })
            elif len(parts) >= 4 and parts[0] == "from" and parts[2] == "import":
                for target in parts[3:]:
                    target = target.rstrip(",").strip()
                    if target and target != "(":
                        relationships.append({
                            "type": "imports",
                            "source": enclosing_name,
                            "target": f"{parts[1]}.{target}",
                        })

        # Inheritance relationships (class definitions with base classes)
        if self._is_class_def(node.type):
            for child in node.children:
                if child.type == "argument_list":
                    for arg in child.children:
                        if arg.type in ("identifier", "attribute"):
                            base_name = self._node_text(arg)
                            relationships.append({
                                "type": "inherits",
                                "source": enclosing_name,
                                "target": base_name,
                            })

        # Call relationships (walk tree for call expressions)
        self._walk_calls(node, enclosing_name, relationships)

        return relationships

    def _walk_calls(
        self, node: Any, enclosing: str, relationships: list[dict[str, str]]
    ) -> None:
        """Recursively walk AST to find function call expressions."""
        if node.type == "call":
            func_node = node.children[0] if node.children else None
            if func_node is not None:
                called = self._node_text(func_node).split("(")[0].strip()
                if called and not called.startswith("("):
                    relationships.append({
                        "type": "calls",
                        "source": enclosing,
                        "target": called,
                    })
        for child in node.children:
            self._walk_calls(child, enclosing, relationships)
```

### Implementation Notes

- `_load_grammar()` uses `importlib.import_module()` to dynamically load tree-sitter grammar
  packages. Each grammar package exposes a `language()` function that returns the grammar handle.
- The `_is_function_def()` and `_is_class_def()` helpers map node types across languages. This
  is the only language-specific logic in the parser; everything else uses tree-sitter's universal
  node traversal API (FR-3250 AC 3).
- For classes exceeding max chunk size, the implementation should split into one chunk per method.
  The initial implementation produces one chunk per class. Add size-based method splitting as a
  follow-up if needed.
- KG relationship extraction (FR-3254) is deterministic — re-parsing the same file produces
  identical relationships. No LLM calls are made.

---

## 8. Parser Registry and Routing

**File:** `src/ingest/support/parser_registry.py`

**Design Task:** Task 6

**FR Coverage:** FR-3300, FR-3301, FR-3302, FR-3303

```python
# src/ingest/support/parser_registry.py

# @summary
# Parser registry mapping file extensions to parser strategies.
# Exports: ParserRegistry
# Deps: pathlib, logging, src.ingest.support.parser_base
# @end-summary

"""Parser strategy registry.

Maps file extensions to parser strategies (document, code, text) and provides
parser instances to pipeline nodes. Pipeline nodes obtain parsers via
registry.get_parser(), never by importing concrete parser classes directly.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from src.ingest.support.parser_base import DocumentParser

logger = logging.getLogger(__name__)


# Canonical extension-to-strategy mapping (Spec Appendix A)
_EXTENSION_MAP: dict[str, str] = {
    # Document strategy
    ".pdf": "document", ".docx": "document", ".pptx": "document",
    ".png": "document", ".jpg": "document", ".jpeg": "document",
    ".tiff": "document", ".bmp": "document",
    # Code strategy
    ".py": "code", ".rs": "code", ".go": "code",
    ".ts": "code", ".tsx": "code", ".js": "code", ".jsx": "code",
    ".java": "code", ".c": "code", ".h": "code",
    ".cpp": "code", ".hpp": "code", ".cc": "code", ".cxx": "code",
    ".cs": "code", ".rb": "code", ".kt": "code",
    ".swift": "code", ".scala": "code",
    ".sh": "code", ".bash": "code", ".zsh": "code",
    ".yaml": "code", ".yml": "code", ".toml": "code", ".json": "code",
    # Plain text strategy
    ".md": "text", ".txt": "text", ".rst": "text",
    ".html": "text", ".htm": "text",
}

_FILENAME_MAP: dict[str, str] = {
    "Dockerfile": "code",
    "Makefile": "code",
}


class ParserRegistry:
    """Maps file extensions to parser strategies. FR-3303.

    Attempts to import each parser class at init time. If a parser's
    dependencies are missing (e.g., tree-sitter not installed), that strategy
    is silently skipped. At minimum the 'text' strategy must be available
    (it has no external dependencies).
    """

    def __init__(self, config: Any) -> None:
        """Register available parsers.

        Args:
            config: IngestionConfig instance.

        Raises:
            RuntimeError: If no parser strategy is available (not even 'text').
        """
        self._strategy_map: dict[str, type] = {}
        self._config = config

        # Always register plain text parser (no external deps)
        from src.ingest.support.parser_text import PlainTextParser
        self._strategy_map["text"] = PlainTextParser

        # Attempt to register document parser (requires Docling)
        if getattr(config, "enable_docling_parser", True):
            try:
                from src.ingest.support.docling import DoclingParser
                self._strategy_map["document"] = DoclingParser
            except ImportError:
                logger.info(
                    "Docling not available; 'document' parser strategy disabled."
                )

        # Attempt to register code parser (requires tree-sitter)
        try:
            from src.ingest.support.parser_code import CodeParser
            self._strategy_map["code"] = CodeParser
        except ImportError:
            logger.info(
                "tree-sitter not available; 'code' parser strategy disabled."
            )

        if not self._strategy_map:
            raise RuntimeError(
                "No parser strategy is available. At minimum, the 'text' "
                "strategy must be loadable."
            )

        registered = ", ".join(sorted(self._strategy_map.keys()))
        logger.info("Parser registry initialised with strategies: %s", registered)

    def get_parser(self, file_path: Path, config: Any) -> DocumentParser:
        """Return a new parser instance for the given file. FR-3300, FR-3301.

        If config.parser_strategy != "auto", uses the forced strategy.
        Otherwise, looks up extension in the canonical mapping.
        Unknown extensions fall back to 'text' with a warning (FR-3302).

        Args:
            file_path: Path to the source file.
            config: IngestionConfig instance.

        Returns:
            A new DocumentParser instance (per-document lifecycle, FR-3206).

        Raises:
            RuntimeError: If the forced strategy is not registered.
        """
        strategy_override = getattr(config, "parser_strategy", "auto")

        if strategy_override != "auto":
            if strategy_override not in self._strategy_map:
                raise RuntimeError(
                    f"parser_strategy='{strategy_override}' is configured but "
                    f"the '{strategy_override}' parser is not available. "
                    f"Available strategies: {sorted(self._strategy_map.keys())}"
                )
            return self._strategy_map[strategy_override]()

        # Auto routing: check filename first, then extension
        filename = file_path.name
        strategy = _FILENAME_MAP.get(filename)

        if strategy is None:
            ext = file_path.suffix.lower()
            strategy = _EXTENSION_MAP.get(ext)

        if strategy is None:
            logger.warning(
                "Unrecognised extension '%s' for file '%s'; "
                "falling back to 'text' parser strategy.",
                file_path.suffix, file_path.name,
            )
            strategy = "text"

        # If the resolved strategy is not registered, fall back to text
        if strategy not in self._strategy_map:
            logger.warning(
                "Strategy '%s' for file '%s' is not available "
                "(missing dependency); falling back to 'text'.",
                strategy, file_path.name,
            )
            strategy = "text"

        return self._strategy_map[strategy]()

    def ensure_all_ready(self, config: Any) -> None:
        """Call ensure_ready() on all registered parsers. FR-3204.

        Called at pipeline startup before any file is processed.

        Raises:
            RuntimeError: If any parser's ensure_ready() fails.
        """
        for name, parser_cls in self._strategy_map.items():
            logger.debug("Checking readiness for parser strategy: %s", name)
            parser_cls.ensure_ready(config)

    def warmup_all(self, config: Any) -> None:
        """Call warmup() on all registered parsers. FR-3207.

        For container/deployment pre-warming. Non-fatal: warmup failures
        are logged but do not prevent startup.
        """
        for name, parser_cls in self._strategy_map.items():
            try:
                parser_cls.warmup(config)
            except Exception as exc:
                logger.warning(
                    "Warmup failed for parser strategy '%s': %s", name, exc,
                )

    @property
    def available_strategies(self) -> list[str]:
        """Return list of registered strategy names."""
        return sorted(self._strategy_map.keys())
```

### Integration Point

The registry is instantiated during pipeline startup in `src/ingest/impl.py` and attached to
`Runtime`. Pipeline nodes access it via `state["runtime"].parser_registry`.

```python
# In src/ingest/impl.py, during pipeline initialisation:

from src.ingest.support.parser_registry import ParserRegistry

registry = ParserRegistry(config)
registry.ensure_all_ready(config)
# Attach to Runtime so nodes can access it
runtime = Runtime(
    config=config,
    embedder=embedder,
    weaviate_client=weaviate_client,
    kg_builder=kg_builder,
    parser_registry=registry,  # NEW field
)
```

---

## 9. Chunker Override Implementation

**Design Task:** Task 7

**FR Coverage:** FR-3320, FR-3321, FR-3322, FR-3323

### Config Field Additions

Add to `config/settings.py`:

```python
RAG_INGESTION_PARSER_STRATEGY: str = os.getenv("RAG_INGESTION_PARSER_STRATEGY", "auto")
RAG_INGESTION_CHUNKER: str = os.getenv("RAG_INGESTION_CHUNKER", "native")
```

Add to `IngestionConfig` in `src/ingest/common/types.py`:

```python
@dataclass
class IngestionConfig:
    # ... existing fields ...

    parser_strategy: str = RAG_INGESTION_PARSER_STRATEGY
    """Parser selection: "auto", "document", "code", "text". Default: "auto". FR-3301."""

    chunker: str = RAG_INGESTION_CHUNKER
    """Chunker selection: "native" or "markdown". Default: "native". FR-3320."""
```

### Validation in verify_core_design()

Add to `src/ingest/impl.py` inside `verify_core_design()`:

```python
# Chunker override validation (FR-3322)
if config.chunker not in ("native", "markdown"):
    errors.append(
        f"chunker must be 'native' or 'markdown', got '{config.chunker}'."
    )

# Parser strategy validation (FR-3301 AC 3)
if config.parser_strategy not in ("auto", "document", "code", "text"):
    errors.append(
        f"parser_strategy must be 'auto', 'document', 'code', or 'text', "
        f"got '{config.parser_strategy}'."
    )

# Chunker override logging (FR-3323)
if config.chunker == "markdown":
    warnings.append(
        "Chunker override active: all parsers will use markdown-based "
        "chunking. Native chunking (with richer heading metadata from "
        "HybridChunker, AST-aware code splitting) is disabled."
    )
```

### Override Logic in chunking_node

The override is applied by the calling node, not inside each parser:

```python
# In chunking_node, after obtaining parser_instance and parse_result from state:

if config.chunker == "markdown":
    chunks = chunk_with_markdown(parse_result, config)
else:
    # config.chunker == "native"
    try:
        chunks = parser_instance.chunk(parse_result)
    except Exception as exc:
        logger.error(
            "Native chunking failed for source=%s: %s — falling back to markdown",
            state.get("source_name", "<unknown>"), exc,
        )
        chunks = chunk_with_markdown(parse_result, config)
        processing_log = append_processing_log(state, "chunking:fallback_to_markdown")
```

---

## 10. VLM Mode Validation Guard

**Design Task:** Task 8

**FR Coverage:** FR-3340, FR-3341, FR-3342

Add to `verify_core_design()` in `src/ingest/impl.py`:

```python
def verify_core_design(config: IngestionConfig) -> IngestionDesignCheck:
    errors: list[str] = []
    warnings: list[str] = []

    # ... existing validation checks ...

    # VLM mutual exclusion guard (FR-3340, FR-3341)
    if config.vlm_mode == "builtin" and config.enable_multimodal_processing:
        errors.append(
            "vlm_mode='builtin' and enable_multimodal_processing=true are mutually "
            "exclusive. vlm_mode='builtin' describes figures at parse time via Docling "
            "SmolVLM. enable_multimodal_processing describes figures in the Phase 1 "
            "multimodal node via vision.py. Disable one to prevent double VLM "
            "processing of figure images."
        )

    # External + multimodal coexistence info (FR-3342)
    if config.vlm_mode == "external" and config.enable_multimodal_processing:
        warnings.append(
            "vlm_mode='external' and enable_multimodal_processing are both active. "
            "Phase 1 multimodal node will process figures pre-chunking; "
            "vlm_mode='external' will enrich chunks post-chunking. Both being active "
            "is valid but means figures are processed at two pipeline stages."
        )

    # ... existing checks continue ...
    return IngestionDesignCheck(ok=not errors, errors=errors, warnings=warnings)
```

### VLM Mode Compatibility Matrix (Spec Appendix C)

| `vlm_mode` | `enable_multimodal_processing` | Validation Result |
|------------|-------------------------------|-------------------|
| `"disabled"` | `false` | OK. No VLM processing. |
| `"disabled"` | `true` | OK. Phase 1 multimodal node only. |
| `"builtin"` | `false` | OK. Docling SmolVLM at parse time. |
| `"builtin"` | `true` | **ERROR.** Mutual exclusion violation. |
| `"external"` | `false` | OK. Post-chunking VLM enrichment only. |
| `"external"` | `true` | OK (with warning). Both stages active. |

All six combinations must be covered in `tests/ingest/test_vlm_guard.py`.

---

## 11. Pipeline Node Updates (structure_detection, chunking)

**Design Task:** Task 9

**FR Coverage:** FR-3200 AC 4, FR-3205 AC 2, FR-3303 AC 2

### State Schema Changes

**`src/ingest/common/types.py` — IngestState:**

```python
class IngestState(TypedDict):
    # ... existing fields ...
    # REMOVED: docling_document: Any
    # ADDED:
    parse_result: Any           # ParseResult from parser abstraction
    parser_instance: Any        # Transient parser instance (never serialised)
    # ... rest of existing fields ...
```

**`src/ingest/common/types.py` — Runtime:**

```python
@dataclass
class Runtime:
    config: IngestionConfig
    embedder: LocalBGEEmbeddings
    weaviate_client: Any
    kg_builder: Optional[KnowledgeGraphBuilder]
    db_client: Optional[Any] = None
    parser_registry: Any = None  # ParserRegistry (typed as Any to avoid circular import)
```

**`src/ingest/embedding/state.py` — EmbeddingPipelineState:**

```python
class EmbeddingPipelineState(TypedDict, total=False):
    # ... existing fields ...
    # REMOVED: docling_document: Optional[Any]
    # ADDED:
    parse_result: Any           # ParseResult from parser abstraction
    parser_instance: Any        # Transient parser instance for chunk() call
    # ... rest of existing fields ...
```

### Updated structure_detection_node

```python
# src/ingest/doc_processing/nodes/structure_detection.py

def structure_detection_node(state: DocumentProcessingState) -> dict[str, Any]:
    """Extract structural signals via parser abstraction. FR-3200 AC 4."""
    config = state["runtime"].config
    registry = state["runtime"].parser_registry
    raw_text = state["raw_text"]

    figures: list[str] = []
    headings: list[str] = []
    parsed_text = raw_text
    parse_result = None
    parser_instance = None
    parser_strategy = "unknown"

    if registry is not None:
        try:
            parser_instance = registry.get_parser(
                Path(state["source_path"]), config
            )
            parse_result = parser_instance.parse(
                Path(state["source_path"]), config
            )
            parsed_text = parse_result.markdown
            headings = parse_result.headings
            figures = (
                [f"Figure {i+1}" for i in range(10)]  # Placeholder count
                if parse_result.has_figures else []
            )
            # Determine which strategy was used for routing
            parser_strategy = type(parser_instance).__name__.lower().replace("parser", "")
        except Exception as exc:
            if config.docling_strict:
                return {
                    "errors": [f"parser_failed:{state['source_name']}:{exc}"],
                    "should_skip": True,
                    "processing_log": append_processing_log(
                        state, "structure_detection:failed",
                    ),
                }
            # Non-strict fallback: regex heuristics
            figures = _FIGURE_PATTERN.findall(raw_text)
            headings = _HEADING_PATTERN.findall(raw_text)
    else:
        # No registry available — legacy fallback to regex
        figures = _FIGURE_PATTERN.findall(raw_text)
        headings = _HEADING_PATTERN.findall(raw_text)

    structure = {
        "has_figures": bool(figures),
        "figures": figures[:_MAX_FIGURES],
        "heading_count": len(headings),
        "docling_enabled": bool(config.enable_docling_parser),
        "docling_model": str(config.docling_model),
        # NEW: strategy name replaces docling_document_available boolean
        "parser_strategy": parser_strategy,
    }

    update: dict[str, Any] = {
        "raw_text": parsed_text,
        "structure": structure,
        "processing_log": append_processing_log(state, "structure_detection:ok"),
    }

    # Store parse_result and parser_instance for chunking_node
    if parse_result is not None:
        update["parse_result"] = parse_result
    if parser_instance is not None:
        update["parser_instance"] = parser_instance

    return update
```

### Updated chunking_node

```python
# src/ingest/embedding/nodes/chunking.py

from src.ingest.support.parser_base import Chunk, chunk_with_markdown


def chunking_node(state: EmbeddingPipelineState) -> dict[str, Any]:
    """Split document into chunks using parser abstraction. FR-3303 AC 2."""
    config = state["runtime"].config

    try:
        base_metadata = metadata_to_dict(
            extract_metadata(state["raw_text"], state["source_name"])
        )
        base_metadata.update({
            "source": state["source_name"],
            "source_uri": state["source_uri"],
            "source_key": state["source_key"],
            "source_id": state["source_id"],
            "connector": state["connector"],
            "source_version": state["source_version"],
        })

        parse_result = state.get("parse_result")
        parser_instance = state.get("parser_instance")

        if parse_result is not None and parser_instance is not None:
            # New parser abstraction path
            if config.chunker == "markdown":
                raw_chunks = chunk_with_markdown(parse_result, config)
                processing_log = append_processing_log(state, "chunking:markdown_override")
            else:
                try:
                    raw_chunks = parser_instance.chunk(parse_result)
                    processing_log = append_processing_log(state, "chunking:native_ok")
                except Exception as exc:
                    logger.error(
                        "Native chunking failed for source=%s: %s — "
                        "falling back to markdown",
                        state.get("source_name", "<unknown>"), exc,
                    )
                    raw_chunks = chunk_with_markdown(parse_result, config)
                    processing_log = append_processing_log(
                        state, "chunking:fallback_to_markdown"
                    )
        else:
            # Legacy fallback: markdown-only chunking (no parser abstraction)
            from src.ingest.support.parser_base import ParseResult
            fallback_result = ParseResult(
                markdown=state.get("refactored_text") or state.get("cleaned_text", ""),
                headings=[],
                has_figures=False,
                page_count=0,
            )
            raw_chunks = chunk_with_markdown(fallback_result, config)
            processing_log = append_processing_log(state, "chunking:legacy_markdown")

        # Map Chunk -> ProcessedChunk
        total = len(raw_chunks)
        chunks = [
            ProcessedChunk(
                text=_normalize_chunk_text(c.text),
                metadata={
                    **base_metadata,
                    "section_path": c.section_path,
                    "heading": c.heading,
                    "heading_level": c.heading_level,
                    "chunk_index": c.chunk_index,
                    "total_chunks": total,
                    **c.extra_metadata,
                },
            )
            for c in raw_chunks
        ]

    except Exception as exc:
        return {
            **state,
            "errors": state.get("errors", []) + [f"chunking:{exc}"],
            "processing_log": append_processing_log(state, "chunking:error"),
        }

    return {
        "chunks": chunks,
        "processing_log": processing_log,
    }
```

### Key Migration Notes

1. **`docling_document` removal.** The `docling_document` key is removed from both `IngestState`
   and `EmbeddingPipelineState`. It was never persisted to durable storage (only in-memory
   LangGraph state), so no data migration is needed.

2. **`structure["docling_document_available"]` replacement.** Downstream conditional edges that
   currently check `structure["docling_document_available"]` (a boolean) should be updated to
   check `structure["parser_strategy"]` (a string). The routing logic changes from
   `if docling_document_available: skip_cleaning` to
   `if parser_strategy in ("docling", "document"): skip_cleaning`.

3. **`parser_instance` is transient.** It exists only in in-memory LangGraph state for the
   duration of one document's processing. It is never serialised, persisted, or checkpointed.
   If LangGraph checkpointing is added later, the parser must be re-instantiated from the
   source file on resume.

4. **HybridChunker import removal.** The `from docling_core.transforms.chunker import HybridChunker`
   import is removed from `chunking_node`. HybridChunker is now called inside
   `DoclingParser.chunk()`, keeping the Docling dependency encapsulated.

5. **Downstream node impact.** No changes are required to `text_cleaning_node`,
   `document_refactoring_node`, `vlm_enrichment_node`, `chunk_enrichment_node`,
   `metadata_generation_node`, `quality_validation_node`, or `embedding_storage_node`. They all
   consume `ProcessedChunk` objects, which are unchanged.

---

## 12. Configuration Reference

### New Configuration Fields

| Field | Type | Default | Env Var | Description | FR |
|-------|------|---------|---------|-------------|-----|
| `parser_strategy` | `str` | `"auto"` | `RAG_INGESTION_PARSER_STRATEGY` | Parser selection mode. `"auto"` routes by extension; `"document"`, `"code"`, `"text"` force a specific strategy. | FR-3301 |
| `chunker` | `str` | `"native"` | `RAG_INGESTION_CHUNKER` | Chunker selection. `"native"` uses each parser's internal chunker; `"markdown"` forces heading-aware markdown splitting for all parsers. | FR-3320 |

### Existing Fields Affected

| Field | Change | Impact |
|-------|--------|--------|
| `enable_docling_parser` | Now controls whether the `"document"` strategy is registered in `ParserRegistry`. When `false`, document-format files fall back to `"text"`. | Backward compatible: default `true` preserves existing behaviour. |
| `vlm_mode` | New validation constraint: `"builtin"` is mutually exclusive with `enable_multimodal_processing=true`. | Backward compatible if existing configs do not use both simultaneously. Configs that do will fail fast at startup with a clear error. |

### Validation Rules (verify_core_design)

| Rule | Trigger | Severity | Message |
|------|---------|----------|---------|
| Chunker must be valid | `chunker not in ("native", "markdown")` | Error | `chunker must be 'native' or 'markdown'` |
| Parser strategy must be valid | `parser_strategy not in ("auto", "document", "code", "text")` | Error | `parser_strategy must be 'auto', 'document', 'code', or 'text'` |
| VLM mutual exclusion | `vlm_mode="builtin"` AND `enable_multimodal_processing=true` | Error | Both are mutually exclusive; disable one to prevent double VLM processing |
| VLM coexistence info | `vlm_mode="external"` AND `enable_multimodal_processing=true` | Warning | Both active; figures processed at two pipeline stages |
| Chunker override warning | `chunker="markdown"` | Warning | Native chunking disabled; richer heading metadata unavailable |

### Backward Compatibility Summary

| Change | Backward Compatible? | Reason |
|--------|---------------------|--------|
| `parser_strategy="auto"` (default) | Yes | Auto routing uses Docling for document formats, same as before. |
| `chunker="native"` (default) | Yes | Native chunking for Docling = HybridChunker, same as before. |
| `docling_document` removed from state | Breaking (Phase D) | No external tools are known to depend on this key. Was always typed `Any`. |
| `parse_result` added to state | Additive | New key, default `None` until `structure_detection_node` runs. |
| VLM guard | Breaking for invalid configs | Only breaks configs that have both `vlm_mode="builtin"` and `enable_multimodal_processing=true`, which was always a latent bug. |
