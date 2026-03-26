# @summary
# Output sanitization for generated answers: removes system prompt leakage,
# document boundary markers, and template artifacts.
# Exports: sanitize_answer
# Deps: logging
# @end-summary
"""Output sanitization for generated answers (REQ-704).

Uses structural detection rather than regex to identify and remove:
1. System prompt leakage — matches against the actual prompt text
2. Document boundary markers — matches the formatting patterns we use
3. Template variable artifacts — detects unreplaced placeholders

All functions are deterministic and side-effect-free.
"""

from __future__ import annotations

import logging
from typing import List, Optional

logger = logging.getLogger("rag.output_sanitizer")

# Document boundary markers used by the pipeline's formatting stages.
# If any of these appear in the generated answer, they are artifacts
# that leaked from the context into the output.
_BOUNDARY_MARKERS = [
    "--- Document ",
    "--- VERSION CONFLICT WARNING ---",
    "[CONTENT_FILTERED]",
]

# Template variable patterns — unreplaced placeholders
_TEMPLATE_ARTIFACTS = [
    "{context}",
    "{question}",
    "{documents}",
    "{query}",
]


def sanitize_answer(
    answer: str,
    system_prompt: Optional[str] = None,
) -> str:
    """Sanitize a generated answer by removing leaked internal artifacts.

    Uses the actual system prompt text (not regex) to detect leakage.
    This is more robust than pattern matching because it catches exact
    substrings of the real prompt regardless of how they're fragmented.

    Args:
        answer: Raw generated answer text.
        system_prompt: The system prompt used for generation. If provided,
            the sanitizer checks for leaked fragments.

    Returns:
        Sanitized answer with artifacts removed.
    """
    if not answer:
        return answer

    lines = answer.split("\n")
    cleaned_lines: List[str] = []

    for line in lines:
        stripped = line.strip()

        # Skip document boundary markers
        if _is_boundary_marker(stripped):
            logger.debug("Stripped boundary marker: %s", stripped[:60])
            continue

        # Skip template artifacts
        if _is_template_artifact(stripped):
            logger.debug("Stripped template artifact: %s", stripped[:60])
            continue

        # Skip system prompt fragments (if prompt provided)
        if system_prompt and _is_prompt_fragment(stripped, system_prompt):
            logger.debug("Stripped prompt fragment: %s", stripped[:60])
            continue

        cleaned_lines.append(line)

    result = "\n".join(cleaned_lines).strip()

    # If sanitization removed everything, return the original
    # (something is better than nothing)
    if not result:
        logger.warning("Sanitization removed all content — returning original")
        return answer

    return result


def _is_boundary_marker(line: str) -> bool:
    """Check if a line is a document boundary marker."""
    return any(marker in line for marker in _BOUNDARY_MARKERS)


def _is_template_artifact(line: str) -> bool:
    """Check if a line contains unreplaced template variables."""
    return any(artifact in line for artifact in _TEMPLATE_ARTIFACTS)


def _is_prompt_fragment(
    line: str,
    system_prompt: str,
    min_fragment_length: int = 40,
) -> bool:
    """Check if a line is a leaked fragment of the system prompt.

    Uses substring matching against the actual prompt text. Only flags
    lines that are substantial fragments (>= min_fragment_length chars)
    to avoid false positives on common phrases.

    Args:
        line: A single line from the answer.
        system_prompt: The full system prompt text.
        min_fragment_length: Minimum length to consider a match.

    Returns:
        True if the line appears to be a leaked prompt fragment.
    """
    if len(line) < min_fragment_length:
        return False
    # Normalize whitespace for comparison
    normalized_line = " ".join(line.lower().split())
    normalized_prompt = " ".join(system_prompt.lower().split())
    return normalized_line in normalized_prompt
