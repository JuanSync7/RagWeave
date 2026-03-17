# @summary
# Typed data structures for token budget tracking: ModelCapabilities,
# TokenBreakdown, TokenBudgetSnapshot.
# Exports: ModelCapabilities, TokenBreakdown, TokenBudgetSnapshot
# Deps: dataclasses
# @end-summary
"""Data structures for the token budget tracker."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelCapabilities:
    """Cached metadata about the active generation model."""

    model_name: str
    context_length: int
    family: str = ""
    parameter_size: str = ""
    quantization_level: str = ""
    stale: bool = False


@dataclass(frozen=True)
class TokenBreakdown:
    """Per-component token counts for the prompt."""

    system_prompt: int = 0
    memory_context: int = 0
    retrieval_chunks: int = 0
    user_query: int = 0
    template_overhead: int = 0

    def total(self) -> int:
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
