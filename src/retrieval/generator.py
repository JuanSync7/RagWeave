# @summary
# LLM generator for RAG answer synthesis, backed by LiteLLM Router.
# Main exports: OllamaGenerator. Deps: typing, config.settings, src.platform.llm
# @end-summary
"""LLM generator for RAG answer synthesis, backed by LiteLLM Router."""

import logging
from typing import List, Optional

from config.settings import (
    GENERATION_MAX_TOKENS,
    GENERATION_TEMPERATURE,
)
from src.platform.llm import get_llm_provider
from src.platform.observability.providers import get_tracer


_SYSTEM_PROMPT = (
    "You are a helpful assistant that answers questions based on the provided context. "
    "Use ONLY the information from the context below to answer the question. "
    "If the context doesn't contain enough information to answer, say so clearly. "
    "Be concise and direct. "
    "IMPORTANT: Cite your sources using bracketed numbers like [1], [2], etc. "
    "that correspond to the context chunk numbers provided. "
    "Every claim should have at least one citation. "
    "Each context chunk has a relevance score (0-100%). "
    "Prioritize information from higher-scoring chunks. "
    "Treat chunks below 10% relevance with caution — they may not be directly relevant. "
    "Return only the final answer body in markdown (no wrapper sections). "
    "Do NOT include headings such as 'Output', 'Inputs', 'Outputs', "
    "'Comprehensive Overview', or 'Top reranked original documents'."
)

_USER_TEMPLATE = """Context:
{context}

Question: {question}

Answer:"""

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
        user_message = _USER_TEMPLATE.format(context=context, question=query)
        messages: list[dict] = [{"role": "system", "content": _SYSTEM_PROMPT}]
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
            span.end(status="ok")
            return response.content or None
        except Exception as e:
            logger.warning("LLM generation failed: %s", e)
            span.end(status="error", error=e)
            return None

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
