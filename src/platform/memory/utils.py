"""Utility helpers for memory trimming and context formatting."""

from __future__ import annotations

import re
import time

from src.platform.memory.schemas import ConversationTurn


def now_ms() -> int:
    return int(time.time() * 1000)


def sanitize_memory_text(text: str, max_chars: int = 1600) -> str:
    """Normalize whitespace and cap text length for prompt safety."""

    clean = re.sub(r"\s+", " ", (text or "")).strip()
    if len(clean) <= max_chars:
        return clean
    return clean[: max_chars - 3] + "..."


def estimate_token_count(text: str) -> int:
    """Cheap token estimate for budget checks."""

    if not text:
        return 0
    # Rough rule: ~4 chars per token for English-like text.
    return max(1, len(text) // 4)


def trim_turns_to_budget(
    turns: list[ConversationTurn],
    *,
    max_turns: int,
    max_tokens_estimate: int,
) -> list[ConversationTurn]:
    """Keep newest turns bounded by count and estimated token budget."""

    if not turns:
        return []
    limited = turns[-max(1, int(max_turns)) :]
    selected: list[ConversationTurn] = []
    total_tokens = 0
    for turn in reversed(limited):
        t = estimate_token_count(turn.content)
        if selected and (total_tokens + t) > max_tokens_estimate:
            break
        selected.append(turn)
        total_tokens += t
    selected.reverse()
    return selected


def build_context_text(summary_text: str, recent_turns: list[ConversationTurn]) -> str:
    """Compose canonical memory context block for prompt injection."""

    parts: list[str] = []
    if summary_text:
        parts.append("Conversation summary:\n" + sanitize_memory_text(summary_text, max_chars=2400))
    if recent_turns:
        rendered = []
        for turn in recent_turns:
            role = turn.role.upper()
            rendered.append(f"{role}: {sanitize_memory_text(turn.content, max_chars=1200)}")
        parts.append("Recent turns:\n" + "\n".join(rendered))
    return "\n\n".join(parts).strip()


def summarize_heuristic(turns: list[ConversationTurn], max_chars: int = 1800) -> str:
    """Fallback compact summary when LLM summarization is unavailable."""

    if not turns:
        return ""
    lines: list[str] = ["Key conversation points:"]
    for turn in turns[-12:]:
        prefix = "User" if turn.role == "user" else "Assistant"
        lines.append(f"- {prefix}: {sanitize_memory_text(turn.content, max_chars=220)}")
    return sanitize_memory_text("\n".join(lines), max_chars=max_chars)


__all__ = [
    "build_context_text",
    "estimate_token_count",
    "now_ms",
    "sanitize_memory_text",
    "summarize_heuristic",
    "trim_turns_to_budget",
]
