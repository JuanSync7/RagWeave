# @summary
# Admin routes for API key and quota management with role checks.
# Exports: create_admin_router, list_api_keys_handler, create_api_key_handler, list_quotas_handler
# Deps: fastapi, server.schemas, src.platform.security
# @end-summary
"""Admin API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from server.schemas import (
    ApiErrorResponse,
    ApiKeyRecord,
    CreateApiKeyRequest,
    CreateApiKeyResponse,
    QuotaSetResponse,
    QuotasResponse,
    QuotaUpdateRequest,
    StatusResponse,
)
from src.platform.security import (
    create_api_key,
    list_api_keys,
    revoke_api_key,
)
from src.platform.security import (
    Principal,
    authenticate_request,
)
from src.platform.security import (
    delete_tenant_quota,
    list_quotas,
    set_tenant_quota,
)
from src.platform.security import require_role


async def list_api_keys_handler(
    include_revoked: bool,
    principal: Principal,
) -> list[ApiKeyRecord]:
    require_role(principal, "admin")
    records = list_api_keys(include_revoked=include_revoked)
    return [ApiKeyRecord(**record) for record in records]


async def create_api_key_handler(
    request: CreateApiKeyRequest,
    principal: Principal,
) -> CreateApiKeyResponse:
    require_role(principal, "admin")
    created = create_api_key(
        subject=request.subject,
        tenant_id=request.tenant_id,
        roles=request.roles,
        description=request.description,
    )
    return CreateApiKeyResponse(**created)


async def list_quotas_handler(principal: Principal) -> QuotasResponse:
    require_role(principal, "admin")
    return QuotasResponse(**list_quotas())


def create_admin_router() -> APIRouter:
    """Create router for admin endpoints."""
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

    @router.get(
        "/admin/api-keys",
        response_model=list[ApiKeyRecord],
        responses=standard_error_responses,
    )
    async def admin_list_api_keys(
        include_revoked: bool = False,
        principal: Principal = Depends(authenticate_request),
    ):
        return await list_api_keys_handler(include_revoked, principal)

    @router.post(
        "/admin/api-keys",
        response_model=CreateApiKeyResponse,
        responses=standard_error_responses,
    )
    async def admin_create_api_key(
        request: CreateApiKeyRequest,
        principal: Principal = Depends(authenticate_request),
    ):
        return await create_api_key_handler(request, principal)

    @router.delete(
        "/admin/api-keys/{key_id}",
        response_model=StatusResponse,
        responses=standard_error_responses,
    )
    async def admin_revoke_api_key(key_id: str, principal: Principal = Depends(authenticate_request)):
        require_role(principal, "admin")
        ok = revoke_api_key(key_id)
        if not ok:
            raise HTTPException(status_code=404, detail="API key not found")
        return StatusResponse(status="revoked", key_id=key_id)

    @router.get("/admin/quotas", response_model=QuotasResponse, responses=standard_error_responses)
    async def admin_list_quotas(principal: Principal = Depends(authenticate_request)):
        return await list_quotas_handler(principal)

    @router.put(
        "/admin/quotas/{tenant_id}",
        response_model=QuotaSetResponse,
        responses=standard_error_responses,
    )
    async def admin_set_tenant_quota(
        tenant_id: str,
        request: QuotaUpdateRequest,
        principal: Principal = Depends(authenticate_request),
    ):
        require_role(principal, "admin")
        return set_tenant_quota(tenant_id, request.requests_per_minute)

    @router.delete(
        "/admin/quotas/{tenant_id}",
        response_model=StatusResponse,
        responses=standard_error_responses,
    )
    async def admin_delete_tenant_quota(
        tenant_id: str,
        principal: Principal = Depends(authenticate_request),
    ):
        require_role(principal, "admin")
        existed = delete_tenant_quota(tenant_id)
        return StatusResponse(status="deleted" if existed else "noop", tenant_id=tenant_id)

    return router


__all__ = [
    "create_admin_router",
    "list_api_keys_handler",
    "create_api_key_handler",
    "list_quotas_handler",
]
