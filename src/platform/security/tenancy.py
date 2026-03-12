"""Tenancy context helpers."""

from src.platform.security.auth import Principal


def resolve_tenant_id(principal: Principal, requested_tenant_id: str | None) -> str:
    """Resolve effective tenant ID with safe defaults."""
    if requested_tenant_id:
        # Tenant override is restricted to admin role.
        if "admin" in principal.roles:
            return requested_tenant_id
        return principal.tenant_id
    return principal.tenant_id

