# @summary
# Document formatting stage for structured context presentation and version conflict detection.
# Exports: format_context, FormattedContext, VersionConflict
# Deps: dataclasses, re, pathlib, src.retrieval.schemas.RankedResult
# @end-summary
"""Document formatting for the generation stage.

Transforms raw RankedResult objects into a structured context string with
metadata headers and version conflict detection. This stage sits between
reranking (stage 5) and generation (stage 6) in the RAG pipeline.

All functions are pure/deterministic — no I/O, no LLM calls.

Requirements references: REQ-501 (metadata attachment), REQ-502 (version
conflict detection), REQ-503 (deterministic formatting).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Dict, List, Optional


@dataclass
class VersionConflict:
    """A detected version conflict between retrieved documents.

    Occurs when chunks from the same document (identified by filename
    stem or spec_id) have different version values.
    """

    spec_stem: str
    versions: List[str]


@dataclass
class FormattedContext:
    """Result of the document formatting stage.

    Attributes:
        context_string: Fully formatted context ready for the LLM prompt.
        chunk_count: Number of chunks included.
        version_conflicts: Any version conflicts detected across chunks.
    """

    context_string: str
    chunk_count: int
    version_conflicts: List[VersionConflict] = field(default_factory=list)


def format_context(
    results: List[Any],
    include_scores: bool = True,
) -> FormattedContext:
    """Format ranked results into a structured context string.

    Each chunk is presented with a metadata header extracted from the
    RankedResult.metadata dict. Version conflicts are detected and
    prepended as a warning block.

    Args:
        results: List of RankedResult objects (must have .text, .score,
            .metadata attributes).
        include_scores: Whether to include relevance scores in headers.

    Returns:
        FormattedContext with the formatted string and conflict metadata.
    """
    if not results:
        return FormattedContext(context_string="", chunk_count=0)

    # Detect version conflicts first
    conflicts = _detect_version_conflicts(results)

    # Format each chunk
    formatted_chunks = []
    for i, result in enumerate(results):
        chunk_str = _format_chunk(i + 1, result, include_scores)
        formatted_chunks.append(chunk_str)

    # Build the final context string
    parts = []

    # Prepend version conflict warning if any
    if conflicts:
        warning_lines = ["--- VERSION CONFLICT WARNING ---"]
        for c in conflicts:
            versions_str = ", ".join(c.versions)
            warning_lines.append(
                f"Documents for \"{c.spec_stem}\" were retrieved in "
                f"versions [{versions_str}]. Information may be "
                f"inconsistent. Cite specific versions in your answer."
            )
        warning_lines.append("---")
        parts.append("\n".join(warning_lines))

    parts.append("\n\n".join(formatted_chunks))

    return FormattedContext(
        context_string="\n\n".join(parts),
        chunk_count=len(results),
        version_conflicts=conflicts,
    )


def _format_chunk(
    index: int,
    result: Any,
    include_scores: bool = True,
) -> str:
    """Format a single chunk with its metadata header.

    Args:
        index: 1-based chunk index.
        result: A RankedResult with .text, .score, .metadata.
        include_scores: Whether to include the relevance score.

    Returns:
        Formatted chunk string with metadata header.
    """
    meta = getattr(result, "metadata", {}) or {}
    score = getattr(result, "score", 0.0)
    text = getattr(result, "text", "")

    # Build metadata header parts
    header_parts = []
    if include_scores:
        header_parts.append(f"[{index}] (relevance: {score:.0%})")
    else:
        header_parts.append(f"[{index}]")

    meta_header = _extract_metadata_header(meta)
    if meta_header:
        header_parts.append(meta_header)

    header = " | ".join(header_parts)
    return f"{header}\n{text}"


def _extract_metadata_header(metadata: Dict[str, Any]) -> str:
    """Extract and format metadata fields into a compact header line.

    Handles missing fields gracefully — only includes fields that have
    non-empty values.

    Args:
        metadata: Metadata dict from a RankedResult.

    Returns:
        Formatted metadata string, or empty string if no metadata.
    """
    parts = []

    source = metadata.get("source") or metadata.get("filename")
    if source:
        parts.append(f"Source: {source}")

    version = metadata.get("source_version") or metadata.get("version")
    if version:
        parts.append(f"Version: {version}")

    date = metadata.get("date") or metadata.get("source_date")
    if date:
        parts.append(f"Date: {date}")

    section = (
        metadata.get("heading")
        or metadata.get("section_path")
        or metadata.get("section")
    )
    if section:
        parts.append(f"Section: {section}")

    domain = metadata.get("domain") or metadata.get("tags")
    if domain:
        if isinstance(domain, list):
            domain = ", ".join(str(d) for d in domain)
        parts.append(f"Domain: {domain}")

    return " | ".join(parts)


def _detect_version_conflicts(
    results: List[Any],
) -> List[VersionConflict]:
    """Detect version conflicts across retrieved documents.

    Groups chunks by document stem (from source_id or filename without
    extension) and checks for differing version values within each group.

    Args:
        results: List of RankedResult objects.

    Returns:
        List of VersionConflict objects for documents with conflicting
        versions. Empty list if no conflicts.
    """
    # Group versions by document stem
    stem_versions: Dict[str, set] = defaultdict(set)

    for result in results:
        meta = getattr(result, "metadata", {}) or {}

        # Determine the document stem (prefer spec_id, fallback to filename stem)
        spec_id = meta.get("source_id") or meta.get("spec_id")
        if spec_id:
            stem = str(spec_id)
        else:
            source = meta.get("source") or meta.get("filename") or ""
            if source:
                stem = PurePosixPath(source).stem
            else:
                continue

        version = meta.get("source_version") or meta.get("version")
        if version:
            stem_versions[stem].add(str(version))

    # Find stems with multiple versions
    conflicts = []
    for stem, versions in stem_versions.items():
        if len(versions) > 1:
            conflicts.append(
                VersionConflict(
                    spec_stem=stem,
                    versions=sorted(versions),
                )
            )

    return conflicts
