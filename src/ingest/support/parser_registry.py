# @summary
# Parser registry mapping file extensions to parser strategies.
# Exports: ParserRegistry, get_parser_for, ensure_all_ready
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
    # Document strategy (Docling)
    ".pdf": "document", ".docx": "document", ".pptx": "document",
    ".xlsx": "document",
    ".png": "document", ".jpg": "document", ".jpeg": "document",
    ".tiff": "document", ".bmp": "document",
    # Code strategy (tree-sitter)
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
    is silently skipped with a log message. At minimum the 'text' strategy
    must be available (it has no external dependencies).
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

        # If the resolved strategy is not registered (missing dep), fall back to text
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

        Args:
            config: IngestionConfig instance.

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

        Args:
            config: IngestionConfig instance.
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


# ---------------------------------------------------------------------------
# Module-level convenience functions (stable import surface for callers
# that do not need a full registry instance)
# ---------------------------------------------------------------------------

def get_parser_for(file_path: Path, config: Any) -> DocumentParser:
    """Convenience wrapper: create a registry and return a parser for file_path.

    Intended for one-off use in tests and CLI tools. For production pipeline
    use, maintain a ParserRegistry instance on Runtime.

    Args:
        file_path: Path to the source file.
        config: IngestionConfig instance.

    Returns:
        A new DocumentParser instance appropriate for file_path.
    """
    registry = ParserRegistry(config)
    return registry.get_parser(file_path, config)


def ensure_all_ready(config: Any) -> None:
    """Convenience wrapper: ensure all registered parsers are ready.

    Creates a temporary registry to call ensure_ready() on each strategy.

    Args:
        config: IngestionConfig instance.
    """
    registry = ParserRegistry(config)
    registry.ensure_all_ready(config)
