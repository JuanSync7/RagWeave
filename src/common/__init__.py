# @summary
# Public facade for cross-domain shared helpers in src/common.
# Exports: parse_json_object
# Deps: src.common.utils
# @end-summary
"""Cross-domain shared helpers facade."""

from src.common.utils import parse_json_object

__all__ = ["parse_json_object"]

# --- Auto-generated re-exports (fix_encapsulation.py) ---
from src.common.utils import make_query_hash
