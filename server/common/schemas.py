# @summary
# Shared server envelope schemas used across API handlers and exception responses.
# Exports: ApiErrorDetail, ApiErrorResponse, ConsoleEnvelope
# Deps: pydantic
# @end-summary
"""Common server API envelope schemas."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class ApiErrorDetail(BaseModel):
    """Structured error detail payload."""

    code: str
    message: str
    details: Optional[dict] = None


class ApiErrorResponse(BaseModel):
    """Standardized API error envelope for non-2xx responses."""

    ok: bool = False
    error: ApiErrorDetail
    request_id: Optional[str] = None


class ConsoleEnvelope(BaseModel):
    """Standardized envelope used by console-specific endpoints."""

    ok: bool
    request_id: Optional[str] = None
    data: Optional[dict] = None
    error: Optional[ApiErrorDetail] = None
