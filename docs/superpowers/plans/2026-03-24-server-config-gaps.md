# Server Config Gap Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire two hardcoded server values (`allow_origins=["*"]` and `120000` ms timeout) to env-configurable settings constants, closing the gaps identified in the SERVER_API_SPEC audit.

**Architecture:** Both constants are added to `config/settings.py` following the existing `os.environ.get(VAR, default)` pattern. The workflow timeout validation (reject `<= 0`) lives in `_validate_startup_config()` in `server/api.py`, called from `lifespan`. The function accepts the value as a parameter so tests can call it directly with explicit values — no module reload needed for validation tests. The CORS constant is wired into `CORSMiddleware` in `server/api.py`. The timeout constant is the default fallback in `server/workflows.py`.

> **Spec/plan note:** The spec says validation should live in `settings.py`. The plan overrides this by putting validation in `server/api.py` to keep `settings.py` side-effect-free and the validation function independently testable without module reloads.

**Tech Stack:** Python 3.12, FastAPI/Starlette, `config/settings.py` env-var pattern, pytest + monkeypatch, `importlib.reload` for settings isolation.

**Spec:** `docs/superpowers/specs/2026-03-24-server-config-gaps-design.md`

---

## File Map

| File | Action | What changes |
|------|--------|-------------|
| `config/settings.py` | Modify | Add `RAG_API_CORS_ORIGINS` and `RAG_WORKFLOW_DEFAULT_TIMEOUT_MS` in the `# --- Server ---` block |
| `server/api.py` | Modify | Import both constants; replace hardcoded `["*"]`; add `_validate_startup_config(ms)` called from `lifespan` |
| `server/workflows.py` | Modify | Import `RAG_WORKFLOW_DEFAULT_TIMEOUT_MS`; replace hardcoded `120000` default |
| `tests/test_server_config.py` | Create | Unit tests for settings parsing, validation, and static wire-up checks |

---

## Task 1: CORS Origins — Settings + Wire-up

**Files:**
- Modify: `config/settings.py` (inside `# --- Server ---` block, after `RAG_API_OVERLOAD_QUEUE_TIMEOUT_MS` line ~186)
- Modify: `server/api.py` (lines 33–40 import block; line 158 `allow_origins`)
- Create: `tests/test_server_config.py`

---

- [ ] **Step 1.1: Write failing tests for `RAG_API_CORS_ORIGINS` settings parsing**

Create `tests/test_server_config.py`:

```python
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
    """Unset env var -> [\"*\"] (preserves current behaviour)."""
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
    """Empty string falls back to [\"*\"]."""
    monkeypatch.setenv("RAG_API_CORS_ORIGINS", "")
    mod = importlib.reload(_settings)
    assert mod.RAG_API_CORS_ORIGINS == ["*"]


def test_cors_origins_whitespace_only(monkeypatch):
    """Whitespace-only string falls back to [\"*\"]."""
    monkeypatch.setenv("RAG_API_CORS_ORIGINS", "   ")
    mod = importlib.reload(_settings)
    assert mod.RAG_API_CORS_ORIGINS == ["*"]
```

- [ ] **Step 1.2: Run tests — verify they FAIL**

```bash
pytest tests/test_server_config.py -v
```

Expected: `FAILED` on all 5 tests with `AttributeError: module 'config.settings' has no attribute 'RAG_API_CORS_ORIGINS'`.

---

- [ ] **Step 1.3: Add `RAG_API_CORS_ORIGINS` to `config/settings.py`**

Inside the `# --- Server ---` block, after the `RAG_API_OVERLOAD_QUEUE_TIMEOUT_MS` line (~186):

```python
RAG_API_CORS_ORIGINS: list[str] = [
    o.strip()
    for o in os.environ.get("RAG_API_CORS_ORIGINS", "*").split(",")
    if o.strip()
] or ["*"]
```

- [ ] **Step 1.4: Run settings parsing tests — verify they PASS**

```bash
pytest tests/test_server_config.py -v -k "cors_origins"
```

Expected: all 5 tests PASS.

---

- [ ] **Step 1.5: Write failing static wire-up test for `server/api.py`**

Add to `tests/test_server_config.py`:

```python
# ---------------------------------------------------------------------------
# Static wire-up checks (source inspection)
# ---------------------------------------------------------------------------

def test_api_cors_not_hardcoded():
    """server/api.py must use RAG_API_CORS_ORIGINS, not a hardcoded [\"*\"]."""
    source = (_PROJECT_ROOT / "server" / "api.py").read_text()
    assert 'allow_origins=["*"]' not in source, (
        'server/api.py still hardcodes allow_origins=["*"]. '
        "Replace with allow_origins=RAG_API_CORS_ORIGINS."
    )
    assert "RAG_API_CORS_ORIGINS" in source, (
        "server/api.py does not import or use RAG_API_CORS_ORIGINS."
    )
```

