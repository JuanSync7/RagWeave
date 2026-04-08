# @summary
# Internal helpers for the LLM composition layer.
# Exports: build_messages, timed, safe_call
# Deps: time, logging, contextlib, src.common.utils
# @end-summary
"""Internal utilities for src.common.llm.

These helpers are shared across modules but NOT re-exported from
the package's public API.
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Any, Generator

from src.common.utils import parse_json_object  # noqa: F401 — re-export for internal use

logger = logging.getLogger(__name__)


def build_messages(
    prompt: str,
    *,
    system: str | None = None,
    history: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    """Build an OpenAI-style message list from simple inputs.

    Args:
        prompt: The user message content.
        system: Optional system message prepended to the list.
        history: Optional prior messages (already in dict format).

    Returns:
        List of ``{"role": ..., "content": ...}`` dicts.
    """
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": prompt})
    return messages


@contextmanager
def timed(label: str) -> Generator[dict[str, float], None, None]:
    """Context manager that records wall-clock elapsed time.

    Usage::

        with timed("retrieval") as t:
            do_work()
        print(t["elapsed"])  # seconds as float

    Args:
        label: Human-readable label for debug logging.

    Yields:
        A mutable dict; ``elapsed`` key is populated on exit.
    """
    result: dict[str, float] = {"elapsed": 0.0}
    start = time.monotonic()
    try:
        yield result
    finally:
        result["elapsed"] = time.monotonic() - start
        logger.debug("%s completed in %.3fs", label, result["elapsed"])


def safe_call(fn: Any, *args: Any, **kwargs: Any) -> tuple[Any, Exception | None]:
    """Call *fn* and return ``(result, None)`` or ``(None, exception)``.

    Never raises — useful for parallel / batch operations where partial
    failure is acceptable.
    """
    try:
        return fn(*args, **kwargs), None
    except Exception as exc:
        logger.warning("safe_call(%s) failed: %s", getattr(fn, "__name__", fn), exc)
        return None, exc
