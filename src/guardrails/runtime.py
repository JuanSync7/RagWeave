# @summary
# Singleton NeMo Guardrails runtime manager. Lazy-imports nemoguardrails
# to avoid import errors when disabled. Initializes once at worker startup.
# Exports: GuardrailsRuntime
# Deps: config.settings, logging
# @end-summary
"""NeMo Guardrails runtime lifecycle manager."""

from __future__ import annotations

import logging
import threading
from typing import Any, Optional

logger = logging.getLogger("rag.guardrails.runtime")


class GuardrailsRuntime:
    """Singleton manager for the NeMo Guardrails runtime.

    Lazy-imports nemoguardrails to avoid import errors when
    RAG_NEMO_ENABLED=false and the package is not installed (REQ-907).
    """

    _instance: Optional[GuardrailsRuntime] = None
    _initialized: bool = False
    _rails = None  # LLMRails instance
    _auto_disabled: bool = False
    _lock: threading.Lock = threading.Lock()

    @classmethod
    def get(cls) -> GuardrailsRuntime:
        """Return the process-wide singleton runtime instance.

        Returns:
            The singleton `GuardrailsRuntime` instance.
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def is_enabled(cls) -> bool:
        """Return whether guardrails are enabled and not auto-disabled.

        This reflects both configuration (`RAG_NEMO_ENABLED`) and whether the
        runtime has been auto-disabled due to a prior initialization/execution
        failure.

        Returns:
            True if guardrails should be considered active for this process.
        """
        from config.settings import RAG_NEMO_ENABLED

        return RAG_NEMO_ENABLED and not cls._auto_disabled

    def initialize(self, config_dir: str) -> None:
        """Load NeMo config and compile Colang flows.

        This method is idempotent and safe to call multiple times. It fails fast
        on Colang syntax errors (to surface configuration issues early), and
        fails open on other runtime errors by auto-disabling guardrails.

        Args:
            config_dir: Directory containing NeMo Guardrails configuration.

        Raises:
            SyntaxError: If Colang parsing fails (fail-fast at startup).
        """
        with type(self)._lock:
            if self._initialized:
                return
            if not self.is_enabled():
                logger.info("NeMo Guardrails disabled (RAG_NEMO_ENABLED=false)")
                return

            try:
                from nemoguardrails import LLMRails, RailsConfig

                logger.info("Initializing NeMo Guardrails from %s...", config_dir)
                config = RailsConfig.from_path(config_dir)
                self._rails = LLMRails(config)
                self._initialized = True
                logger.info("NeMo Guardrails runtime initialized successfully")
            except SyntaxError as e:
                logger.error("Colang parse error in %s: %s", config_dir, e)
                raise
            except Exception as e:
                logger.error(
                    "NeMo Guardrails init failed: %s — auto-disabling guardrails", e
                )
                type(self)._auto_disabled = True

    @property
    def rails(self) -> Any | None:
        """Return the underlying `LLMRails` instance, if initialized.

        Returns:
            The compiled `LLMRails` instance, or None if not initialized.
        """
        return self._rails

    @property
    def initialized(self) -> bool:
        """Return whether the runtime has been successfully initialized.

        Returns:
            True if `initialize()` completed successfully.
        """
        return self._initialized

    async def generate_async(self, messages: list[dict]) -> dict:
        """Execute rails on a message sequence.

        This is a fail-open integration point: if rails are unavailable or an
        execution error occurs, an empty assistant message is returned and the
        runtime is auto-disabled for subsequent requests.

        Args:
            messages: Chat message list in OpenAI-compatible dict format.

        Returns:
            Assistant message dict produced by rails, or an empty assistant
            message if guardrails are disabled/unavailable.
        """
        if not self._initialized or self._rails is None:
            return {"role": "assistant", "content": ""}
        try:
            return await self._rails.generate_async(messages=messages)
        except Exception as e:
            logger.warning(
                "Rail execution failed: %s — auto-disabling guardrails", e
            )
            type(self)._auto_disabled = True
            return {"role": "assistant", "content": ""}

    def register_actions(self, actions: dict[str, callable]) -> None:
        """Register custom Python actions with the NeMo runtime.

        Actions registered here are available to Colang flows via
        ``await action_name(...)`` syntax.

        Args:
            actions: Dict mapping action names to async callables.
        """
        if self._rails is None:
            logger.warning("Cannot register actions — runtime not initialized")
            return
        for name, fn in actions.items():
            self._rails.register_action(fn, name=name)
            logger.info("Registered custom action: %s", name)

    def shutdown(self) -> None:
        """Release runtime resources and mark the runtime uninitialized."""
        self._rails = None
        self._initialized = False
        logger.info("NeMo Guardrails runtime shut down")

    @classmethod
    def reset(cls) -> None:
        """Reset singleton state (primarily for testing)."""
        with cls._lock:
            if cls._instance is not None:
                cls._instance.shutdown()
            cls._instance = None
            cls._auto_disabled = False
