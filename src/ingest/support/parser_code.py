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


# Internal extension-to-language mapping — not exposed in ParseResult or Chunk.
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


class CodeParser:
    """tree-sitter code parser implementing DocumentParser protocol. FR-3250.

    Produces one chunk per top-level function or class definition, plus an
    optional module-level chunk for imports and top-level statements.
    Extracts KG relationships (imports, inherits, calls) from the AST. FR-3254.
    """

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

        Args:
            file_path: Path to the source file.
            config: IngestionConfig instance.

        Returns:
            ParseResult with markdown (fenced code block), headings, has_figures=False,
            page_count=0.
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

        Args:
            parse_result: ParseResult from a prior parse() call.

        Returns:
            List of Chunk objects with AST-derived section_path and extra_metadata.

        Raises:
            RuntimeError: If called before parse().
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
            kg_rels = self._extract_kg_relationships(node, name, module_imports)

            if defn["kind"] == "class":
                chunks.append(
                    Chunk(
                        text=text,
                        section_path=f"{self._file_path} > {name}",
                        heading=name,
                        heading_level=2,
                        chunk_index=len(chunks),
                        extra_metadata={
                            "language": self._language,
                            "file_path": self._file_path,
                            "function_name": "",
                            "class_name": name,
                            "docstring": docstring,
                            "imports": module_imports,
                            "decorators": decorators,
                            "kg_relationships": kg_rels,
                        },
                    )
                )
            else:
                chunks.append(
                    Chunk(
                        text=text,
                        section_path=f"{self._file_path} > {name}",
                        heading=name,
                        heading_level=2,
                        chunk_index=len(chunks),
                        extra_metadata={
                            "language": self._language,
                            "file_path": self._file_path,
                            "function_name": name,
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
        """Verify tree-sitter is importable and at least one grammar loads. FR-3204.

        Raises:
            RuntimeError: If tree-sitter package is not installed.
        """
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
        so warmup ensures they are importable. FR-3207."""
        cls.ensure_ready(config)

    # -------------------------------------------------------------------------
    # Internal helpers (language-specific node type resolution)
    # -------------------------------------------------------------------------

    @staticmethod
    def _load_grammar(language: str) -> Any:
        """Dynamically import tree-sitter grammar module for the given language.

        Args:
            language: Language identifier (e.g., "python", "rust").

        Returns:
            Grammar handle returned by the grammar package's language() function.

        Raises:
            ImportError: If the grammar package is not installed.
        """
        import importlib
        module_name = f"tree_sitter_{language}"
        mod = importlib.import_module(module_name)
        return mod.language()

    def _is_function_def(self, node_type: str) -> bool:
        """Return True if node_type represents a function definition."""
        return node_type in {
            "function_definition",    # Python, C, C++
            "function_item",          # Rust
            "function_declaration",   # Go, JS, TS, Java, C#, Swift, Kotlin
            "method_declaration",     # Java, C#
            "arrow_function",         # JS, TS
            "method_definition",      # Ruby
        }

    def _is_class_def(self, node_type: str) -> bool:
        """Return True if node_type represents a class/type definition."""
        return node_type in {
            "class_definition",       # Python
            "class_declaration",      # Java, C#, TS, JS, Kotlin, Swift
            "struct_item",            # Rust
            "impl_item",              # Rust
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
                        ln.strip() for ln in lines[0:i + 1]
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

        Args:
            node: AST node for the enclosing definition.
            enclosing_name: Name of the enclosing function or class.
            module_imports: Module-level import statements.

        Returns:
            List of relationship dicts with type, source, target keys.
        """
        relationships: list[dict[str, str]] = []

        # Import relationships (from module-level imports)
        for imp in module_imports:
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
