# Auto-Research Changelog — Container Image Optimization

**Branch**: `autoresearch/container-2026-04-10`
**Run started**: 2026-04-10
**Stop reason**: Target reached (API < 500 MB AND Runtime < 3 GB)

## Final Score

Two tables — the first is what the auto-research scoring metric saw (`docker inspect .Size`, single-platform slice), the second is ground truth (`podman images`, true on-disk size as measured after the run). **Deltas in both tables are valid; absolute values in the first are under-reported by roughly 2–3×** due to how `docker inspect` measures single-platform image slices without BuildKit provenance attestations.

### As scored during the run (`docker inspect .Size`)

| Image | Baseline | Final | Reduction |
|---|---|---|---|
| **API** | 3,197 MB | **115 MB** | **−96.4%** (−3,082 MB) |
| **Runtime** | 3,205 MB | **2,926 MB** | **−8.7%** (−279 MB) |
| **Total** | **6,402 MB** | **3,041 MB** | **−52.5%** (−3,361 MB) |

### True on-disk size (`podman images`, measured after the run)

| Image | Baseline | Final | Reduction |
|---|---|---|---|
| **API** | 6.65 GB | **389 MB** | **−94%** (−6.26 GB) |
| **Runtime** | 6.65 GB | **5.79 GB** | **−13%** (−0.86 GB) |
| **Combined** | **~13.3 GB** | **~6.18 GB** | **−54%** (−7.12 GB) |

Baseline was effectively one monolithic image built from `pip install .`, so both services shared the same ~6.65 GB layout. The dominant win is the API split — it no longer contains torch/docling/transformers. The worker still carries full torch (kept for GPU inference) but benefits from the multi-stage build, cache/test stripping, and removal of curl + build-essential from the runtime layer.

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

## Post-run follow-ups (manual, after auto-research stopped)

### 1. BuildKit pip cache mounts — **re-added** (commit `992c37d`)
Discarded by the size-only metric in iter-007, but re-added manually after the run because the rebuild-speed benefit is substantial when deps change. `RUN --mount=type=cache,target=/root/.cache/pip` now lives in both builder stages.

### 2. Podman verification — **done**
Both images build cleanly with `podman build --format docker -f ...` on podman 4.9.3. `--format docker` is used to preserve `HEALTHCHECK` directives if ever re-added (podman's default OCI format silently drops them). See `make container-build-podman`.

### 3. HEALTHCHECK moved to docker-compose.yml (commit `900348b`)
Because podman OCI drops `HEALTHCHECK`, the check was moved to the compose file where both `docker-compose` and `podman-compose` respect it identically. The check uses Python stdlib `urllib.request` so no curl is needed inside the image.

## Intentionally rejected

### CPU-only torch
The worker image is still dominated by `torch` (~1.5 GB of CUDA libraries bundled in the default wheel). Switching to `torch --index-url https://download.pytorch.org/whl/cpu` would shave another 1–1.5 GB off the runtime image, but the user confirmed that **GPU inference is required** for embedding and reranking models. Full torch stays in `requirements-worker.txt`.

## Build time observations

- Cold baseline build: ~9 min per image
- Iter-004 (post dep-split) warm rebuild: ~30 sec for API
- Iter-006 (+.dockerignore) fully cached rebuild: **1.6 sec** for both images
- Iter-009 cold rebuild of builder: ~8 min (torch re-install), runtime stage: ~3 min
