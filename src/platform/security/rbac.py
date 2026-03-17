# @summary
# Role-based access control helpers for checking Principal roles.
# Exports: require_role
# Deps: fastapi, src.platform.security.auth
# @end-summary
"""Role-based access control helpers."""

from fastapi import HTTPException, status

from src.platform.security.auth import Principal


def require_role(principal: Principal, required: str) -> None:
    """Ensure a principal has a required role.

    Args:
        principal: Authenticated request principal.
        required: Role required for the operation.

    Raises:
        HTTPException: With 403 status when the principal lacks the role.
    """
    if required in principal.roles:
        return
    if "admin" in principal.roles:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"Missing role: {required}",
    )

