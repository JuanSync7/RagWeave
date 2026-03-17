# @summary
# Shared server helper functions for request id extraction and error/console envelopes.
# Exports: request_id_from_request, error_payload, console_ok, console_err
# Deps: fastapi, server.common.schemas
# @end-summary
"""Server-common utility helpers."""

from __future__ import annotations

from fastapi import Request

from server.common.schemas import ApiErrorDetail, ApiErrorResponse, ConsoleEnvelope


def request_id_from_request(request: Request) -> str | None:
    """Extract request id from request state, if present."""

    return getattr(request.state, "request_id", None)


def error_payload(
    request: Request,
    *,
    code: str,
    message: str,
    details: dict | None = None,
) -> dict:
    """Build normalized API error payload."""

    return ApiErrorResponse(
        ok=False,
        error=ApiErrorDetail(code=code, message=message, details=details),
        request_id=request_id_from_request(request),
    ).model_dump()


def console_ok(request: Request, data: dict) -> ConsoleEnvelope:
    """Build success envelope payload for console endpoints."""

    return ConsoleEnvelope(ok=True, request_id=request_id_from_request(request), data=data)


def console_err(
    request: Request,
    *,
    code: str,
    message: str,
    details: dict | None = None,
) -> ConsoleEnvelope:
    """Build error envelope payload for console endpoints."""

    return ConsoleEnvelope(
        ok=False,
        request_id=request_id_from_request(request),
        error=ApiErrorDetail(code=code, message=message, details=details),
    )
