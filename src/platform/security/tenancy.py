# @summary
# Tenancy context helpers for resolving effective tenant id from a Principal.
# Exports: resolve_tenant_id
# Deps: src.platform.security.auth
# @end-summary
"""Tenancy context helpers."""

from src.platform.security.auth import Principal


def resolve_tenant_id(principal: Principal, requested_tenant_id: str | None) -> str:
    """Resolve the effective tenant id for a request.

    Non-admin callers cannot override their tenant.

    Args:
        principal: Authenticated request principal.
        requested_tenant_id: Optional tenant override requested by the caller.

    Returns:
        Effective tenant id to use for the request.
    """
    if requested_tenant_id:
        # Tenant override is restricted to admin role.
        if "admin" in principal.roles:
            return requested_tenant_id
        return principal.tenant_id
    return principal.tenant_id

