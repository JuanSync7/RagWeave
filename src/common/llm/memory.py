# @summary
# Session-based conversation history delegating to platform memory provider.
# Provides a thin wrapper over src.platform.memory (Redis-backed) for use
# within the LLM composition layer, with a lightweight in-memory fallback.
# Exports: conversation, ConversationSession
# Deps: src.common.llm.schemas, src.platform.memory.provider
# @end-summary
"""Session-based message history for LLM conversations.

Provides ``conversation()`` — a factory that returns a
``ConversationSession`` bound to a session ID.  Two backends:

* **redis** (default) — delegates to the platform's
  ``RedisConversationMemory``, sharing infrastructure with the rest of the
  project (TTL, multi-tenant scoping, LLM-driven summarization).
* **memory** — lightweight in-process store for tests and short-lived
  pipelines where Redis is unavailable.
"""

from __future__ import annotations

import logging
from typing import Literal

from src.common.llm.schemas import ConversationMessage, MessageRole

logger = logging.getLogger(__name__)

__all__ = ["conversation", "ConversationSession"]

_registry: dict[tuple[str, str], "ConversationSession"] = {}


class ConversationSession:
    """Unified conversation history interface.

    When *backend* is ``"redis"``, all operations delegate to the platform
    ``ConversationMemoryProvider``.  When ``"memory"``, messages are kept
    in a plain list (lost on process exit).
    """

    def __init__(
        self,
        session_id: str,
        backend: Literal["redis", "memory"],
        *,
        tenant_id: str = "default",
        subject: str = "system",
        project_id: str | None = None,
    ) -> None:
        self._session_id = session_id
        self._backend = backend
        self._tenant_id = tenant_id
        self._subject = subject
        self._project_id = project_id

        if backend == "redis":
            from src.platform.memory.provider import get_conversation_memory

            self._provider = get_conversation_memory()
            self._provider.ensure_conversation(
                tenant_id=tenant_id,
                subject=subject,
                project_id=project_id,
                conversation_id=session_id,
            )
        elif backend == "memory":
            self._messages: list[ConversationMessage] = []
        else:
            raise ValueError(f"Unknown backend: {backend!r}")

    # ── mutators ────────────────────────────────────────────────────────

    def add_user(self, content: str) -> None:
        """Append a user message."""
        self._add(MessageRole.USER, content)

    def add_assistant(self, content: str) -> None:
        """Append an assistant message."""
        self._add(MessageRole.ASSISTANT, content)

    def add_system(self, content: str) -> None:
        """Append a system message."""
        self._add(MessageRole.SYSTEM, content)

    def clear(self) -> None:
        """Wipe all messages for this session."""
        if self._backend == "redis":
            self._provider.delete_conversation(
                tenant_id=self._tenant_id,
                subject=self._subject,
                project_id=self._project_id,
                conversation_id=self._session_id,
            )
            # Re-create so the session remains usable
            self._provider.ensure_conversation(
                tenant_id=self._tenant_id,
                subject=self._subject,
                project_id=self._project_id,
                conversation_id=self._session_id,
            )
        else:
            self._messages.clear()

    # ── accessors ───────────────────────────────────────────────────────

    @property
    def messages(self) -> list[ConversationMessage]:
        """Return the full message history."""
        if self._backend == "redis":
            turns = self._provider.get_turns(
                tenant_id=self._tenant_id,
                subject=self._subject,
                project_id=self._project_id,
                conversation_id=self._session_id,
            )
            return [
                ConversationMessage(
                    role=MessageRole(t.role),
                    content=t.content,
                )
                for t in turns
            ]
        return list(self._messages)

    def to_dicts(self) -> list[dict[str, str]]:
        """Return messages as OpenAI-style ``{"role": ..., "content": ...}`` dicts."""
        return [{"role": m.role.value, "content": m.content} for m in self.messages]

    # ── internals ───────────────────────────────────────────────────────

    def _add(self, role: MessageRole, content: str) -> None:
        if self._backend == "redis":
            self._provider.append_turn(
                tenant_id=self._tenant_id,
                subject=self._subject,
                project_id=self._project_id,
                conversation_id=self._session_id,
                role=role.value,
                content=content,
            )
        else:
            self._messages.append(ConversationMessage(role=role, content=content))


def conversation(
    session_id: str,
    *,
    backend: Literal["redis", "memory"] = "redis",
    tenant_id: str = "default",
    subject: str = "system",
    project_id: str | None = None,
) -> ConversationSession:
    """Return the ``ConversationSession`` for *session_id*, creating on first call.

    Args:
        session_id: Unique session identifier.
        backend: ``"redis"`` (default) or ``"memory"``.
        tenant_id: Tenant scope for Redis multi-tenant isolation.
        subject: Subject scope (user or service identifier).
        project_id: Optional project scope.

    Returns:
        A ``ConversationSession`` instance (cached per session_id+backend).
    """
    key = (session_id, backend)
    if key not in _registry:
        _registry[key] = ConversationSession(
            session_id,
            backend,
            tenant_id=tenant_id,
            subject=subject,
            project_id=project_id,
        )
    return _registry[key]
