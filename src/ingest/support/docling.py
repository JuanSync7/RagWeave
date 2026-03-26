 # @summary
 # Docling integration for ingestion parsing into markdown.
 # Exports: DoclingParseResult, warmup_docling_models, ensure_docling_ready, parse_with_docling
 # Deps: dataclasses, pathlib, typing
 # @end-summary
"""Docling integration for ingestion parsing.

This module provides a minimal adapter around Docling to parse source documents
into markdown for downstream ingestion steps (chunking, metadata extraction,
and optional multimodal processing).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class DoclingParseResult:
    """Docling parsing output normalized for ingestion nodes.

    Attributes:
        text_markdown: Parsed markdown text.
        has_figures: Whether Docling detected any figures/pictures.
        figures: Lightweight figure identifiers for telemetry/UI.
        headings: Extracted heading text in document order.
        parser_model: Parser model identifier used for telemetry/debugging.
    """

    text_markdown: str
    has_figures: bool
    figures: list[str]
    headings: list[str]
    parser_model: str


def warmup_docling_models(*, artifacts_path: str = "") -> Path:
    """Download and validate core Docling models used by ingestion.

    Args:
        artifacts_path: Optional directory to store downloaded artifacts. When
            empty, Docling's default cache location is used.

    Returns:
        The resolved Docling model root directory.

    Raises:
        RuntimeError: If Docling's downloader is unavailable or required models
            are missing after download.
    """
    try:
        from docling.datamodel.pipeline_options import LayoutOptions
        from docling.models.stages.table_structure.table_structure_model import (
            TableStructureModel,
        )
        from docling.utils.model_downloader import download_models
    except Exception as exc:  # pragma: no cover - import path depends on runtime env
        raise RuntimeError("Docling model downloader is unavailable") from exc

    output_dir = None
    if artifacts_path:
        output_dir = Path(artifacts_path)
        output_dir.mkdir(parents=True, exist_ok=True)

    model_root = download_models(
        output_dir=output_dir,
        force=False,
        progress=False,
        with_layout=True,
        with_tableformer=True,
        with_tableformer_v2=False,
        with_code_formula=False,
        with_picture_classifier=False,
        with_smolvlm=False,
        with_granitedocling=False,
        with_granitedocling_mlx=False,
        with_smoldocling=False,
        with_smoldocling_mlx=False,
        with_granite_vision=False,
        with_granite_chart_extraction=False,
        with_rapidocr=False,
        with_easyocr=False,
    )
    layout_repo_dir = model_root / LayoutOptions().model_spec.model_repo_folder
    tableformer_repo_dir = model_root / TableStructureModel._model_repo_folder
    if not layout_repo_dir.exists():
        raise RuntimeError(f"Docling Heron/Layout model not found in: {layout_repo_dir}")
    if not tableformer_repo_dir.exists():
        raise RuntimeError(f"Docling TableFormer model not found in: {tableformer_repo_dir}")
    return model_root


def ensure_docling_ready(
    *,
    parser_model: str,
    artifacts_path: str = "",
    auto_download: bool = True,
) -> None:
    """Validate Docling runtime setup before ingestion starts.

    This function performs a lightweight import check and, optionally, ensures
    the required models are present by triggering a download.

    Args:
        parser_model: Parser model identifier used for telemetry and validation.
        artifacts_path: Optional directory containing Docling artifacts.
        auto_download: Whether to automatically download missing artifacts.

    Raises:
        RuntimeError: If Docling is unavailable, configuration is invalid, or
            artifacts cannot be prepared.
    """
    if not str(parser_model).strip():
        raise RuntimeError("Docling parser model is empty")
    try:
        from docling.document_converter import DocumentConverter
    except Exception as exc:  # pragma: no cover - import path depends on runtime env
        raise RuntimeError(
            "Docling is required but not installed. Install with: uv add docling"
        ) from exc

    prepared_artifacts_path = artifacts_path
    if auto_download:
        model_root = warmup_docling_models(artifacts_path=artifacts_path)
        if not prepared_artifacts_path:
            prepared_artifacts_path = str(model_root)

    if prepared_artifacts_path:
        artifacts = Path(prepared_artifacts_path)
        if not artifacts.exists() or not artifacts.is_dir():
            raise RuntimeError(f"Docling artifacts path is invalid: {prepared_artifacts_path}")
        DocumentConverter(artifacts_path=str(artifacts))
        return
    DocumentConverter()


def _extract_headings_from_markdown(text: str) -> list[str]:
    """Extract heading text from markdown.

    Args:
        text: Markdown content.

    Returns:
        Heading text in appearance order.
    """
    headings: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip()
            if heading:
                headings.append(heading)
    return headings


def parse_with_docling(
    source_path: Path,
    *,
    parser_model: str,
    artifacts_path: str = "",
) -> DoclingParseResult:
    """Parse a source document into markdown using local Docling runtime.

    Args:
        source_path: Path to the source document to parse.
        parser_model: Parser model identifier used for telemetry/debugging.
        artifacts_path: Optional directory containing Docling artifacts.

    Returns:
        A normalized `DoclingParseResult`.

    Raises:
        RuntimeError: If Docling is unavailable, conversion fails, or the output
            is empty/unsupported.
    """
    try:
        # Import lazily to keep module import cheap and explicit.
        from docling.document_converter import DocumentConverter
    except Exception as exc:  # pragma: no cover - import path depends on runtime env
        raise RuntimeError(
            "Docling is required but not installed. Install with: uv add docling"
        ) from exc

    converter_kwargs: dict[str, Any] = {}
    if artifacts_path:
        converter_kwargs["artifacts_path"] = artifacts_path

    converter = DocumentConverter(**converter_kwargs)
    try:
        result = converter.convert(str(source_path))
    except Exception as exc:
        raise RuntimeError(
            f"Docling conversion failed for {source_path}: {exc}"
        ) from exc
    document = getattr(result, "document", None)
    if document is None:
        raise RuntimeError("Docling conversion did not return a document object")

    if not hasattr(document, "export_to_markdown"):
        raise RuntimeError("Docling document object does not support markdown export")
    markdown = str(document.export_to_markdown() or "").strip()
    if not markdown:
        raise RuntimeError("Docling returned empty markdown output")

    pictures = list(getattr(document, "pictures", []) or [])
    figures = [f"Figure {idx + 1}" for idx, _ in enumerate(pictures)]
    headings = _extract_headings_from_markdown(markdown)
    return DoclingParseResult(
        text_markdown=markdown,
        has_figures=bool(figures),
        figures=figures,
        headings=headings,
        parser_model=parser_model,
    )

