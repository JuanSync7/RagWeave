# @summary
# Structured LLM output with automatic JSON repair.
# Exports: structured_output
# Deps: logging, pydantic, langchain_core, src.common.llm.provider,
#        src.common.llm.schemas, src.common.llm.utils
# @end-summary
"""Structured output extraction from LLM responses.

Provides ``structured_output()`` — invoke an LLM, parse the response into
a Pydantic model, and optionally auto-fix malformed JSON using a cheap
secondary model.
"""

from __future__ import annotations

import logging
from typing import Any, Type, TypeVar

from pydantic import BaseModel, ValidationError

from src.common.llm.provider import get_llm
from src.common.llm.schemas import OutputResult
from src.common.llm.utils import build_messages, parse_json_object

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


def structured_output(
    llm: Any,
    schema: Type[T],
    prompt: str,
    *,
    system: str | None = None,
    auto_fix: bool = True,
    fix_model_alias: str = "default",
) -> OutputResult:
    """Invoke *llm* and return a validated Pydantic object.

    Strategy:

    1. Try ``llm.with_structured_output(schema)`` (native tool-calling).
    2. If that fails or returns ``None``, invoke the LLM as plain text,
       extract JSON via ``parse_json_object``, and validate.
    3. If validation fails and *auto_fix* is enabled, send the raw output
       to a cheap fix model with instructions to repair the JSON.

    Args:
        llm: A LangChain ``BaseChatModel`` (typically from ``get_llm()``).
        schema: Pydantic model class to validate against.
        prompt: The user-facing prompt text.
        system: Optional system message.
        auto_fix: Whether to attempt automatic JSON repair on failure.
        fix_model_alias: Model alias passed to ``get_llm()`` for the
            fix model.  Defaults to ``"default"``.

    Returns:
        An ``OutputResult`` with the parsed object and metadata.

    Raises:
        ValidationError: If parsing fails and auto-fix is disabled or
            also fails.
    """
    messages = build_messages(prompt, system=system)
    model_name = getattr(llm, "model_alias", str(llm))

    # ── 1. Try native structured output ──────────────────────────────
    try:
        structured_llm = llm.with_structured_output(schema)
        parsed = structured_llm.invoke(messages)
        if parsed is not None:
            return OutputResult(
                parsed=parsed,
                raw="",
                auto_fixed=False,
                model_used=model_name,
            )
    except Exception:
        logger.debug("with_structured_output failed for %s, falling back", model_name)

    # ── 2. Plain invoke → extract JSON → validate ────────────────────
    raw_response = llm.invoke(messages)
    raw_text: str = raw_response.content if hasattr(raw_response, "content") else str(raw_response)

    try:
        data = parse_json_object(raw_text)
        parsed = schema.model_validate(data)
        return OutputResult(
            parsed=parsed,
            raw=raw_text,
            auto_fixed=False,
            model_used=model_name,
        )
    except (ValueError, ValidationError) as first_err:
        if not auto_fix:
            raise

    # ── 3. Auto-fix: ask a cheap model to repair the JSON ────────────
    logger.info("Auto-fixing structured output for schema %s", schema.__name__)

    fix_prompt = (
        "The following LLM output was supposed to be valid JSON matching "
        f"this schema:\n\n{schema.model_json_schema()}\n\n"
        f"Raw output:\n\n{raw_text}\n\n"
        "Return ONLY the corrected JSON object — no explanation, no markdown fences."
    )
    fix_llm = get_llm(fix_model_alias)
    fix_response = fix_llm.invoke(build_messages(fix_prompt))
    fix_text: str = fix_response.content if hasattr(fix_response, "content") else str(fix_response)

    data = parse_json_object(fix_text)
    parsed = schema.model_validate(data)
    return OutputResult(
        parsed=parsed,
        raw=raw_text,
        auto_fixed=True,
        model_used=model_name,
    )


__all__ = ["structured_output"]
