# @summary
# FastAPI server that accepts RAG queries over HTTP and dispatches them to
# Temporal workers where models are preloaded. No models loaded in this process.
# Exports: app
# Deps: fastapi, temporalio, server.schemas, server.workflows, config.settings
# @end-summary
"""FastAPI server — the HTTP frontend for the RAG system.

This process is lightweight: no GPU models, no torch imports. It accepts
HTTP requests, starts Temporal workflows, and returns results.

Usage:
    uvicorn server.api:app --host 0.0.0.0 --port 8000
"""

import asyncio
import json as json_mod
import logging
import os
import sys
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from temporalio.client import Client
from temporalio.service import RPCError

from config.settings import (
    TEMPORAL_TARGET_HOST,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    GENERATION_MAX_TOKENS,
    GENERATION_TEMPERATURE,
)
from src.platform.observability.providers import get_tracer
from server.schemas import QueryRequest, QueryResponse, HealthResponse
from server.workflows import RAGQueryWorkflow, RAG_QUERY_TASK_QUEUE

# Use uvicorn's logger/formatter so API logs match server output
# (INFO prefix + colorized level formatting).
logger = logging.getLogger("uvicorn.error").getChild("rag.server.api")

_temporal_client: Client | None = None
_obs_tracer = get_tracer()

