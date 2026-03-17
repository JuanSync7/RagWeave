# @summary
# Typed data structures for token budget tracking: ModelCapabilities,
# TokenBreakdown, TokenBudgetSnapshot.
# Exports: ModelCapabilities, TokenBreakdown, TokenBudgetSnapshot
# Deps: dataclasses
# @end-summary
"""Data structures for the token budget tracker.

These dataclasses provide a stable, JSON-friendly envelope for reporting
estimated and actual token usage to CLI/console surfaces.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelCapabilities:
    """Cached metadata about the active generation model.

    Attributes:
        model_name: Model identifier string.
        context_length: Maximum context window size (input + output), in tokens.
        family: Optional model family/provider label.
        parameter_size: Optional parameter size string.
        quantization_level: Optional quantization string.
        stale: Whether the values were derived from a fallback path.
    """

    model_name: str
    context_length: int
    family: str = ""
    parameter_size: str = ""
    quantization_level: str = ""
    stale: bool = False


@dataclass(frozen=True)
class TokenBreakdown:
    """Per-component token counts for the prompt.

    Attributes:
        system_prompt: Tokens attributed to the system prompt.
        memory_context: Tokens attributed to conversation memory context.
        retrieval_chunks: Tokens attributed to retrieved context chunks.
        user_query: Tokens attributed to the user query.
        template_overhead: Tokens attributed to prompt template overhead.
    """

    system_prompt: int = 0
    memory_context: int = 0
    retrieval_chunks: int = 0
    user_query: int = 0
    template_overhead: int = 0

    def total(self) -> int:
        """Return the total token estimate across all components.

        Returns:
            Sum of all breakdown components.
        """
        return (
            self.system_prompt
            + self.memory_context
            + self.retrieval_chunks
            + self.user_query
            + self.template_overhead
        )


@dataclass(frozen=True)
class TokenBudgetSnapshot:
    """Complete budget state for display in console and CLI.

    Carries both pre-generation *estimates* (input_tokens, breakdown) and
    optional post-generation *actuals* from the LLM response.

    Attributes:
        input_tokens: Estimated input token count (prompt + context).
        context_length: Model context window size in tokens.
        output_reservation: Reserved tokens for model output generation.
        usage_percent: Estimated percent of available input budget used.
        model_name: Model identifier string used for estimation/tokenization.
        breakdown: Optional component-level estimate.
        actual_prompt_tokens: Post-generation prompt token count from provider (if available).
        actual_completion_tokens: Post-generation completion token count (if available).
        actual_total_tokens: Post-generation total token count (if available).
        cost_usd: Post-generation cost estimate (if available).
    """

    input_tokens: int
    context_length: int
    output_reservation: int
    usage_percent: float
    model_name: str
    breakdown: TokenBreakdown | None = None

    # Post-generation actuals (populated after LLM call)
    actual_prompt_tokens: int = 0
    actual_completion_tokens: int = 0
    actual_total_tokens: int = 0
    cost_usd: float = 0.0


__all__ = ["ModelCapabilities", "TokenBreakdown", "TokenBudgetSnapshot"]
