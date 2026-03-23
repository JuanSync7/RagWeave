# @summary
# MCP adapter that exposes RAG API query/health as MCP tools.
# Exports: mcp
# @end-summary

"""MCP adapter for the RAG API.

This server is intentionally thin: it forwards tool calls to the existing
FastAPI endpoints so the HTTP API remains the single production contract.
"""

from __future__ import annotations

import orjson
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from mcp.server.fastmcp import FastMCP

from config.settings import RAG_API_URL
from server.schemas import (
    ApiKeyRecord,
    CreateApiKeyRequest,
    CreateApiKeyResponse,
    HealthResponse,
    QueryRequest,
    QueryResponse,
    QuotaSetResponse,
    QuotasResponse,
    QuotaUpdateRequest,
    StatusResponse,
)

_DEFAULT_TIMEOUT_SECONDS = int(os.environ.get("RAG_MCP_TIMEOUT_SECONDS", "90"))
_MCP_API_KEY = os.environ.get("RAG_MCP_API_KEY", "").strip()
_MCP_BEARER_TOKEN = os.environ.get("RAG_MCP_BEARER_TOKEN", "").strip()
_ADMIN_TOOLS_ENV = "RAG_MCP_ENABLE_ADMIN_TOOLS"

mcp = FastMCP(
    name="rag-api-adapter",
    instructions=(
        "Use this server to query and inspect the RAG backend via its stable HTTP API."
    ),
)


def _build_headers() -> dict[str, str]:
    """Build outbound API headers from MCP adapter environment variables."""
    headers = {"Content-Type": "application/json"}
    if _MCP_API_KEY:
        headers["x-api-key"] = _MCP_API_KEY
    if _MCP_BEARER_TOKEN:
        headers["Authorization"] = f"Bearer {_MCP_BEARER_TOKEN}"
    return headers


def _env_true(name: str) -> bool:
    """Return True when env var is set to a truthy value."""
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _require_admin_tools_enabled() -> None:
    """Guard dangerous admin tools behind explicit opt-in."""
    if _env_true(_ADMIN_TOOLS_ENV):
        return
    raise RuntimeError(
        "Admin MCP tools are disabled. Set RAG_MCP_ENABLE_ADMIN_TOOLS=1 to enable."
    )


def _parse_error_payload(status_code: int, body_text: str) -> str:
    """Extract a readable error message from the API error envelope."""
    try:
        payload = orjson.loads(body_text)
    except orjson.JSONDecodeError:
        return f"HTTP {status_code}: {body_text}"
    if isinstance(payload, dict):
        error = payload.get("error", {})
        message = error.get("message") if isinstance(error, dict) else None
        code = error.get("code") if isinstance(error, dict) else None
        if message and code:
            return f"{code}: {message}"
        if message:
            return str(message)
        detail = payload.get("detail")
        if detail:
            return str(detail)
    return f"HTTP {status_code}: {body_text}"


def _request_json(
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
) -> Any:
    """Execute an HTTP request against the RAG API and return parsed JSON."""
    base_url = os.environ.get("RAG_API_URL", RAG_API_URL).rstrip("/")
    body = None
    if payload is not None:
        body = orjson.dumps(payload)
    req = Request(
        f"{base_url}{path}",
        data=body,
        headers=_build_headers(),
        method=method,
    )
    try:
        with urlopen(req, timeout=timeout_seconds) as resp:
            raw = resp.read().decode("utf-8")
            if not raw.strip():
                return {}
            return orjson.loads(raw)
    except HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(_parse_error_payload(exc.code, body_text)) from exc
    except URLError as exc:
        raise RuntimeError(f"RAG API unavailable: {exc}") from exc


@mcp.tool(description="Check RAG API and Temporal worker health.")
def health() -> dict[str, Any]:
    """Return health state from the backend API."""
    payload = _request_json("GET", "/health")
    return HealthResponse(**payload).model_dump()


