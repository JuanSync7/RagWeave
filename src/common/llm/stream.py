# @summary
# Unified event streaming with callbacks for LangChain Runnables and plain callables.
# Exports: stream, astream
# Deps: time, asyncio, typing, langchain_core.runnables, src.common.llm.schemas
# @end-summary
"""Unified event streaming with callbacks.

Provides ``stream()`` and ``astream()`` — thin wrappers that emit
``StreamFrame`` events via an optional callback while forwarding the
final result to the caller.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Optional

from langchain_core.runnables import Runnable

from src.common.llm.schemas import StreamEvent, StreamFrame

__all__ = ["stream", "astream"]

EventCallback = Optional[Callable[[StreamFrame], None]]


def _emit(
    cb: EventCallback,
    event: StreamEvent,
    data: Any,
    start: float,
    step_name: str | None = None,
) -> None:
    """Build a StreamFrame and invoke the callback (if provided)."""
    if cb is not None:
        frame = StreamFrame(
            event=event,
            data=data,
            step_name=step_name,
            elapsed_ms=(time.perf_counter() - start) * 1000,
        )
        cb(frame)


def stream(
    runnable_or_callable: Any,
    input: Any,  # noqa: A002
    *,
    on_event: EventCallback = None,
    step_name: str | None = None,
) -> Any:
    """Run *runnable_or_callable* and emit ``StreamFrame`` events via *on_event*.

    If the target is a LangChain ``Runnable``, tokens are streamed one by one.
    Otherwise the callable is invoked directly with STEP_START / STEP_END
    bookends.

    Returns the final result.
    """
    start = time.perf_counter()
    _emit(on_event, StreamEvent.STEP_START, None, start, step_name)

    if isinstance(runnable_or_callable, Runnable):
        chunks: list[Any] = []
        for chunk in runnable_or_callable.stream(input):
            chunks.append(chunk)
            _emit(on_event, StreamEvent.LLM_TOKEN, chunk, start, step_name)
        result = chunks[-1] if len(chunks) == 1 else sum(chunks[1:], chunks[0])
    else:
        result = runnable_or_callable(input)

    _emit(on_event, StreamEvent.STEP_END, result, start, step_name)
    return result


async def astream(
    runnable_or_callable: Any,
    input: Any,  # noqa: A002
    *,
    on_event: EventCallback = None,
    step_name: str | None = None,
) -> Any:
    """Async variant of :func:`stream`."""
    start = time.perf_counter()
    _emit(on_event, StreamEvent.STEP_START, None, start, step_name)

    if isinstance(runnable_or_callable, Runnable):
        chunks: list[Any] = []
        async for chunk in runnable_or_callable.astream(input):
            chunks.append(chunk)
            _emit(on_event, StreamEvent.LLM_TOKEN, chunk, start, step_name)
        result = chunks[-1] if len(chunks) == 1 else sum(chunks[1:], chunks[0])
    elif asyncio.iscoroutinefunction(runnable_or_callable):
        result = await runnable_or_callable(input)
    else:
        result = runnable_or_callable(input)

    _emit(on_event, StreamEvent.STEP_END, result, start, step_name)
    return result
