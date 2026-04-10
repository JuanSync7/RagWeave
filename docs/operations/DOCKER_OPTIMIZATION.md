# Container Image Optimization Guide

## Summary

The `containers/Dockerfile.api` and `containers/Dockerfile.runtime` were optimized from a combined **6,402 MB** down to **3,041 MB** (−52.5%), via auto-research on branch `autoresearch/container-2026-04-10`.

| Image | Before | After |
|---|---|---|
| `rag-api` | 3,197 MB | **115 MB** |
| `rag-worker` | 3,205 MB | **2,926 MB** |

Full experiment log: [`auto-research/container/research/iterations.tsv`](../../auto-research/container/research/iterations.tsv)
Full changelog: [`auto-research/container/research/changelog.md`](../../auto-research/container/research/changelog.md)

## What changed (user-facing)

### 1. Separate requirements files

Dependencies are now split across two files:
- **`containers/requirements-api.txt`** — 15 lightweight deps (fastapi, uvicorn, temporalio, redis, pyjwt, pydantic, prometheus-client, langfuse, litellm, minio, pyyaml, orjson, mcp, langdetect, weaviate-client). No torch/docling/transformers.
- **`containers/requirements-worker.txt`** — 23 deps including ML stack (torch, sentence-transformers, docling, langchain, nemoguardrails, etc.)

**`pyproject.toml` is unchanged** — local dev setup still uses `make install` / `make setup` and installs all deps in the venv. The requirements files are Docker-only.

**When to edit:**
- Adding a dep that the API server imports → add to `containers/requirements-api.txt` AND `pyproject.toml`
- Adding a dep that only the worker imports → add to `containers/requirements-worker.txt` AND `pyproject.toml`
- Adding a dev-only dep → only `pyproject.toml` (never goes into the containers)

### 2. Multi-stage Dockerfiles

Both Dockerfiles now have a `builder` stage (with `build-essential`) and a `runtime` stage (without). The runtime stage copies `/install` from the builder to `/usr/local`:

```
builder  → apt-get install build-essential → pip install --prefix=/install
           ↓
runtime  → python:3.11-slim-bookworm (no gcc) → COPY --from=builder /install /usr/local
```

### 3. `.dockerignore` at project root

Excludes `.venv/`, `tests/`, `evals/`, `docs/`, `auto-research/`, `node_modules/`, `ops/`, `scripts/`, `.runtime/`, `models/`, etc. from the build context. **Dramatic rebuild speedup**: fully-cached rebuilds now take ~1.6 seconds.

### 4. `__pycache__` and test-directory stripping

The builder stage removes `__pycache__/`, `tests/`, `*.pyc`, and `*.pyo` from `/install` before the runtime stage copies it. `PYTHONDONTWRITEBYTECODE=1` in the runtime env ensures they aren't regenerated.

### 5. No more `curl` in runtime layers

- API image: health check now uses Python stdlib `urllib.request` instead of `curl`
- Worker image: `curl` removed entirely (no HTTP healthcheck)

## How to build

### Docker

```bash
# API image
DOCKER_BUILDKIT=1 docker build -t rag-api -f containers/Dockerfile.api .

# Worker image
DOCKER_BUILDKIT=1 docker build -t rag-worker -f containers/Dockerfile.runtime .

# Or via docker-compose (unchanged)
./scripts/compose.sh --profile app --profile workers up -d --build
```

### Podman

Both Dockerfiles use only standard syntax (no Docker-specific extensions). Podman should work identically:

```bash
# API image
podman build -t rag-api -f containers/Dockerfile.api .

# Worker image
podman build -t rag-worker -f containers/Dockerfile.runtime .
```

If you rename the files to `Containerfile.*` (Podman convention), update the `-f` flag accordingly.

## Verifying the optimization

### Image size check
```bash
docker images rag-api rag-worker --format "table {{.Repository}}\t{{.Size}}"
```

Expected (approximate):
```
REPOSITORY    SIZE
rag-api       115MB
rag-worker    2.9GB
```

### Import probe (catches transitive ML leakage into API image)

```bash
docker run --rm --entrypoint python rag-api -c "from server.api import app; print('OK')"
```

If this prints `OK`, the API image has all deps it needs. If it fails with `ModuleNotFoundError`, add the missing package to `containers/requirements-api.txt` and rebuild.

## Known remaining gaps

### CPU-only torch (not applied)
The runtime image is still ~2.9 GB, dominated by `torch` with bundled CUDA libraries (~1.5 GB). If the worker is running on CPU only:

```bash
# Not applied automatically — requires user confirmation
pip install torch --index-url https://download.pytorch.org/whl/cpu
```

This was not applied during the auto-research run because the worker is designed to optionally use GPU (see `rag-worker` service comment in `docker-compose.yml`). Apply manually if you are certain no GPU path is used.

### BuildKit pip cache mounts (optional follow-up)
Adds `RUN --mount=type=cache,target=/root/.cache/pip pip install ...` in the builder stages. No size change, but rebuilds that add/change a dep will reuse cached wheels. Attempted in iteration 007 but discarded because the auto-research scoring metric is size-only. Good to add manually.

## Troubleshooting

### API image build fails with `ModuleNotFoundError: No module named 'X'`
Some module in `server/api.py` or its route imports needs a package not listed in `containers/requirements-api.txt`. The import probe will tell you which one. Add it to `requirements-api.txt` and rebuild.

### Worker image build fails on a compiled package
The builder stage has `build-essential`. If a new dep needs additional system libraries (e.g. `libpq-dev` for psycopg2), add them to the builder stage's `apt-get install` line — NOT the runtime stage.

### Runtime image is still too big
The biggest contributor is `torch`. Options:
1. Switch to CPU-only torch (see above)
2. Check if `nemoguardrails` is actually used — it has heavy transitive deps
3. Audit `requirements-worker.txt` for unused packages
