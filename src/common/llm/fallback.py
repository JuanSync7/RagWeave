# @summary
# Strategy-level failover for LLM pipelines.
# Provides fallback_chain (sync) and afallback_chain (async) combinators
# that try strategies in order and return FallbackResult on first success.
# Exports: fallback_chain, afallback_chain
# Deps: src.common.llm.schemas.FallbackResult
# @end-summary
"""Strategy-level failover combinators.

NOT model-level retry (that is LiteLLM's job).  These combinators accept
an ordered sequence of *strategy callables* and return a single callable
that tries each strategy until one succeeds.
"""

from __future__ import annotations

from typing import Any, Callable

from src.common.llm.schemas import FallbackResult

__all__ = ["fallback_chain", "afallback_chain"]


def fallback_chain(
    *strategies: Callable[..., Any],
) -> Callable[..., FallbackResult]:
    """Return a callable that tries each *strategy* in order.

    The first strategy that returns without raising wins.  If every
    strategy raises, the **last** exception is re-raised.

    Returns:
        A callable ``(*args, **kwargs) -> FallbackResult``.
    """

    def _run(*args: Any, **kwargs: Any) -> FallbackResult:
        last_exc: BaseException | None = None
        for idx, strategy in enumerate(strategies):
            try:
                result = strategy(*args, **kwargs)
                return FallbackResult(
                    result=result,
                    strategy_used=idx,
                    strategies_tried=idx + 1,
                )
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
        raise last_exc  # type: ignore[misc]

    return _run


def afallback_chain(
    *strategies: Callable[..., Any],
) -> Callable[..., Any]:
    """Async version of :func:`fallback_chain`.

    Each strategy is ``await``-ed in order.  Semantics are otherwise
    identical to the synchronous variant.
    """

    async def _run(*args: Any, **kwargs: Any) -> FallbackResult:
        last_exc: BaseException | None = None
        for idx, strategy in enumerate(strategies):
            try:
                result = await strategy(*args, **kwargs)
                return FallbackResult(
                    result=result,
                    strategy_used=idx,
                    strategies_tried=idx + 1,
                )
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
        raise last_exc  # type: ignore[misc]

    return _run
