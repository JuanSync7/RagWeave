import asyncio
import base64
import hashlib
import hmac
import json
import time

import pytest
from fastapi import HTTPException

from src.platform.security import auth


def _make_hs256_token(payload: dict, secret: str, alg: str = "HS256") -> str:
    """Construct a minimal HS256 JWT for tests."""
    header = base64.urlsafe_b64encode(json.dumps({"alg": alg, "typ": "JWT"}).encode()).rstrip(b"=").decode()
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    signing_input = f"{header}.{body}".encode()
    sig = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).rstrip(b"=").decode()
    return f"{header}.{body}.{sig_b64}"


def test_api_key_auth_match(monkeypatch):
    payload = {
        "svc1": {
            "key": "test-key",
            "subject": "service-a",
            "tenant_id": "t-1",
            "roles": ["query"],
        }
    }
    monkeypatch.setattr(auth, "_API_KEY_INDEX", payload)
    principal = auth._principal_from_api_key("test-key")
    assert principal is not None
    assert principal.tenant_id == "t-1"
    assert "query" in principal.roles


def test_oidc_principal_mapping(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_OIDC_ENABLED", True)
    monkeypatch.setattr(auth, "AUTH_OIDC_ROLES_CLAIM", "roles")
    monkeypatch.setattr(auth, "AUTH_OIDC_SUBJECT_CLAIM", "sub")
    monkeypatch.setattr(auth, "AUTH_OIDC_TENANT_CLAIM", "tenant_id")
    monkeypatch.setattr(
        auth,
        "_verify_oidc_jwt",
        lambda _token: {
            "sub": "user-1",
            "tenant_id": "tenant-1",
            "roles": ["query", "admin"],
            "project_id": "p-1",
        },
    )
    principal = auth._principal_from_jwt("dummy")
    assert principal.subject == "user-1"
    assert principal.tenant_id == "tenant-1"
    assert "admin" in principal.roles
    assert principal.project_id == "p-1"


# ---------------------------------------------------------------------------
# JWT HS256 tests
# ---------------------------------------------------------------------------

_SECRET = "test-secret-for-hs256"


def test_hs256_valid_token_authenticated(monkeypatch):
    """A valid HS256 token with correct signature returns a Principal."""
    payload = {
        "sub": "user-hs",
        "tenant_id": "tenant-hs",
        "roles": ["query"],
        "exp": int(time.time()) + 3600,
    }
    token = _make_hs256_token(payload, _SECRET)
    monkeypatch.setattr(auth, "AUTH_JWT_ENABLED", True)
    monkeypatch.setattr(auth, "AUTH_OIDC_ENABLED", False)
    monkeypatch.setattr(auth, "AUTH_JWT_HS256_SECRET", _SECRET)

    principal = auth._principal_from_jwt(token)
    assert principal.subject == "user-hs"
    assert principal.tenant_id == "tenant-hs"
    assert "query" in principal.roles
    assert principal.auth_type == "jwt"


def test_hs256_expired_token_raises_401(monkeypatch):
    """An expired HS256 token raises HTTP 401."""
    payload = {
        "sub": "user-exp",
        "tenant_id": "t",
        "exp": int(time.time()) - 10,  # already expired
    }
    token = _make_hs256_token(payload, _SECRET)
    monkeypatch.setattr(auth, "AUTH_JWT_ENABLED", True)
    monkeypatch.setattr(auth, "AUTH_OIDC_ENABLED", False)
    monkeypatch.setattr(auth, "AUTH_JWT_HS256_SECRET", _SECRET)

    with pytest.raises(HTTPException) as exc_info:
        auth._principal_from_jwt(token)
    assert exc_info.value.status_code == 401


def test_hs256_wrong_signature_raises_401(monkeypatch):
    """A token signed with the wrong secret raises HTTP 401."""
    payload = {"sub": "user-bad", "exp": int(time.time()) + 3600}
    token = _make_hs256_token(payload, "wrong-secret")
    monkeypatch.setattr(auth, "AUTH_JWT_ENABLED", True)
    monkeypatch.setattr(auth, "AUTH_OIDC_ENABLED", False)
    monkeypatch.setattr(auth, "AUTH_JWT_HS256_SECRET", _SECRET)

    with pytest.raises(HTTPException) as exc_info:
        auth._principal_from_jwt(token)
    assert exc_info.value.status_code == 401


def test_missing_auth_header_raises_401_when_required(monkeypatch):
    """No Authorization header raises HTTP 401 when auth is required."""
    monkeypatch.setattr(auth, "AUTH_API_KEYS_REQUIRED", True)
    monkeypatch.setattr(auth, "AUTH_JWT_ENABLED", False)
    monkeypatch.setattr(auth, "AUTH_OIDC_ENABLED", False)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            auth.authenticate_request(authorization=None, x_api_key=None)
        )
    assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# OIDC tests
# ---------------------------------------------------------------------------


def test_oidc_valid_token_and_kid_authenticated(monkeypatch):
    """Stubbed JWKS: valid token + matching kid → authenticated Principal."""
    monkeypatch.setattr(auth, "AUTH_OIDC_ENABLED", True)
    monkeypatch.setattr(auth, "AUTH_OIDC_ROLES_CLAIM", "roles")
    monkeypatch.setattr(auth, "AUTH_OIDC_SUBJECT_CLAIM", "sub")
    monkeypatch.setattr(auth, "AUTH_OIDC_TENANT_CLAIM", "tenant_id")
    monkeypatch.setattr(
        auth,
        "_verify_oidc_jwt",
        lambda _token: {
            "sub": "oidc-user",
            "tenant_id": "oidc-tenant",
            "roles": ["query"],
        },
    )

    principal = auth._principal_from_jwt("dummy-oidc-token")
    assert principal.subject == "oidc-user"
    assert principal.tenant_id == "oidc-tenant"
    assert principal.auth_type == "oidc"


def test_oidc_unknown_kid_raises_401(monkeypatch):
    """Unknown kid in JWKS causes HTTP 401."""
    monkeypatch.setattr(auth, "AUTH_OIDC_ENABLED", True)

    def _bad_verify(_token: str):
        raise ValueError("Unable to find a signing key that matches the kid: unknown-kid")

    monkeypatch.setattr(auth, "_verify_oidc_jwt", _bad_verify)

    with pytest.raises(HTTPException) as exc_info:
        auth._principal_from_jwt("bad-token")
    assert exc_info.value.status_code == 401


def test_oidc_issuer_mismatch_raises_401(monkeypatch):
    """Issuer mismatch during OIDC validation causes HTTP 401."""
    monkeypatch.setattr(auth, "AUTH_OIDC_ENABLED", True)

    def _bad_verify(_token: str):
        raise ValueError("Invalid issuer")

    monkeypatch.setattr(auth, "_verify_oidc_jwt", _bad_verify)

    with pytest.raises(HTTPException) as exc_info:
        auth._principal_from_jwt("mismatched-issuer-token")
    assert exc_info.value.status_code == 401