- [ ] **Step 1.6: Run wire-up test — verify it FAILS**

```bash
pytest tests/test_server_config.py::test_api_cors_not_hardcoded -v
```

Expected: `FAILED` — `allow_origins=["*"]` still present in source.

---

- [ ] **Step 1.7: Update `server/api.py` — add import and replace hardcoded value**

**Import block** (`server/api.py` lines 33–40): add `RAG_API_CORS_ORIGINS` to the existing import. The full block after this step:

```python
from config.settings import (
    TEMPORAL_TARGET_HOST,
    RAG_API_MAX_INFLIGHT_REQUESTS,
    RAG_API_OVERLOAD_QUEUE_TIMEOUT_MS,
    RAG_API_CORS_ORIGINS,
    RATE_LIMIT_ENABLED,
    RATE_LIMIT_REQUESTS_PER_MINUTE,
    RATE_LIMIT_WINDOW_SECONDS,
)
```

**Middleware call** (`server/api.py` lines 156–161): replace `allow_origins=["*"]`:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=RAG_API_CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

- [ ] **Step 1.8: Run all Task 1 tests — verify they PASS**

```bash
pytest tests/test_server_config.py -v -k "cors"
```

Expected: all 6 tests PASS.

---

- [ ] **Step 1.9: Commit**

```bash
git add config/settings.py server/api.py tests/test_server_config.py
git commit -m "feat: make CORS origins configurable via RAG_API_CORS_ORIGINS env var"
```

---

## Task 2: Workflow Default Timeout — Settings + Validation + Wire-up

**Files:**
- Modify: `config/settings.py` (inside `# --- Server ---` block, after `RAG_API_CORS_ORIGINS`)
- Modify: `server/api.py` (extend import block from Task 1; add `_validate_startup_config`; update `lifespan`)
- Modify: `server/workflows.py` (add import; replace hardcoded `120000`)
- Modify: `tests/test_server_config.py` (add timeout tests)

---

- [ ] **Step 2.1: Write failing tests for `RAG_WORKFLOW_DEFAULT_TIMEOUT_MS` settings parsing**

Add to `tests/test_server_config.py`:

```python
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
```

- [ ] **Step 2.2: Run tests — verify they FAIL**

```bash
pytest tests/test_server_config.py -v -k "workflow_timeout"
```

Expected: `FAILED` with `AttributeError: module 'config.settings' has no attribute 'RAG_WORKFLOW_DEFAULT_TIMEOUT_MS'`.

---

- [ ] **Step 2.3: Add `RAG_WORKFLOW_DEFAULT_TIMEOUT_MS` to `config/settings.py`**

Inside the `# --- Server ---` block, after `RAG_API_CORS_ORIGINS`:

```python
RAG_WORKFLOW_DEFAULT_TIMEOUT_MS = int(
    os.environ.get("RAG_WORKFLOW_DEFAULT_TIMEOUT_MS", "120000")
)
```

- [ ] **Step 2.4: Run settings parsing tests — verify they PASS**

```bash
pytest tests/test_server_config.py -v -k "workflow_timeout"
```

Expected: both parsing tests PASS.

---

- [ ] **Step 2.5: Write failing tests for startup validation**

The validation function accepts `workflow_timeout_ms` as a parameter so tests can pass explicit values directly — no module reload needed.

Add to `tests/test_server_config.py`:

```python
# ---------------------------------------------------------------------------
# _validate_startup_config — validation logic
# ---------------------------------------------------------------------------

def test_validate_startup_config_passes_with_valid_value():
    """Valid positive timeout must not raise."""
    from server.api import _validate_startup_config
    _validate_startup_config(workflow_timeout_ms=120000)  # must not raise


def test_validate_startup_config_rejects_zero():
    """Zero timeout must raise ValueError."""
    from server.api import _validate_startup_config
    with pytest.raises(ValueError, match="RAG_WORKFLOW_DEFAULT_TIMEOUT_MS"):
        _validate_startup_config(workflow_timeout_ms=0)


def test_validate_startup_config_rejects_negative():
    """Negative timeout must raise ValueError."""
    from server.api import _validate_startup_config
    with pytest.raises(ValueError, match="RAG_WORKFLOW_DEFAULT_TIMEOUT_MS"):
        _validate_startup_config(workflow_timeout_ms=-1000)
```

- [ ] **Step 2.6: Run validation tests — verify they FAIL**

