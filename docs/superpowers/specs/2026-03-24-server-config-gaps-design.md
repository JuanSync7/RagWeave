# Server Config Gap Fixes — Design

**Date:** 2026-03-24
**Status:** Approved
**Scope:** Two targeted config-wiring changes to close hardcoded-value gaps found in the server API audit.

---

## Problem

Two server values are hardcoded and cannot be changed without a code edit:

1. `server/api.py` — CORS `allow_origins` is always `["*"]`
2. `server/workflows.py` — workflow default timeout is always `120000` ms

Both values should be controllable via environment variables, consistent with how every other server config is handled in `config/settings.py`.

> **Confirmed non-gaps (from audit):**
> - Cache TTL: `_cache.set()` already falls back to `CACHE_TTL_SECONDS` from settings — no change needed.
> - MCP adapter: `server/mcp_adapter.py` is fully implemented with `health`, `query`, and admin tools.

---

## Approach

All config lives in `config/settings.py` with `os.environ.get(VAR, default)` — the established project pattern. Each affected file imports from settings rather than reading the environment directly.

---

## Change 1 — CORS Origins

### `config/settings.py`

Add inside the `# --- Server ---` block (after `RAG_API_OVERLOAD_QUEUE_TIMEOUT_MS`, line ~186):

```python
RAG_API_CORS_ORIGINS: list[str] = [
    o.strip()
    for o in os.environ.get("RAG_API_CORS_ORIGINS", "*").split(",")
    if o.strip()
] or ["*"]
```

- Default: `"*"` → `["*"]` — identical to current runtime behavior.
- Operators set `RAG_API_CORS_ORIGINS=http://localhost:3000,https://myapp.com` for production lockdown.
- The `or ["*"]` guard prevents an empty list if the env var is set to empty or whitespace.
- **Note:** `allow_credentials=True` is incompatible with `allow_origins=["*"]` in Starlette/FastAPI. If credential-carrying requests are needed in future, a separate code change to add `allow_credentials=True` will also be required (out of scope here).

### `server/api.py`

1. Add `RAG_API_CORS_ORIGINS` to the `from config.settings import (...)` block.
2. Replace `allow_origins=["*"]` with `allow_origins=RAG_API_CORS_ORIGINS`.

---

## Change 2 — Workflow Default Timeout

### `config/settings.py`

Add inside the `# --- Server ---` block alongside the other `RAG_API_*` settings:

```python
RAG_WORKFLOW_DEFAULT_TIMEOUT_MS = int(
    os.environ.get("RAG_WORKFLOW_DEFAULT_TIMEOUT_MS", "120000")
)
```

- Default: `120000` ms — identical to current runtime behavior.
- Operators can lower this (e.g., `60000`) for tighter SLO enforcement or raise it for heavy workloads.
- **Validation:** The value must be a positive integer. A value of `0` or negative would be clamped to 1 second by `max(1, math.ceil(...))` in `workflows.py` — a silent misconfiguration. The settings module should assert `RAG_WORKFLOW_DEFAULT_TIMEOUT_MS > 0` and raise a `ValueError` with a clear message on startup if violated.

### `server/workflows.py`

1. Import `RAG_WORKFLOW_DEFAULT_TIMEOUT_MS` from `config.settings`.
2. Replace the hardcoded fallback:

```python
# Before
timeout_ms = int(request.get("overall_timeout_ms", 120000))

# After
timeout_ms = int(request.get("overall_timeout_ms", RAG_WORKFLOW_DEFAULT_TIMEOUT_MS))
```

Per-request `overall_timeout_ms` continues to override the default when provided.

---

## Files Touched

| File | Change |
|------|--------|
| `config/settings.py` | Add `RAG_API_CORS_ORIGINS` and `RAG_WORKFLOW_DEFAULT_TIMEOUT_MS` |
| `server/api.py` | Import + use `RAG_API_CORS_ORIGINS` |
| `server/workflows.py` | Import + use `RAG_WORKFLOW_DEFAULT_TIMEOUT_MS` |

**~5 lines of code total. No behavior change at runtime with default values.**

---

## Acceptance Criteria

- `RAG_API_CORS_ORIGINS` unset → behavior identical to today (`["*"]`).
- `RAG_API_CORS_ORIGINS=http://localhost:3000` → CORS restricted to that origin.
- `RAG_API_CORS_ORIGINS=http://a.com,http://b.com` → both origins accepted.
- `RAG_API_CORS_ORIGINS=` (empty string) or `RAG_API_CORS_ORIGINS=  ` (whitespace) → falls back to `["*"]`.
- `RAG_WORKFLOW_DEFAULT_TIMEOUT_MS` unset → workflow timeout unchanged (`120000` ms).
- `RAG_WORKFLOW_DEFAULT_TIMEOUT_MS=60000` → workflows time out at 60 s by default.
- `RAG_WORKFLOW_DEFAULT_TIMEOUT_MS=0` or negative → startup raises `ValueError` with a clear message.
- Per-request `overall_timeout_ms` still overrides the default.
- No ML imports added to `server/api.py`.
