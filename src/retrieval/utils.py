# @summary
# Retrieval utility facade re-exporting deterministic helpers for stable imports.
# Exports: parse_json_object
# Deps: src.retrieval.common.utils
# @end-summary
"""Public retrieval utility facade."""

from src.retrieval.common.utils import parse_json_object

__all__ = ["parse_json_object"]
