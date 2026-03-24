"""Tests for server configuration wiring and validation."""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest

import config.settings as _settings

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _restore_settings():
    """Reload settings to a clean state after each test."""
    yield
    importlib.reload(_settings)


# ---------------------------------------------------------------------------
# RAG_API_CORS_ORIGINS — settings parsing
# ---------------------------------------------------------------------------

def test_cors_origins_default(monkeypatch):
    """Unset env var -> ["*"] (preserves current behaviour)."""
    monkeypatch.delenv("RAG_API_CORS_ORIGINS", raising=False)
    mod = importlib.reload(_settings)
    assert mod.RAG_API_CORS_ORIGINS == ["*"]


def test_cors_origins_single(monkeypatch):
    """Single origin is returned as a one-element list."""
    monkeypatch.setenv("RAG_API_CORS_ORIGINS", "http://localhost:3000")
    mod = importlib.reload(_settings)
    assert mod.RAG_API_CORS_ORIGINS == ["http://localhost:3000"]


def test_cors_origins_multiple(monkeypatch):
    """Comma-separated string splits into a list of stripped origins."""
    monkeypatch.setenv("RAG_API_CORS_ORIGINS", "http://a.com,http://b.com")
    mod = importlib.reload(_settings)
    assert mod.RAG_API_CORS_ORIGINS == ["http://a.com", "http://b.com"]


def test_cors_origins_empty_string(monkeypatch):
    """Empty string falls back to ["*"]."""
    monkeypatch.setenv("RAG_API_CORS_ORIGINS", "")
    mod = importlib.reload(_settings)
    assert mod.RAG_API_CORS_ORIGINS == ["*"]


def test_cors_origins_whitespace_only(monkeypatch):
    """Whitespace-only string falls back to ["*"]."""
    monkeypatch.setenv("RAG_API_CORS_ORIGINS", "   ")
    mod = importlib.reload(_settings)
    assert mod.RAG_API_CORS_ORIGINS == ["*"]


# ---------------------------------------------------------------------------
# Static wire-up checks (source inspection)
# ---------------------------------------------------------------------------

def test_api_cors_not_hardcoded():
    """server/api.py must use RAG_API_CORS_ORIGINS, not a hardcoded ["*"]."""
    source = (_PROJECT_ROOT / "server" / "api.py").read_text()
    assert 'allow_origins=["*"]' not in source, (
        'server/api.py still hardcodes allow_origins=["*"]. '
        "Replace with allow_origins=RAG_API_CORS_ORIGINS."
    )
    assert "RAG_API_CORS_ORIGINS" in source, (
        "server/api.py does not import or use RAG_API_CORS_ORIGINS."
    )


# ---------------------------------------------------------------------------
# RAG_WORKFLOW_DEFAULT_TIMEOUT_MS — settings parsing
# ---------------------------------------------------------------------------

def test_workflow_timeout_default(monkeypatch):
    """Unset env var -> 120000 ms (preserves current behaviour)."""
    monkeypatch.delenv("RAG_WORKFLOW_DEFAULT_TIMEOUT_MS", raising=False)
    mod = importlib.reload(_settings)
    assert mod.RAG_WORKFLOW_DEFAULT_TIMEOUT_MS == 120000


def test_workflow_timeout_custom(monkeypatch):
    """Custom value is parsed as int."""
    monkeypatch.setenv("RAG_WORKFLOW_DEFAULT_TIMEOUT_MS", "60000")
    mod = importlib.reload(_settings)
    assert mod.RAG_WORKFLOW_DEFAULT_TIMEOUT_MS == 60000


# ---------------------------------------------------------------------------
# _validate_startup_config — validation logic
# ---------------------------------------------------------------------------

def test_validate_startup_config_passes_with_valid_value():
    """Valid positive timeout must not raise."""
    from server.common.utils import validate_startup_config
    validate_startup_config(workflow_timeout_ms=120000)  # must not raise


def test_validate_startup_config_rejects_zero():
    """Zero timeout must raise ValueError."""
    from server.common.utils import validate_startup_config
    with pytest.raises(ValueError, match="RAG_WORKFLOW_DEFAULT_TIMEOUT_MS"):
        validate_startup_config(workflow_timeout_ms=0)


def test_validate_startup_config_rejects_negative():
    """Negative timeout must raise ValueError."""
    from server.common.utils import validate_startup_config
    with pytest.raises(ValueError, match="RAG_WORKFLOW_DEFAULT_TIMEOUT_MS"):
        validate_startup_config(workflow_timeout_ms=-1000)


def test_workflow_timeout_not_hardcoded():
    """server/workflows.py must use RAG_WORKFLOW_DEFAULT_TIMEOUT_MS, not 120000."""
    source = (_PROJECT_ROOT / "server" / "workflows.py").read_text()
    assert "120000" not in source, (
        "server/workflows.py still hardcodes 120000. "
        "Replace with RAG_WORKFLOW_DEFAULT_TIMEOUT_MS."
    )
    assert "RAG_WORKFLOW_DEFAULT_TIMEOUT_MS" in source, (
        "server/workflows.py does not import or use RAG_WORKFLOW_DEFAULT_TIMEOUT_MS."
    )
