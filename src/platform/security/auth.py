"""Authentication helpers for API key and JWT bearer auth."""

from __future__ import annotations

import hmac
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

from fastapi import Header, HTTPException, status

from config.settings import (
    AUTH_API_KEYS_JSON,
    AUTH_API_KEYS_REQUIRED,
    AUTH_JWT_ENABLED,
    AUTH_JWT_HS256_SECRET,
    AUTH_OIDC_AUDIENCE,
    AUTH_OIDC_ENABLED,
    AUTH_OIDC_ISSUER,
    AUTH_OIDC_JWKS_URL,
    AUTH_OIDC_ROLES_CLAIM,
    AUTH_OIDC_SUBJECT_CLAIM,
    AUTH_OIDC_TENANT_CLAIM,
)
from src.platform.security.api_key_store import lookup_api_key

logger = logging.getLogger("rag.security.auth")


@dataclass
class Principal:
    """Authenticated request principal."""

    subject: str
    tenant_id: str
    roles: list[str]
    auth_type: str
    raw_token_id: str | None = None
    project_id: str | None = None


def _b64url_decode(inp: str) -> bytes:
    import base64

    padding = "=" * (-len(inp) % 4)
    return base64.urlsafe_b64decode(inp + padding)


def _verify_hs256_jwt(token: str, secret: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid JWT format")

    header_b64, payload_b64, signature_b64 = parts
    signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
    expected = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    actual = _b64url_decode(signature_b64)
    if not hmac.compare_digest(expected, actual):
        raise ValueError("Invalid JWT signature")

    header = json.loads(_b64url_decode(header_b64).decode("utf-8"))
    if header.get("alg") != "HS256":
        raise ValueError("Unsupported JWT algorithm")

    payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
    exp = payload.get("exp")
    if exp is not None and float(exp) < time.time():
        raise ValueError("JWT expired")
    return payload


def _verify_oidc_jwt(token: str) -> dict[str, Any]:
    if not AUTH_OIDC_JWKS_URL:
        raise ValueError("OIDC enabled but JWKS URL is not configured")
    if not AUTH_OIDC_ISSUER:
        raise ValueError("OIDC enabled but issuer is not configured")
    if not AUTH_OIDC_AUDIENCE:
        raise ValueError("OIDC enabled but audience is not configured")
    try:
        import jwt
    except Exception as exc:
        raise ValueError("PyJWT is required for OIDC validation") from exc

    jwks_client = jwt.PyJWKClient(AUTH_OIDC_JWKS_URL, cache_keys=True)
    signing_key = jwks_client.get_signing_key_from_jwt(token)
    return jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"],
        audience=AUTH_OIDC_AUDIENCE,
        issuer=AUTH_OIDC_ISSUER,
        options={"require": ["exp", "iat", "sub"]},
    )


def _parse_api_keys() -> dict[str, dict[str, Any]]:
    if not AUTH_API_KEYS_JSON.strip():
        return {}
    try:
        parsed = json.loads(AUTH_API_KEYS_JSON)
    except json.JSONDecodeError as exc:
        raise RuntimeError("RAG_AUTH_API_KEYS_JSON is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("RAG_AUTH_API_KEYS_JSON must be an object")
    return parsed


_API_KEY_INDEX = _parse_api_keys()


def _principal_from_api_key(raw_key: str) -> Optional[Principal]:
    for token_id, cfg in _API_KEY_INDEX.items():
        candidate = str(cfg.get("key", ""))
        if candidate and hmac.compare_digest(candidate, raw_key):
            return Principal(
                subject=str(cfg.get("subject", token_id)),
                tenant_id=str(cfg.get("tenant_id", "default")),
                roles=[str(r) for r in cfg.get("roles", ["query"])],
                auth_type="api_key",
                raw_token_id=token_id,
            )
    managed = lookup_api_key(raw_key)
    if managed:
        return Principal(
            subject=str(managed.get("subject", managed["key_id"])),
            tenant_id=str(managed.get("tenant_id", "default")),
            roles=[str(r) for r in managed.get("roles", ["query"])],
            auth_type="api_key",
            raw_token_id=str(managed["key_id"]),
            project_id=managed.get("project_id"),
        )
    return None


def _principal_from_jwt(raw_jwt: str) -> Principal:
    if AUTH_OIDC_ENABLED:
        try:
            payload = _verify_oidc_jwt(raw_jwt)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid OIDC bearer token: {exc}",
            ) from exc
        roles = payload.get(AUTH_OIDC_ROLES_CLAIM, payload.get("roles", ["query"]))
        if isinstance(roles, str):
            roles = [roles]
        return Principal(
            subject=str(payload.get(AUTH_OIDC_SUBJECT_CLAIM, "unknown")),
            tenant_id=str(payload.get(AUTH_OIDC_TENANT_CLAIM, "default")),
            roles=[str(r) for r in roles],
            auth_type="oidc",
            project_id=payload.get("project_id"),
        )

    if not AUTH_JWT_HS256_SECRET:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="JWT auth enabled but HS256 secret is not configured",
        )
    try:
        payload = _verify_hs256_jwt(raw_jwt, AUTH_JWT_HS256_SECRET)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid bearer token: {exc}",
        ) from exc

    roles = payload.get("roles", ["query"])
    if isinstance(roles, str):
        roles = [roles]
    return Principal(
        subject=str(payload.get("sub", "unknown")),
        tenant_id=str(payload.get("tenant_id", "default")),
        roles=[str(r) for r in roles],
        auth_type="jwt",
        project_id=payload.get("project_id"),
    )


def _extract_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    prefix = "bearer "
    if authorization.lower().startswith(prefix):
        return authorization[len(prefix) :].strip()
    return None


async def authenticate_request(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
) -> Principal:
    """FastAPI dependency for auth. Honors API-key and JWT settings."""
    bearer = _extract_bearer(authorization)

    # API key has precedence for service clients.
    if x_api_key:
        principal = _principal_from_api_key(x_api_key)
        if principal:
            return principal
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

    if bearer and (AUTH_JWT_ENABLED or AUTH_OIDC_ENABLED):
        return _principal_from_jwt(bearer)

    if AUTH_API_KEYS_REQUIRED or AUTH_JWT_ENABLED or AUTH_OIDC_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    # Backward-compatible dev mode.
    return Principal(
        subject="anonymous",
        tenant_id="default",
        roles=["query", "admin"],
        auth_type="none",
    )

