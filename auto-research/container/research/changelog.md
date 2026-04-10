# Auto-Research Changelog — Container Image Optimization

**Branch**: `autoresearch/container-2026-04-10`
**Run started**: 2026-04-10
**Stop reason**: Target reached (API < 500 MB AND Runtime < 3 GB)

## Final Score

| Image | Baseline | Final | Reduction |
|---|---|---|---|
| **API** | 3,197 MB | **115 MB** | **−96.4%** (−3,082 MB) |
| **Runtime** | 3,205 MB | **2,926 MB** | **−8.7%** (−279 MB) |
| **Total** | **6,402 MB** | **3,041 MB** | **−52.5%** (−3,361 MB) |

## Iterations Summary

| # | Commit | Direction | Status | Total MB | Saved |
|---|--------|-----------|--------|----------|-------|
| 001 | `5463e69` | baseline | keep | 6,402 | 0 |
| 002 | `b515047` | extras-based dep split | **discard** | 6,402 | 0 |
| 003 | `745e467` | requirements-api.txt | **crash** | — | — |
| 004 | `6e8eedb` | + weaviate-client fix | keep | 3,417 | 2,985 |
| 005 | `44804c2` | multi-stage builds | keep | 3,214 | 3,188 |
| 006 | `ae75a41` | .dockerignore | keep | 3,205 | 3,197 |
| 007 | `6176437` | BuildKit pip cache mounts | **discard** (tie) | 3,205 | 3,197 |
| 008 | `3e504b7` | drop curl from both images | keep | 3,198 | 3,204 |
| 009 | `cd5dbf0` | strip `__pycache__` + tests | keep | **3,041** | **3,361** |

## What Worked

### 1. Dep isolation via separate requirements files (iter-004) — **biggest win**
`pip install ".[api]"` with extras didn't work because pip installs `[project.dependencies]` core first regardless of the extras flag, making extras purely additive. The correct approach was:
- Create `containers/requirements-api.txt` (14 deps: fastapi, uvicorn, temporalio, redis, pyjwt, pydantic, prometheus-client, langfuse, litellm, minio, pyyaml, orjson, mcp, langdetect, **weaviate-client**)
- Create `containers/requirements-worker.txt` (23 deps: torch, sentence-transformers, transformers, docling, langchain, etc.)
- Dockerfiles `pip install -r` from those files — bypassing `pyproject.toml` core deps entirely
- Source code is importable via `PYTHONPATH=/app`, so no `pip install .` needed

**Impact**: API image dropped from 3,197 → 242 MB (92% reduction).

### 2. Multi-stage builds (iter-005)
Builder stage has `build-essential` + runs `pip install --prefix=/install`. Runtime stage is a fresh `python:3.11-slim-bookworm` with `COPY --from=builder /install /usr/local`. Build tools never enter the runtime layer.
**Impact**: API 242 → 144 MB, Runtime 3,175 → 3,070 MB (−203 MB total).

### 3. `.dockerignore` (iter-006)
Excluded `.venv/`, `tests/`, `docs/`, `evals/`, `auto-research/`, `node_modules/`, `.git/`, etc. Small direct size gain (9 MB) but **dramatic rebuild speed improvement**: cached rebuilds went from ~9 min to **~1.6 seconds**.

### 4. Drop curl (iter-008)
Replaced curl-based healthcheck with Python stdlib `urllib.request`. Removed curl from the worker image entirely (no HTTP healthcheck there). −7 MB total.

### 5. Strip `__pycache__`, `tests/`, `*.pyc` from installed packages (iter-009) — **final push**
Added `find /install -type d -name __pycache__ -prune -exec rm -rf {} +` (and for `tests`, `*.pyc`, `*.pyo`) to the builder stage before the runtime copy. `PYTHONDONTWRITEBYTECODE=1` ensures they aren't regenerated at runtime.
**Impact**: API 138 → 115 MB, Runtime 3,060 → 2,926 MB. **This is what crossed the 3 GB runtime target.**

## What Didn't Work

### Extras-based dep splitting (iter-002)
Adding `[project.optional-dependencies] api = [...]` to `pyproject.toml` and changing Dockerfile to `pip install ".[api]"` — **no effect**. Pip installs core deps first, then extras. Extras are additive, not restrictive.
**Lesson**: To split deps per-image without touching core, use separate requirements files.

### BuildKit pip cache mounts (iter-007)
Added `RUN --mount=type=cache,target=/root/.cache/pip pip install ...` — no change in final image size (as expected). Useful for rebuild speed when deps change, but not measurable by the size metric. **Recommended as a manual follow-up** (see "Remaining Gaps" below).

## Crashes

### iter-003: Import probe caught missing weaviate-client
First attempt at `requirements-api.txt` was missing `weaviate-client`. Import probe (`docker run --entrypoint python -c "from server.api import app"`) caught it immediately inside the container — build succeeded, import failed.
**Root cause**: `server/routes/documents.py` imports `src.vector_db` at module load time, which imports `weaviate`.
**Fix**: Added `weaviate-client` to `requirements-api.txt` (iter-004).
The probe mechanism worked exactly as designed — caught a transitive runtime dep without needing a healthcheck or running the full server.

## Remaining Gaps (recommended manual follow-ups)

### 1. BuildKit pip cache mounts (rejected in iter-007 due to scoring rules)
Not kept because the size metric didn't move, but this is a genuinely good change. Adds `--mount=type=cache,target=/root/.cache/pip` to both builder stages. Future rebuilds that add/change a dep will reuse cached wheels instead of re-downloading. Recommended for manual addition.

### 2. CPU-only torch (requires user decision)
The runtime image is still dominated by `torch` (~1.5 GB of CUDA libraries bundled in the default wheel). If the worker does not use GPU inference, switching to `torch --index-url https://download.pytorch.org/whl/cpu` would shave another 1-1.5 GB off the runtime image. **This was NOT attempted** because the worker is designed to optionally run with NVIDIA container runtime (see `docker-compose.yml` comment on `rag-worker`) and defaulting to CPU-only torch would break GPU inference.

### 3. Podman/OCI compatibility verification (Direction 6)
All changes use standard Dockerfile syntax (no Docker-specific extensions). Should work with `podman build -f containers/Dockerfile.api .` out of the box. Not explicitly verified during this run because Podman isn't installed in the current WSL2 environment. Recommended manual verification before shipping.

## Build time observations

- Cold baseline build: ~9 min per image
- Iter-004 (post dep-split) warm rebuild: ~30 sec for API
- Iter-006 (+.dockerignore) fully cached rebuild: **1.6 sec** for both images
- Iter-009 cold rebuild of builder: ~8 min (torch re-install), runtime stage: ~3 min
