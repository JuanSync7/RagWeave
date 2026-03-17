from __future__ import annotations

from fastapi.testclient import TestClient

from server import api
from src.platform.security import auth


class _DummyWorkflowService:
    async def get_system_info(self):
        return {"status": "ok"}


class _DummyTemporalClient:
    def __init__(self):
        self.workflow_service = _DummyWorkflowService()

    async def execute_workflow(self, *args, **kwargs):
        return {
            "query": "hello",
            "processed_query": "hello",
            "query_confidence": 0.9,
            "action": "search",
            "results": [],
            "generated_answer": "test answer",
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


def test_query_returns_conversation_id(monkeypatch):
    _set_auth_defaults()

    async def _fake_connect(_target: str):
        return _DummyTemporalClient()

    monkeypatch.setattr(api.Client, "connect", _fake_connect)
    with TestClient(api.app, raise_server_exceptions=False) as client:
        response = client.post("/query", json={"query": "hello"})
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body.get("conversation_id"), str)
    assert body["conversation_id"]


def test_query_respects_provided_conversation_id(monkeypatch):
    _set_auth_defaults()

    async def _fake_connect(_target: str):
        return _DummyTemporalClient()

    monkeypatch.setattr(api.Client, "connect", _fake_connect)
    with TestClient(api.app, raise_server_exceptions=False) as client:
        response = client.post(
            "/query",
            json={"query": "follow up", "conversation_id": "conv_demo_123"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["conversation_id"] == "conv_demo_123"


def test_console_command_switch_and_compact_actions(monkeypatch):
    _set_auth_defaults()

    async def _fake_connect(_target: str):
        return _DummyTemporalClient()

    monkeypatch.setattr(api.Client, "connect", _fake_connect)
    with TestClient(api.app, raise_server_exceptions=False) as client:
        switch_resp = client.post(
            "/console/command",
            json={"mode": "query", "command": "switch", "arg": "conv_abc", "state": {}},
        )
        compact_resp = client.post(
            "/console/command",
            json={
                "mode": "query",
                "command": "compact",
                "state": {"conversation_id": "conv_abc"},
            },
        )

    assert switch_resp.status_code == 200
    switch_data = switch_resp.json()["data"]
    assert switch_data["action"] == "switch_conversation"
    assert switch_data["data"]["conversation_id"] == "conv_abc"

    assert compact_resp.status_code == 200
    compact_data = compact_resp.json()["data"]
    assert compact_data["action"] == "compact_conversation"
