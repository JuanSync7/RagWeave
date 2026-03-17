import pytest

from server import mcp_adapter


def test_parse_error_payload_prefers_standard_envelope():
    body = '{"ok":false,"error":{"code":"HTTP_429","message":"Rate limit exceeded"}}'
    message = mcp_adapter._parse_error_payload(429, body)
    assert "HTTP_429" in message
    assert "Rate limit exceeded" in message


def test_health_tool_validates_schema(monkeypatch):
    monkeypatch.setattr(
        mcp_adapter,
        "_request_json",
        lambda method, path, payload=None, timeout_seconds=90: {
            "status": "healthy",
            "temporal_connected": True,
            "worker_available": True,
        },
    )
    result = mcp_adapter.health()
    assert result["status"] == "healthy"
    assert result["temporal_connected"] is True


def test_query_tool_rejects_invalid_stage_budget_key():
    with pytest.raises(Exception):
        mcp_adapter.query(
            query="hello",
            stage_budget_overrides={"bad_stage": 1000},
        )


def test_query_tool_returns_validated_response(monkeypatch):
    monkeypatch.setattr(
        mcp_adapter,
        "_request_json",
        lambda method, path, payload=None, timeout_seconds=90: {
            "query": "hello",
            "processed_query": "hello",
            "query_confidence": 0.9,
            "action": "search",
            "results": [],
            "stage_timings": [],
            "timing_totals": {"total_ms": 10.0},
            "budget_exhausted": False,
        },
    )
    result = mcp_adapter.query(query="hello")
    assert result["action"] == "search"
    assert result["processed_query"] == "hello"


def test_admin_list_api_keys_validates_list_payload(monkeypatch):
    monkeypatch.setenv("RAG_MCP_ENABLE_ADMIN_TOOLS", "1")
    monkeypatch.setattr(
        mcp_adapter,
        "_request_json",
        lambda method, path, payload=None, timeout_seconds=90: [
            {
                "key_id": "k1",
                "subject": "svc",
                "tenant_id": "default",
                "roles": ["query"],
                "description": "",
                "created_at": 1,
                "revoked_at": None,
            }
        ],
    )
    result = mcp_adapter.admin_list_api_keys()
    assert len(result) == 1
    assert result[0]["key_id"] == "k1"


def test_admin_create_api_key_validates_response(monkeypatch):
    monkeypatch.setenv("RAG_MCP_ENABLE_ADMIN_TOOLS", "1")
    monkeypatch.setattr(
        mcp_adapter,
        "_request_json",
        lambda method, path, payload=None, timeout_seconds=90: {
            "key_id": "k2",
            "subject": "svc2",
            "tenant_id": "default",
            "roles": ["query"],
            "description": "",
            "created_at": 2,
            "revoked_at": None,
            "api_key": "rag_live_x",
        },
    )
    result = mcp_adapter.admin_create_api_key(subject="svc2")
    assert result["key_id"] == "k2"
    assert result["api_key"] == "rag_live_x"


def test_admin_quota_tools_validate_payloads(monkeypatch):
    monkeypatch.setenv("RAG_MCP_ENABLE_ADMIN_TOOLS", "1")
    monkeypatch.setattr(
        mcp_adapter,
        "_request_json",
        lambda method, path, payload=None, timeout_seconds=90: (
            {"defaults": {}, "tenants": {}, "projects": {}}
            if method == "GET"
            else {"tenant_id": "t1", "requests_per_minute": 123}
            if method == "PUT"
            else {"status": "deleted", "tenant_id": "t1"}
        ),
    )
    listed = mcp_adapter.admin_list_quotas()
    set_result = mcp_adapter.admin_set_tenant_quota("t1", 123)
    deleted = mcp_adapter.admin_delete_tenant_quota("t1")
    assert listed["tenants"] == {}
    assert set_result["requests_per_minute"] == 123
    assert deleted["status"] == "deleted"


def test_admin_tools_disabled_by_default(monkeypatch):
    monkeypatch.delenv("RAG_MCP_ENABLE_ADMIN_TOOLS", raising=False)
    with pytest.raises(RuntimeError):
        mcp_adapter.admin_list_api_keys()
