# @summary
# LLM helper for JSON-only chat calls used by ingestion nodes, backed by LiteLLM.
# Exports: _llm_json
# Deps: json, src.platform.llm, src.ingest.common.utils, src.ingest.common.types
# @end-summary

"""LLM helper utilities for ingestion pipeline."""

from __future__ import annotations

import json
import logging

from src.ingest.common.types import IngestionConfig
from src.ingest.common.utils import parse_json_object
from src.platform.llm import get_llm_provider

logger = logging.getLogger(__name__)


def _llm_json(
    prompt: str, config: IngestionConfig, max_tokens: int = 300
) -> dict[str, object]:
    """Execute a JSON-only LLM chat call via LiteLLM and parse the response.

    Returns parsed JSON dict, or empty dict on failure or when LLM is disabled.
    """
    if not config.enable_llm_metadata:
        return {}
    messages = [
        {"role": "system", "content": "Return JSON only."},
        {"role": "user", "content": prompt},
    ]
    try:
        provider = get_llm_provider()
        response = provider.json_completion(
            messages,
            temperature=config.llm_temperature,
            max_tokens=max_tokens,
        )
        return parse_json_object(response.content)
    except Exception:
        logger.debug("LLM JSON call failed, returning empty dict", exc_info=True)
        return {}


# Backward-compatible alias for callers still using the old name.
_ollama_json = _llm_json
