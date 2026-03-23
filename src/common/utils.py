# @summary
# Cross-domain deterministic helpers shared by multiple src/* feature packages.
# Exports: parse_json_object, make_query_hash
# Deps: json, re, hashlib, typing
# @end-summary
"""Cross-domain deterministic utility helpers."""

from __future__ import annotations

import hashlib
import orjson
import re
from typing import Any


def parse_json_object(raw: str) -> dict[str, Any]:
    """Parse a JSON object from plain or fenced markdown text."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.IGNORECASE)
    try:
        payload = orjson.loads(cleaned)
    except orjson.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def make_query_hash(text: str, length: int = 16) -> str:
    """Return a short SHA-256 hex digest for logging/dedup purposes."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


__all__ = ["parse_json_object", "make_query_hash"]
