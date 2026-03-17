# @summary
# System routes for health and root metadata endpoints.
# Exports: create_system_router, build_health_response
# Deps: fastapi, temporalio, server.schemas, server.workflows
# @end-summary
"""System API routes."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Callable

from fastapi import APIRouter
from temporalio.api.enums.v1 import TaskQueueType
from temporalio.api.taskqueue.v1 import TaskQueue
from temporalio.api.workflowservice.v1 import DescribeTaskQueueRequest, GetSystemInfoRequest
from temporalio.client import Client  # pyright: ignore[reportMissingImports]

from server.schemas import ApiErrorResponse, HealthResponse, RootResponse
from server.workflows import RAG_QUERY_TASK_QUEUE


async def build_health_response(
    temporal_client: Client | None,
    logger: logging.Logger,
) -> HealthResponse:
    """Build health payload from Temporal connectivity and worker availability."""
    temporal_ok = False
    worker_ok = False
    if temporal_client is not None:
        try:
            # SDK-compatible connectivity check across Temporal client versions.
            check_health = getattr(temporal_client.service_client, "check_health", None)
            if check_health is not None:
                temporal_ok = bool(await check_health(timeout=timedelta(seconds=2)))
            else:
                await temporal_client.workflow_service.get_system_info(
                    GetSystemInfoRequest(),
                    timeout=timedelta(seconds=2),
                )
                temporal_ok = True
        except Exception:
            temporal_ok = False
        if temporal_ok:
            try:
                for queue_type in (
                    TaskQueueType.TASK_QUEUE_TYPE_WORKFLOW,
                    TaskQueueType.TASK_QUEUE_TYPE_ACTIVITY,
                ):
                    response = await temporal_client.workflow_service.describe_task_queue(
                        DescribeTaskQueueRequest(
                            namespace=temporal_client.namespace,
                            task_queue=TaskQueue(name=RAG_QUERY_TASK_QUEUE),
                            task_queue_type=queue_type,
                        ),
                        timeout=timedelta(seconds=2),
                    )
                    if response.pollers:
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


def create_system_router(
    *,
    get_temporal_client: Callable[[], Client | None],
    logger: logging.Logger,
) -> APIRouter:
    """Create router for health and root endpoints."""
    standard_error_responses = {
        401: {"model": ApiErrorResponse},
        403: {"model": ApiErrorResponse},
        404: {"model": ApiErrorResponse},
        422: {"model": ApiErrorResponse},
        429: {"model": ApiErrorResponse},
        500: {"model": ApiErrorResponse},
        503: {"model": ApiErrorResponse},
    }
    router = APIRouter()

    @router.get("/health", response_model=HealthResponse, responses=standard_error_responses)
    async def health():
        return await build_health_response(get_temporal_client(), logger)

    @router.get("/", response_model=RootResponse, responses=standard_error_responses)
    async def root():
        return RootResponse(
            service="RAG Query API",
            docs="/docs",
            health="/health",
            query_endpoint="POST /query",
        )

    return router


__all__ = ["create_system_router", "build_health_response"]
