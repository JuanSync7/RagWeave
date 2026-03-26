# @summary
# Generation sub-package schema contracts: document formatting results and version conflicts.
# Exports: FormattedContext, VersionConflict
# Deps: dataclasses, typing
# @end-summary
"""Generation stage schema contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


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
