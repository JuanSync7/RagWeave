# @summary
# Cross-domain deterministic helpers shared by multiple src/* feature packages.
# Exports: parse_json_object, make_query_hash
# Deps: orjson, json, hashlib, typing
# @end-summary
"""Cross-domain deterministic utility helpers."""

from __future__ import annotations

import hashlib
import json
import orjson
from typing import Any

# Reusable decoder — raw_decode() parses JSON starting at a given index
# and returns (parsed_value, end_index). This is a C-implemented parser
# that correctly handles all JSON edge cases (string escaping, unicode,
# nested structures) in a single pass.
_JSON_DECODER = json.JSONDecoder()


def parse_json_object(raw: str) -> dict[str, Any]:
    """Parse a JSON object from LLM output that may contain surrounding text.

    Handles common LLM output formats:
    - Clean JSON: ``{"key": "value"}``
    - Markdown fenced: ``  ```json\\n{...}\\n```  ``
    - Prose wrapping: ``Here is the JSON:\\n{...}\\nLet me know``
    - Nested braces in values: ``{"code": "if (x) { return; }"}``

    Strategy:
    1. Try direct parse with orjson (fastest path for clean JSON).
    2. Strip markdown fences and try again.
    3. Find the first ``{`` and use ``json.JSONDecoder.raw_decode()``
       to parse from that position. This is a C-implemented full JSON
       parser — faster and more correct than manual brace scanning.
    4. Return ``{}`` if nothing works.

    Args:
        raw: Raw LLM response text potentially containing a JSON object.

    Returns:
        Parsed dict, or ``{}`` if no valid JSON object can be extracted.
    """
    if not raw or not raw.strip():
        return {}

    text = raw.strip()

    # 1. Try direct parse (fastest path for clean JSON)
    result = _try_parse_dict(text)
    if result is not None:
        return result

    # 2. Try stripping markdown fences
    defenced = _strip_markdown_fences(text)
    if defenced != text:
        result = _try_parse_dict(defenced)
        if result is not None:
            return result
        # Also try raw_decode on defenced content
        result = _raw_decode_first_object(defenced)
        if result is not None:
            return result

    # 3. Use json.JSONDecoder.raw_decode() from the first '{'
    #    This is a C-implemented parser that handles all JSON edge cases
    #    (string escaping, nested braces, unicode) in one pass.
    result = _raw_decode_first_object(text)
    if result is not None:
        return result

    return {}


def _try_parse_dict(text: str) -> dict[str, Any] | None:
    """Attempt to parse text as a JSON dict via orjson. Returns None on failure."""
    try:
        payload = orjson.loads(text)
    except (orjson.JSONDecodeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _raw_decode_first_object(text: str) -> dict[str, Any] | None:
    """Find and parse the first JSON object in text using raw_decode.

    Scans for the first ``{`` and uses the stdlib JSON decoder's
    ``raw_decode()`` method to parse from that position. This is
    implemented in C and handles all JSON string escaping, nested
    structures, and unicode correctly — no manual brace walking needed.

    Args:
        text: Text that may contain a JSON object somewhere within it.

    Returns:
        Parsed dict if a valid JSON object is found, None otherwise.
    """
    idx = text.find("{")
    if idx < 0:
        return None
    try:
        obj, _ = _JSON_DECODER.raw_decode(text, idx)
    except (json.JSONDecodeError, ValueError):
        return None
    return obj if isinstance(obj, dict) else None


def _strip_markdown_fences(text: str) -> str:
    """Remove markdown code fences from text.

    Looks for lines that are just ``` (optionally followed by a
    language tag like "json") and extracts the content between them.
    """
    lines = text.split("\n")
    fence_indices = []

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("```"):
            rest = stripped[3:].strip()
            # Opening fence: ``` or ```json or ```JSON etc.
            # Closing fence: ```
            if not rest or rest.isalpha():
                fence_indices.append(i)

    if len(fence_indices) >= 2:
        start = fence_indices[0]
        end = fence_indices[-1]
        if start < end:
            inner = "\n".join(lines[start + 1 : end])
            return inner.strip()

    return text


def make_query_hash(text: str, length: int = 16) -> str:
    """Return a short SHA-256 hex digest for logging/dedup purposes."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


__all__ = ["parse_json_object", "make_query_hash"]
