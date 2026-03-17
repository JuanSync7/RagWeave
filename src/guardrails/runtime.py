# @summary
# Singleton NeMo Guardrails runtime manager. Lazy-imports nemoguardrails
# to avoid import errors when disabled. Initializes once at worker startup.
# Exports: GuardrailsRuntime
# Deps: config.settings, logging
# @end-summary
"""NeMo Guardrails runtime lifecycle manager."""

from __future__ import annotations

import logging
from typing import Optional

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

    @classmethod
    def get(cls) -> GuardrailsRuntime:
        """Get the singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def is_enabled(cls) -> bool:
        """Check if NeMo Guardrails is enabled and not auto-disabled."""
        from config.settings import RAG_NEMO_ENABLED

        return RAG_NEMO_ENABLED and not cls._auto_disabled

    def initialize(self, config_dir: str) -> None:
        """Load NeMo config and compile Colang flows.

        Raises on Colang parse errors (fail-fast at startup).
        Catches other errors and auto-disables NeMo (REQ-902).
        """
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
            self._auto_disabled = True

    @property
    def rails(self):
        """Access the LLMRails instance. Returns None if not initialized."""
        return self._rails

    @property
    def initialized(self) -> bool:
        """Whether the runtime has been successfully initialized."""
        return self._initialized

    async def generate_async(self, messages: list[dict]) -> dict:
        """Execute rails on a message sequence.

        Returns empty response on failure (fail-safe).
        """
        if not self._initialized or self._rails is None:
            return {"role": "assistant", "content": ""}
        try:
            return await self._rails.generate_async(messages=messages)
        except Exception as e:
            logger.warning(
                "Rail execution failed: %s — auto-disabling guardrails", e
            )
            self._auto_disabled = True
            return {"role": "assistant", "content": ""}

    def shutdown(self) -> None:
        """Release runtime resources."""
        self._rails = None
        self._initialized = False
        logger.info("NeMo Guardrails runtime shut down")

    @classmethod
    def reset(cls) -> None:
        """Reset singleton state (for testing)."""
        if cls._instance is not None:
            cls._instance.shutdown()
        cls._instance = None
        cls._auto_disabled = False
