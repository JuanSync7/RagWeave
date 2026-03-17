"""Shared slash-command parsing and dispatch helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from src.platform.command_catalog import get_command_spec


@dataclass(frozen=True)
class ParsedSlashCommand:
    """Parsed slash command payload."""

    name: str
    arg: str


def parse_slash_command(raw: str) -> ParsedSlashCommand | None:
    """Parse `/name [arg]` syntax into structured fields."""

    text = raw.strip()
    if not text.startswith("/"):
        return None
    body = text[1:].strip()
    if not body:
        return ParsedSlashCommand(name="", arg="")
    parts = body.split(maxsplit=1)
    name = parts[0].strip().lower()
    arg = parts[1].strip() if len(parts) > 1 else ""
    return ParsedSlashCommand(name=name, arg=arg)


def dispatch_slash_command(
    *,
    raw: str,
    mode: str,
    handlers: dict[str, Callable[[str], None]],
    allow_admin: bool = False,
) -> tuple[bool, str | None]:
    """Dispatch a slash command to handlers with catalog validation.

    Returns `(handled, error_message)`:
    - handled=False means input was not a slash command.
    - handled=True and error_message=None means command executed.
    - handled=True and error_message set means slash command parse/validation failed.
    """

    parsed = parse_slash_command(raw)
    if parsed is None:
        return False, None
    if not parsed.name:
        return True, "EMPTY_COMMAND"

    allowed_spec = get_command_spec(
        mode,
        parsed.name,
        include_hidden=allow_admin,
        allow_admin=allow_admin,
    )
    if allowed_spec is None:
        # Differentiate unknown commands vs known-but-restricted commands.
        known_spec = get_command_spec(
            mode,
            parsed.name,
            include_hidden=True,
            allow_admin=True,
        )
        if known_spec is not None and known_spec.admin_only and not allow_admin:
            return True, "FORBIDDEN_COMMAND"
        return True, "UNKNOWN_COMMAND"

    handler = handlers.get(parsed.name)
    if handler is None:
        return True, "UNSUPPORTED_COMMAND"
    handler(parsed.arg)
    return True, None


__all__ = ["ParsedSlashCommand", "dispatch_slash_command", "parse_slash_command"]
