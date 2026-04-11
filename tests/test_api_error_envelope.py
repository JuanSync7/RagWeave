from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from server import api
from src.platform.security import auth
from src.platform.security.auth import authenticate_request, Principal


class _DummyWorkflowService:
    async def get_system_info(self):
        return {"status": "ok"}


class _DummyTemporalClient:
    def __init__(self, *, fail_query: bool = False):
        self.workflow_service = _DummyWorkflowService()
        self._fail_query = fail_query

    async def execute_workflow(self, *args, **kwargs):
        if self._fail_query:
            raise RuntimeError("simulated workflow failure")
        return {
            "query": "hello",
            "processed_query": "hello",
            "query_confidence": 0.9,
            "action": "search",
            "results": [],
            "stage_timings": [],
            "timing_totals": {"total_ms": 5.0},
            "budget_exhausted": False,
        }

    async def close(self):
        return None


def _set_auth_defaults() -> None:
    auth.AUTH_API_KEYS_REQUIRED = False
    auth.AUTH_JWT_ENABLED = False
    auth.AUTH_OIDC_ENABLED = False


def test_422_validation_error_uses_standard_envelope(monkeypatch):
    _set_auth_defaults()

    async def _fake_connect(_target: str):
        return _DummyTemporalClient()

    monkeypatch.setattr(api.Client, "connect", _fake_connect)
    with TestClient(api.app, raise_server_exceptions=False) as client:
        response = client.post("/query", json={})

    body = response.json()
    assert response.status_code == 422
    assert body["ok"] is False
    assert body["error"]["code"] == "REQUEST_VALIDATION_ERROR"
    assert "x-request-id" in response.headers
    assert body["request_id"] == response.headers["x-request-id"]


def test_401_auth_error_uses_standard_envelope(monkeypatch):
    auth.AUTH_API_KEYS_REQUIRED = True
    auth.AUTH_JWT_ENABLED = False
    auth.AUTH_OIDC_ENABLED = False

    async def _fake_connect(_target: str):
        return _DummyTemporalClient()

    monkeypatch.setattr(api.Client, "connect", _fake_connect)
    with TestClient(api.app, raise_server_exceptions=False) as client:
        response = client.post("/query", json={"query": "hello"})

    body = response.json()
    assert response.status_code == 401
    assert body["ok"] is False
    assert body["error"]["code"] == "HTTP_401"
    assert body["error"]["message"] == "Authentication required"


def test_403_role_error_uses_standard_envelope(monkeypatch):
    _set_auth_defaults()

    async def _fake_connect(_target: str):
        return _DummyTemporalClient()

    async def _viewer_principal():
        return Principal(
            subject="viewer",
            tenant_id="default",
            roles=["viewer"],
            auth_type="none",
        )

    monkeypatch.setattr(api.Client, "connect", _fake_connect)
    api.app.dependency_overrides[authenticate_request] = _viewer_principal
    try:
        with TestClient(api.app, raise_server_exceptions=False) as client:
            response = client.post("/query", json={"query": "hello"})
    finally:
        api.app.dependency_overrides.clear()

    body = response.json()
    assert response.status_code == 403
    assert body["ok"] is False
    assert body["error"]["code"] == "HTTP_403"
    assert "Missing role" in body["error"]["message"]


def test_500_query_failure_uses_standard_envelope(monkeypatch):
    _set_auth_defaults()

    async def _fake_connect(_target: str):
        return _DummyTemporalClient(fail_query=True)

    monkeypatch.setattr(api.Client, "connect", _fake_connect)
    with TestClient(api.app, raise_server_exceptions=False) as client:
        response = client.post("/query", json={"query": "hello"})

    body = response.json()
    assert response.status_code == 500
    assert body["ok"] is False
    assert body["error"]["code"] == "INTERNAL_SERVER_ERROR"
    # Production's unhandled-exception handler intentionally returns a
    # generic message and does NOT leak the upstream exception text — the
    # original "simulated workflow failure" is logged server-side but is
    # scrubbed from the client response (server/api.py:230-241).
    assert body["error"]["message"] == "Internal server error"


def test_404_not_found_uses_standard_envelope(monkeypatch):
    _set_auth_defaults()

    async def _fake_connect(_target: str):
        return _DummyTemporalClient()

    monkeypatch.setattr(api.Client, "connect", _fake_connect)
    with TestClient(api.app, raise_server_exceptions=False) as client:
        response = client.get("/does-not-exist")

    body = response.json()
    assert response.status_code == 404
    assert body["ok"] is False
    assert body["error"]["code"] == "HTTP_404"


def test_503_overload_uses_standard_envelope(monkeypatch):
    _set_auth_defaults()

    async def _fake_connect(_target: str):
        return _DummyTemporalClient()

    monkeypatch.setattr(api.Client, "connect", _fake_connect)
    monkeypatch.setattr(api, "_api_inflight_semaphore", asyncio.Semaphore(0))
    monkeypatch.setattr(api, "_api_overload_queue_timeout_ms", 1)
    with TestClient(api.app, raise_server_exceptions=False) as client:
        response = client.post("/query", json={"query": "hello"})

    body = response.json()
    assert response.status_code == 503
    assert body["ok"] is False
    assert body["error"]["code"] == "HTTP_503"
    assert "Server overloaded" in body["error"]["message"]
