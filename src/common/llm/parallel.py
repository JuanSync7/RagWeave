# @summary
# Generic fan-out/fan-in execution wrapper for named concurrent tasks.
# Exports: parallel, aparallel
# Deps: concurrent.futures, asyncio, time, logging,
#        langchain_core.runnables, src.common.llm.schemas, src.common.llm.utils
# @end-summary
"""Parallel execution helpers for the LLM composition layer.

Provides ``parallel()`` and ``aparallel()`` — generic fan-out/fan-in
wrappers that accept named callables (or LangChain Runnables), execute
them concurrently, and return a :class:`ParallelResult` with per-task
results, timings, and errors.

Strategy selection is automatic:
* If **all** tasks are plain callables → ``ThreadPoolExecutor``
* If **any** task is a LangChain ``Runnable`` → ``RunnableParallel``
"""

from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

from src.common.llm.schemas import ParallelResult
from src.common.llm.utils import safe_call, timed

logger = logging.getLogger(__name__)


def _is_runnable(obj: Any) -> bool:
    """Return True if *obj* is a LangChain Runnable."""
    try:
        from langchain_core.runnables import Runnable

        return isinstance(obj, Runnable)
    except ImportError:
        return False


# ── Thread-pool path (plain callables) ──────────────────────────────────


def _run_threaded(**tasks: Callable[..., Any]) -> ParallelResult:
    """Execute plain callables via ``ThreadPoolExecutor``."""
    results: dict[str, Any] = {}
    timings: dict[str, float] = {}
    errors: dict[str, Exception] = {}

    with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
        future_to_name = {
            pool.submit(_timed_safe_call, name, fn): name
            for name, fn in tasks.items()
        }
        for future in as_completed(future_to_name):
            name = future_to_name[future]
            value, elapsed, exc = future.result()
            timings[name] = elapsed
            if exc is not None:
                errors[name] = exc
            else:
                results[name] = value

    return ParallelResult(results=results, timings=timings, errors=errors)


def _timed_safe_call(
    name: str, fn: Callable[..., Any]
) -> tuple[Any, float, Exception | None]:
    """Call *fn* while measuring wall-clock time; never raises."""
    start = time.monotonic()
    value, exc = safe_call(fn)
    elapsed = time.monotonic() - start
    return value, elapsed, exc


# ── RunnableParallel path (LangChain) ──────────────────────────────────


def _run_langchain(**tasks: Any) -> ParallelResult:
    """Execute tasks via ``RunnableParallel`` when any task is a Runnable."""
    from langchain_core.runnables import Runnable, RunnableParallel, RunnableLambda

    results: dict[str, Any] = {}
    timings: dict[str, float] = {}
    errors: dict[str, Exception] = {}

    # Wrap plain callables as RunnableLambda so RunnableParallel accepts them.
    # Also wrap each task to capture timing and errors.
    wrapped: dict[str, Runnable] = {}
    for name, task in tasks.items():
        if isinstance(task, Runnable):
            wrapped[name] = RunnableLambda(
                lambda _input, _n=name, _t=task: _invoke_and_record(
                    _n, _t.invoke, timings, errors
                )
            )
        else:
            wrapped[name] = RunnableLambda(
                lambda _input, _n=name, _t=task: _invoke_and_record(
                    _n, _t, timings, errors
                )
            )

    rp = RunnableParallel(**wrapped)

    try:
        raw = rp.invoke({})
    except Exception:
        # If the orchestrator itself fails, individual errors were already
        # captured inside _invoke_and_record; raw may be incomplete.
        raw = {}

    for name, value in raw.items():
        if name not in errors:
            results[name] = value

    return ParallelResult(results=results, timings=timings, errors=errors)


def _invoke_and_record(
    name: str,
    fn: Callable[..., Any],
    timings: dict[str, float],
    errors: dict[str, Exception],
) -> Any:
    """Invoke *fn*, record timing, and capture errors without propagating."""
    start = time.monotonic()
    try:
        result = fn()
        return result
    except Exception as exc:
        logger.warning("parallel task %r failed: %s", name, exc)
        errors[name] = exc
        return None
    finally:
        timings[name] = time.monotonic() - start


# ── Public sync interface ───────────────────────────────────────────────


def parallel(**tasks: Callable[..., Any] | Any) -> ParallelResult:
    """Run named tasks concurrently and collect results.

    Accepts a mix of plain callables and LangChain ``Runnable`` objects.
    The execution backend is chosen automatically:

    * All plain callables → ``ThreadPoolExecutor``
    * Any ``Runnable`` present → ``RunnableParallel``

    Args:
        **tasks: Named callables or Runnables to execute.

    Returns:
        A :class:`ParallelResult` with ``results``, ``timings``, and
        ``errors`` dicts keyed by task name.

    Example::

        result = parallel(
            vectors=lambda: search_weaviate(query),
            keywords=lambda: search_bm25(query),
        )
        result.results["vectors"]   # search output
        result.timings["vectors"]   # wall-clock seconds
        result.errors               # empty dict if all OK
    """
    if not tasks:
        return ParallelResult()

    has_runnable = any(_is_runnable(t) for t in tasks.values())

    with timed("parallel") as t:
        if has_runnable:
            out = _run_langchain(**tasks)
        else:
            out = _run_threaded(**tasks)

    logger.debug(
        "parallel: %d tasks, %d succeeded, %d failed (%.3fs total)",
        len(tasks),
        len(out.results),
        len(out.errors),
        t["elapsed"],
    )
    return out


# ── Public async interface ──────────────────────────────────────────────


async def aparallel(**tasks: Callable[..., Any] | Any) -> ParallelResult:
    """Async variant of :func:`parallel` using ``asyncio.gather``.

    Each task is executed as a coroutine if it is already async, or
    wrapped in ``asyncio.to_thread`` if synchronous.

    Args:
        **tasks: Named callables (sync or async) to execute.

    Returns:
        A :class:`ParallelResult` with ``results``, ``timings``, and
        ``errors`` dicts keyed by task name.
    """
    if not tasks:
        return ParallelResult()

    results: dict[str, Any] = {}
    timings: dict[str, float] = {}
    errors: dict[str, Exception] = {}

    async def _run_one(name: str, fn: Callable[..., Any]) -> None:
        start = time.monotonic()
        try:
            if asyncio.iscoroutinefunction(fn):
                value = await fn()
            else:
                value = await asyncio.to_thread(fn)
            results[name] = value
        except Exception as exc:
            logger.warning("aparallel task %r failed: %s", name, exc)
            errors[name] = exc
        finally:
            timings[name] = time.monotonic() - start

    await asyncio.gather(*(_run_one(name, fn) for name, fn in tasks.items()))

    logger.debug(
        "aparallel: %d tasks, %d succeeded, %d failed",
        len(tasks),
        len(results),
        len(errors),
    )
    return ParallelResult(results=results, timings=timings, errors=errors)


__all__ = [
    "parallel",
    "aparallel",
]
