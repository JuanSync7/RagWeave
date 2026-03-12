"""Role-based access helpers."""

from fastapi import HTTPException, status

from src.platform.security.auth import Principal


def require_role(principal: Principal, required: str) -> None:
    """Raise 403 when principal lacks required role."""
    if required in principal.roles:
        return
    if "admin" in principal.roles:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"Missing role: {required}",
    )

