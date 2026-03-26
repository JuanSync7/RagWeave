# @summary
# LLM generator for RAG answer synthesis, backed by LiteLLM Router.
# Main exports: OllamaGenerator, _get_system_prompt. Deps: typing, config.settings, src.platform.llm
# @end-summary
"""LLM generator for RAG answer synthesis, backed by LiteLLM Router."""

import logging
import re
from typing import List, Optional, Tuple

from config.settings import (
    GENERATION_MAX_TOKENS,
    GENERATION_TEMPERATURE,
    PROMPTS_DIR,
)
from src.platform.llm import get_llm_provider
from src.platform.observability.providers import get_tracer


def _load_system_prompt() -> str:
    """Load the RAG system prompt from an external file (REQ-601).

    Falls back to a minimal inline prompt if the file is missing,
    ensuring the pipeline never crashes due to a missing prompt file.
    """
    path = PROMPTS_DIR / "rag_system.md"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    logging.getLogger("rag.generator").warning(
        "System prompt file not found at %s — using minimal fallback", path
    )
    return (
        "You are a helpful assistant. Answer questions using ONLY the provided context. "
        "Cite sources using [1], [2], etc. If context is insufficient, say so."
    )


_SYSTEM_PROMPT: Optional[str] = None


def _get_system_prompt() -> str:
    """Return the system prompt, loading it from disk on first call."""
    global _SYSTEM_PROMPT
    if _SYSTEM_PROMPT is None:
        _SYSTEM_PROMPT = _load_system_prompt()
    return _SYSTEM_PROMPT


# Regex to extract the CONFIDENCE line from LLM responses
_CONFIDENCE_RE = re.compile(
    r"^CONFIDENCE:\s*(high|medium|low)\s*$",
    re.MULTILINE | re.IGNORECASE,
)

def _build_user_prompt(context: str, question: str) -> str:
    """Build user prompt via concatenation — safe against curly braces in documents.

    Using string concatenation instead of .format() prevents KeyError/IndexError
    when retrieved documents contain Python format specifiers like {variable},
    JSON examples, or template syntax (REQ-602).
    """
    return "Context:\n" + context + "\n\nQuestion: " + question + "\n\nAnswer:"

logger = logging.getLogger("rag.generator")


class OllamaGenerator:
    """Generate answers using LiteLLM Router (provider-agnostic).

    Retains the OllamaGenerator name for backward compatibility — callers
    continue to use the same class, but all HTTP calls now go through
    LLMProvider instead of raw urllib to Ollama's /api/chat.
    """

    def __init__(
        self,
        max_tokens: int = GENERATION_MAX_TOKENS,
        temperature: float = GENERATION_TEMPERATURE,
    ):
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.tracer = get_tracer()
        self._provider = get_llm_provider()
        # Expose model name for logging (matches old interface)
        self.model = self._provider.config.model
        # Last LLM response — populated after generate() for token tracking
        self._last_response = None
        # Last LLM self-reported confidence — read by rag_chain.py for composite scoring
        self._last_llm_confidence: str = "medium"

    def _build_messages(
        self,
        query: str,
        context_chunks: List[str],
        scores: Optional[List[float]] = None,
        memory_context: Optional[str] = None,
        recent_turns: Optional[List[dict]] = None,
    ) -> list[dict]:
        if scores:
            context = "\n\n".join(
                f"[{i+1}] (relevance: {score:.0%}) {chunk}"
                for i, (chunk, score) in enumerate(zip(context_chunks, scores))
            )
        else:
            context = "\n\n".join(
                f"[{i+1}] {chunk}" for i, chunk in enumerate(context_chunks)
            )
        user_message = _build_user_prompt(context, query)
        messages: list[dict] = [{"role": "system", "content": _get_system_prompt()}]
        if memory_context:
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "Use the conversation context below only as supporting context for follow-up intent.\n"
                        + memory_context
                    ),
                }
            )
        for turn in recent_turns or []:
            role = str(turn.get("role", "user"))
            if role not in {"user", "assistant", "system"}:
                continue
            content = str(turn.get("content", "")).strip()
            if not content:
                continue
            messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_message})
        return messages

    def generate(
        self,
        query: str,
        context_chunks: List[str],
        scores: Optional[List[float]] = None,
        memory_context: Optional[str] = None,
        recent_turns: Optional[List[dict]] = None,
    ) -> Optional[str]:
        """Generate an answer using retrieved context chunks.

        Args:
            query: The user's question.
            context_chunks: List of relevant text chunks from retrieval.
            scores: Optional reranker scores (0.0-1.0) for each chunk.

        Returns:
            Generated answer string, or None if generation fails.
        """
        if not context_chunks:
            return None
        span = self.tracer.start_span(
            "generator.generate",
            {
                "model": self.model,
                "context_chunk_count": len(context_chunks),
            },
        )

        messages = self._build_messages(
            query,
            context_chunks,
            scores,
            memory_context=memory_context,
            recent_turns=recent_turns,
        )

        try:
            response = self._provider.generate(
                messages,
                model_alias="default",
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            self._last_response = response
            raw_content = response.content or None
            if raw_content:
                answer, confidence = self._extract_confidence(raw_content)
                self._last_llm_confidence = confidence
                span.set_attribute("llm_confidence", confidence)
                span.end(status="ok")
                return answer
            span.end(status="ok")
            return None
        except Exception as e:
            logger.warning("LLM generation failed: %s", e)
            span.end(status="error", error=e)
            return None

    @staticmethod
    def _extract_confidence(response_text: str) -> Tuple[str, str]:
        """Extract and strip the CONFIDENCE line from an LLM response.

        The LLM is prompted to append "CONFIDENCE: high|medium|low" on
        a new line after its answer. This method extracts that line and
        returns the answer text without it.

        Args:
            response_text: Raw LLM response text.

        Returns:
            Tuple of (answer_text_without_confidence_line, confidence_level).
            Confidence defaults to "medium" if not parseable.
        """
        match = _CONFIDENCE_RE.search(response_text)
        if match:
            confidence = match.group(1).lower()
            # Strip the confidence line from the answer
            answer = _CONFIDENCE_RE.sub("", response_text).rstrip()
            return answer, confidence
        return response_text, "medium"

    def generate_stream(
        self,
        query: str,
        context_chunks: List[str],
        scores: Optional[List[float]] = None,
        memory_context: Optional[str] = None,
        recent_turns: Optional[List[dict]] = None,
    ):
        """Stream tokens from LLM. Yields content strings as they arrive.

        Same prompt as generate(), but uses streaming mode so callers
        can display tokens incrementally.
        """
        if not context_chunks:
            return

        messages = self._build_messages(
            query,
            context_chunks,
            scores,
            memory_context=memory_context,
            recent_turns=recent_turns,
        )

        try:
            for chunk in self._provider.generate_stream(
                messages,
                model_alias="default",
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            ):
                yield chunk
        except Exception as e:
            logger.warning("LLM streaming failed: %s", e)

    def is_available(self) -> bool:
        """Check if the LLM provider is reachable."""
        span = self.tracer.start_span(
            "generator.is_available",
            {"model": self.model},
        )
        try:
            available = self._provider.is_available(model_alias="default")
            span.end(status="ok")
            return available
        except Exception:
            span.end(status="error")
            return False