```bash
pytest tests/test_server_config.py -v -k "validate_startup"
```

Expected: `FAILED` with `ImportError` — `_validate_startup_config` does not exist yet.

---

- [ ] **Step 2.7: Add `_validate_startup_config` to `server/api.py` and update `lifespan`**

**Import block** — this extends the block written in Task 1 (Step 1.7). Add `RAG_WORKFLOW_DEFAULT_TIMEOUT_MS`. The full cumulative block after this step:

```python
from config.settings import (
    TEMPORAL_TARGET_HOST,
    RAG_API_MAX_INFLIGHT_REQUESTS,
    RAG_API_OVERLOAD_QUEUE_TIMEOUT_MS,
    RAG_API_CORS_ORIGINS,
    RAG_WORKFLOW_DEFAULT_TIMEOUT_MS,
    RATE_LIMIT_ENABLED,
    RATE_LIMIT_REQUESTS_PER_MINUTE,
    RATE_LIMIT_WINDOW_SECONDS,
)
```

**Add validation function** — insert after `API_PORT = int(os.environ.get("RAG_API_PORT", "8000"))` (line 80) and before `def _enforce_rate_limit` (line 83):

```python
def _validate_startup_config(
    workflow_timeout_ms: int = RAG_WORKFLOW_DEFAULT_TIMEOUT_MS,
) -> None:
    """Raise ValueError for config values that would cause silent misbehaviour."""
    if workflow_timeout_ms <= 0:
        raise ValueError(
            f"RAG_WORKFLOW_DEFAULT_TIMEOUT_MS must be a positive integer, "
            f"got {workflow_timeout_ms!r}. "
            "Set RAG_WORKFLOW_DEFAULT_TIMEOUT_MS to a value > 0 (milliseconds)."
        )
```

**Update `lifespan`** — add `_validate_startup_config()` as the first line of the function body (before `global _temporal_client`). Full lifespan after this step:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    _validate_startup_config()
    global _temporal_client
    logger.info("Connecting to Temporal at %s", TEMPORAL_TARGET_HOST)
    _temporal_client = await Client.connect(TEMPORAL_TARGET_HOST)
    logger.info("API server ready — queries route through Temporal to preloaded workers")
    try:
        yield
    finally:
        if _temporal_client is not None:
            await _temporal_client.close()
            _temporal_client = None
        logger.info("API server shutting down")
```

- [ ] **Step 2.8: Run validation tests — verify they PASS**

```bash
pytest tests/test_server_config.py -v -k "validate_startup"
```

Expected: all 3 validation tests PASS.

---

- [ ] **Step 2.9: Write failing static wire-up test for `server/workflows.py`**

Add to `tests/test_server_config.py`:

```python
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
```

- [ ] **Step 2.10: Run wire-up test — verify it FAILS**

```bash
pytest tests/test_server_config.py::test_workflow_timeout_not_hardcoded -v
```

Expected: `FAILED` — `120000` still present.

---

- [ ] **Step 2.11: Update `server/workflows.py` — import constant and replace hardcoded fallback**

**Add import** after the existing imports at the top of `server/workflows.py`:

```python
from config.settings import RAG_WORKFLOW_DEFAULT_TIMEOUT_MS
```

**Replace hardcoded fallback** (line 35):

```python
# Before
timeout_ms = int(request.get("overall_timeout_ms", 120000))

# After
timeout_ms = int(request.get("overall_timeout_ms", RAG_WORKFLOW_DEFAULT_TIMEOUT_MS))
```

- [ ] **Step 2.12: Run all tests — verify they PASS**

```bash
pytest tests/test_server_config.py -v
```

Expected: all 12 tests PASS.

Run the broader suite to confirm no regressions (skip live-service integration tests):

```bash
pytest tests/ -v --ignore=tests/test_vector_store_integration.py --ignore=tests/test_rag_chain_integration.py -x
```

Expected: all non-integration tests PASS.

---

- [ ] **Step 2.13: Commit**

```bash
git add config/settings.py server/api.py server/workflows.py tests/test_server_config.py
git commit -m "feat: make workflow default timeout configurable via RAG_WORKFLOW_DEFAULT_TIMEOUT_MS"
```

---

## Summary

| Task | Tests | Files changed |
|------|-------|--------------|
| 1 — CORS origins | 6 tests | `config/settings.py`, `server/api.py`, `tests/test_server_config.py` |
| 2 — Workflow timeout | 6 tests | `config/settings.py`, `server/api.py`, `server/workflows.py`, `tests/test_server_config.py` |

**Total: ~10 lines of production code, 12 tests, 2 commits.**