@mcp.tool(description="Run a RAG query through the production API.")
def query(
    query: str,
    source_filter: str | None = None,
    heading_filter: str | None = None,
    alpha: float = 0.5,
    search_limit: int = 10,
    rerank_top_k: int = 5,
    tenant_id: str | None = None,
    max_query_iterations: int | None = None,
    fast_path: bool | None = None,
    overall_timeout_ms: int | None = None,
    stage_budget_overrides: dict[str, int] | None = None,
    conversation_id: str | None = None,
    memory_enabled: bool = True,
    memory_turn_window: int | None = None,
    compact_now: bool = False,
) -> dict[str, Any]:
    """Execute a standard RAG query and return validated response payload."""
    request_model = QueryRequest(
        query=query,
        source_filter=source_filter,
        heading_filter=heading_filter,
        alpha=alpha,
        search_limit=search_limit,
        rerank_top_k=rerank_top_k,
        tenant_id=tenant_id,
        max_query_iterations=max_query_iterations,
        fast_path=fast_path,
        overall_timeout_ms=overall_timeout_ms,
        stage_budget_overrides=stage_budget_overrides or {},
        conversation_id=conversation_id,
        memory_enabled=memory_enabled,
        memory_turn_window=memory_turn_window,
        compact_now=compact_now,
    )
    payload = _request_json("POST", "/query", payload=request_model.model_dump(exclude_none=True))
    return QueryResponse(**payload).model_dump()


@mcp.tool(description="List API keys (admin role required by backend API).")
def admin_list_api_keys(include_revoked: bool = False) -> list[dict[str, Any]]:
    """List managed API keys."""
    _require_admin_tools_enabled()
    suffix = "?include_revoked=true" if include_revoked else ""
    payload = _request_json("GET", f"/admin/api-keys{suffix}")
    if not isinstance(payload, list):
        raise RuntimeError("Invalid API key list response: expected array")
    return [ApiKeyRecord(**item).model_dump() for item in payload]


@mcp.tool(description="Create an API key (admin role required by backend API).")
def admin_create_api_key(
    subject: str,
    tenant_id: str | None = None,
    roles: list[str] | None = None,
    description: str = "",
) -> dict[str, Any]:
    """Create and return a managed API key record."""
    _require_admin_tools_enabled()
    request_model = CreateApiKeyRequest(
        subject=subject,
        tenant_id=tenant_id,
        roles=roles or ["query"],
        description=description,
    )
    payload = _request_json(
        "POST",
        "/admin/api-keys",
        payload=request_model.model_dump(exclude_none=True),
    )
    return CreateApiKeyResponse(**payload).model_dump()


@mcp.tool(description="Revoke an API key by key_id (admin role required by backend API).")
def admin_revoke_api_key(key_id: str) -> dict[str, Any]:
    """Revoke an API key and return status."""
    _require_admin_tools_enabled()
    payload = _request_json("DELETE", f"/admin/api-keys/{key_id}")
    return StatusResponse(**payload).model_dump()


@mcp.tool(description="List quota policy (admin role required by backend API).")
def admin_list_quotas() -> dict[str, Any]:
    """Return current quota defaults and tenant/project overrides."""
    _require_admin_tools_enabled()
    payload = _request_json("GET", "/admin/quotas")
    return QuotasResponse(**payload).model_dump()


@mcp.tool(description="Set a tenant quota in requests/minute (admin role required by backend API).")
def admin_set_tenant_quota(tenant_id: str, requests_per_minute: int) -> dict[str, Any]:
    """Set tenant requests/minute quota and return applied policy."""
    _require_admin_tools_enabled()
    request_model = QuotaUpdateRequest(requests_per_minute=requests_per_minute)
    payload = _request_json(
        "PUT",
        f"/admin/quotas/{tenant_id}",
        payload=request_model.model_dump(),
    )
    return QuotaSetResponse(**payload).model_dump()


@mcp.tool(description="Delete a tenant quota override (admin role required by backend API).")
def admin_delete_tenant_quota(tenant_id: str) -> dict[str, Any]:
    """Delete tenant quota override and return status."""
    _require_admin_tools_enabled()
    payload = _request_json("DELETE", f"/admin/quotas/{tenant_id}")
    return StatusResponse(**payload).model_dump()


def main() -> None:
    """Run MCP adapter over stdio transport."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