API_PORT = int(os.environ.get("RAG_API_PORT", "8000"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _temporal_client
    logger.info("Connecting to Temporal at %s", TEMPORAL_TARGET_HOST)
    _temporal_client = await Client.connect(TEMPORAL_TARGET_HOST)
    logger.info("API server ready — queries route through Temporal to preloaded workers")
    try:
        yield
    finally:
        if _temporal_client is not None:
            await _temporal_client.close()
            _temporal_client = None
        logger.info("API server shutting down")


app = FastAPI(
    title="RAG Query API",
    description="Production RAG endpoint — models preloaded in Temporal workers, "
                "queries dispatched via durable workflows.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/query", response_model=QueryResponse)
async def query(request: QueryRequest):
    """Submit a RAG query.

    The query is dispatched as a Temporal workflow to a worker where embedding
    and reranker models are already loaded in GPU memory. Typical latency is
    100-500ms (inference only, no model loading).
    """
    if _temporal_client is None:
        raise HTTPException(status_code=503, detail="Temporal client not connected")

    workflow_id = f"rag-query-{uuid.uuid4().hex[:12]}"
    payload = request.model_dump(exclude_none=True)

    start = time.perf_counter()
    try:
        result = await _temporal_client.execute_workflow(
            RAGQueryWorkflow.run,
            payload,
            id=workflow_id,
            task_queue=RAG_QUERY_TASK_QUEUE,
        )
    except RPCError as exc:
        logger.error("Temporal RPC error: %s", exc)
        raise HTTPException(
            status_code=503,
            detail=f"Temporal unavailable: {exc}. Is the worker running?",
        )
    except Exception as exc:
        logger.error("Workflow execution failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    total_ms = (time.perf_counter() - start) * 1000

    result["workflow_id"] = workflow_id
    if "latency_ms" not in result:
        result["latency_ms"] = round(total_ms, 1)

    logger.info(
        "Query served in %.0fms (workflow %s): %s",
        total_ms,
        workflow_id,
        request.query[:60],
    )
    return QueryResponse(**result)


@app.post("/query/stream")
async def query_stream(request: QueryRequest):
    """Stream a RAG query response via Server-Sent Events.

    Retrieval (stages 1-5) runs through Temporal for durability.
    Generation (stage 6) streams directly from Ollama so the user
    sees tokens as they arrive instead of waiting for the full answer.

    SSE event types:
        retrieval  — metadata + retrieved chunks (no generated_answer)
        token      — a single generation token
        done       — final event with total latency
        error      — error message
    """
    if _temporal_client is None:
        raise HTTPException(status_code=503, detail="Temporal client not connected")

    workflow_id = f"rag-stream-{uuid.uuid4().hex[:12]}"
    payload = request.model_dump(exclude_none=True)
    payload["skip_generation"] = True

    async def event_generator():
        start = time.perf_counter()
        stream_error_message: str | None = None

        try:
            retrieval_result = await _temporal_client.execute_workflow(
                RAGQueryWorkflow.run,
                payload,
                id=workflow_id,
                task_queue=RAG_QUERY_TASK_QUEUE,
            )
        except RPCError as exc:
            stream_error_message = f"Retrieval failed: {exc}"
            yield _sse("error", {"message": stream_error_message})
            _emit_stream_observability_async(
                workflow_id=workflow_id,
                request=request,
                retrieval_ms=0.0,
                generation_ms=0.0,
                latency_ms=(time.perf_counter() - start) * 1000,
                token_count=0,
                stage_timings=[],
                timing_totals={"total_ms": 0.0},
                outcome="error",
                error_message=stream_error_message,
            )
            return
        except Exception as exc:
            stream_error_message = str(exc)
            yield _sse("error", {"message": stream_error_message})
            _emit_stream_observability_async(
                workflow_id=workflow_id,
                request=request,
                retrieval_ms=0.0,
                generation_ms=0.0,
                latency_ms=(time.perf_counter() - start) * 1000,
                token_count=0,
                stage_timings=[],
                timing_totals={"total_ms": 0.0},
                outcome="error",
                error_message=stream_error_message,
            )
            return

        retrieval_ms = (time.perf_counter() - start) * 1000
        retrieval_result["workflow_id"] = workflow_id
        retrieval_result["latency_ms"] = round(retrieval_ms, 1)
        retrieval_stages = list(retrieval_result.get("stage_timings", []))

        yield _sse("retrieval", retrieval_result)

        # Stream generation if we have results and action is "search"
        chunks = retrieval_result.get("results", [])
        processed_query = retrieval_result.get("processed_query", request.query)
        if retrieval_result.get("action") != "search" or not chunks:
            done_payload = {
                "latency_ms": round(retrieval_ms, 1),
                "retrieval_ms": round(retrieval_ms, 1),
                "generation_ms": 0.0,
                "token_count": 0,
                "stage_timings": retrieval_stages,
                "timing_totals": _aggregate_stage_totals(retrieval_stages),
            }
            yield _sse("done", done_payload)
            _emit_stream_observability_async(
                workflow_id=workflow_id,
                request=request,
                retrieval_ms=retrieval_ms,
                generation_ms=0.0,
                latency_ms=retrieval_ms,
                token_count=0,
                stage_timings=retrieval_stages,
                timing_totals=done_payload["timing_totals"],
                outcome="completed",
            )
            return

        context_texts = [c["text"] for c in chunks]
        scores = [c["score"] for c in chunks]

        gen_start = time.perf_counter()
        token_count = 0
        generation_stages: list[dict] = []

        try:
            for token in _stream_ollama(
                processed_query,
                context_texts,
                scores,
                stage_timings=generation_stages,
            ):
                token_count += 1
                yield _sse("token", {"token": token})
                # Yield control so FastAPI can flush
                await asyncio.sleep(0)
        except Exception as exc:
            logger.warning("Generation stream error: %s", exc)
            stream_error_message = str(exc)
            yield _sse("error", {"message": f"Generation error: {exc}"})

        gen_ms = (time.perf_counter() - gen_start) * 1000
        total_ms = (time.perf_counter() - start) * 1000

        logger.info(
            "Streamed %d tokens in %.0fms (retrieval: %.0fms, generation: %.0fms) — %s",
            token_count, total_ms, retrieval_ms, gen_ms, request.query[:60],
        )
        all_stages = retrieval_stages + generation_stages
        stage_totals = _aggregate_stage_totals(all_stages)
        done_payload = {
            "latency_ms": round(total_ms, 1),
            "retrieval_ms": round(retrieval_ms, 1),
            "generation_ms": round(gen_ms, 1),
            "token_count": token_count,
            "stage_timings": all_stages,
            "timing_totals": stage_totals,
        }
        yield _sse("done", done_payload)
        _emit_stream_observability_async(
            workflow_id=workflow_id,
            request=request,
            retrieval_ms=retrieval_ms,
            generation_ms=gen_ms,
            latency_ms=total_ms,
            token_count=token_count,
            stage_timings=all_stages,
            timing_totals=stage_totals,
            outcome="error" if stream_error_message else "completed",
            error_message=stream_error_message,
        )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _sse(event: str, data: dict) -> str:
    """Format a Server-Sent Event."""
    return f"event: {event}\ndata: {json_mod.dumps(data)}\n\n"


def _aggregate_stage_totals(stage_timings: list[dict]) -> dict:
    """Aggregate stage timings by pipeline bucket."""
    bucket_totals: dict[str, float] = {}
    for stage in stage_timings:
        bucket = str(stage.get("bucket", "other"))
        bucket_totals[bucket] = bucket_totals.get(bucket, 0.0) + float(stage.get("ms", 0.0))
    totals = {f"{bucket}_ms": round(ms, 1) for bucket, ms in bucket_totals.items()}
    totals["total_ms"] = round(sum(bucket_totals.values()), 1)
    return totals


def _emit_stream_observability_async(
    *,
    workflow_id: str,
    request: QueryRequest,
    retrieval_ms: float,
    generation_ms: float,
    latency_ms: float,
    token_count: int,
    stage_timings: list[dict],
    timing_totals: dict,
    outcome: str,
    error_message: str | None = None,
) -> None:
    """Emit stream observability in background to keep streaming latency stable."""

    async def _emit() -> None:
        def _sync_emit() -> None:
            span = _obs_tracer.start_span(
                "rag.api.stream",
                {
                    "workflow_id": workflow_id,
                    "query_length": len(request.query),
                    "search_limit": request.search_limit,
                    "rerank_top_k": request.rerank_top_k,
                    "alpha": request.alpha,
                    "outcome": outcome,
                },
            )
            try:
                span.set_attribute("latency_ms", round(latency_ms, 1))
                span.set_attribute("retrieval_ms", round(retrieval_ms, 1))
                span.set_attribute("generation_ms", round(generation_ms, 1))
                span.set_attribute("token_count", int(token_count))
                span.set_attribute("stage_timings", stage_timings)
                span.set_attribute("timing_totals", timing_totals)
                if request.source_filter:
                    span.set_attribute("source_filter", request.source_filter)
                if request.heading_filter:
                    span.set_attribute("heading_filter", request.heading_filter)
                if error_message:
                    span.set_attribute("error_message", error_message)
            finally:
                span.end(
                    status="ok" if outcome == "completed" else "error",
                    error=Exception(error_message) if error_message else None,
                )

        try:
            await asyncio.to_thread(_sync_emit)
        except Exception as exc:
            logger.debug("Background stream observability emit failed: %s", exc)

    asyncio.create_task(_emit())


def _stream_ollama(
    query: str,
    context_chunks: list[str],
    scores: list[float],
    stage_timings: list[dict] | None = None,
):
    """Stream tokens from Ollama. Lightweight — no GPU, just HTTP."""
    from urllib.request import Request, urlopen

    from src.retrieval.generator import _SYSTEM_PROMPT, _USER_TEMPLATE

    def _record_stage(stage: str, bucket: str, started_at: float) -> None:
        if stage_timings is None:
            return
        stage_timings.append(
            {"stage": stage, "bucket": bucket, "ms": round((time.perf_counter() - started_at) * 1000, 1)}
        )

    prep_start = time.perf_counter()
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

    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        "stream": True,
        "options": {
            "num_predict": GENERATION_MAX_TOKENS,
            "temperature": GENERATION_TEMPERATURE,
        },
    }

    req = Request(
        f"{OLLAMA_BASE_URL.rstrip('/')}/api/chat",
        data=json_mod.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    _record_stage("prompt_prepare", "generation", prep_start)
    resp = None
    stream_start = None
    try:
        connect_start = time.perf_counter()
        resp = urlopen(req, timeout=120)
        _record_stage("http_connect", "generation", connect_start)
        stream_start = time.perf_counter()
        for raw_line in resp:
            line = raw_line.decode("utf-8").strip()
            if not line:
                continue
            chunk = json_mod.loads(line)
            token = chunk.get("message", {}).get("content", "")
            if token:
                yield token
            if chunk.get("done"):
                break
    finally:
        if stream_start is not None:
            _record_stage("stream_tokens", "generation", stream_start)
        if resp is not None:
            resp.close()


@app.get("/health", response_model=HealthResponse)
async def health():
    """Check API and Temporal connectivity."""
    temporal_ok = False
    worker_ok = False

    if _temporal_client is not None:
        try:
            await _temporal_client.workflow_service.get_system_info()
            temporal_ok = True
        except Exception:
            pass

        if temporal_ok:
            try:
                from temporalio.client import WorkflowExecutionStatus
                async for _ in _temporal_client.list_workflows(
                    f'TaskQueue="{RAG_QUERY_TASK_QUEUE}" AND ExecutionStatus="Running"'
                ):
                    worker_ok = True
                    break
            except Exception as exc:
                worker_ok = False
                logger.warning("Worker availability check failed: %s", exc)

    status = "healthy" if (temporal_ok and worker_ok) else "degraded"
    return HealthResponse(
        status=status,
        temporal_connected=temporal_ok,
        worker_available=worker_ok,
    )


@app.get("/")
async def root():
    return {
        "service": "RAG Query API",
        "docs": "/docs",
        "health": "/health",
        "query_endpoint": "POST /query",
    }
