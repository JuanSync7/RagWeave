# @summary
# Server common package exports shared envelope schemas and request/response helpers.
# Exports: ApiErrorDetail, ApiErrorResponse, ConsoleEnvelope, request_id_from_request, error_payload, console_ok, console_err
# Deps: server.common.schemas, server.common.utils
# @end-summary
"""Common server schemas and helpers."""

from server.common.schemas import ApiErrorDetail, ApiErrorResponse, ConsoleEnvelope
from server.common.utils import console_err, console_ok, error_payload, request_id_from_request

__all__ = [
    "ApiErrorDetail",
    "ApiErrorResponse",
    "ConsoleEnvelope",
    "request_id_from_request",
    "error_payload",
    "console_ok",
    "console_err",
]

# --- Auto-generated re-exports (fix_encapsulation.py) ---
from server.common.utils import validate_optional_dependencies, validate_startup_config
