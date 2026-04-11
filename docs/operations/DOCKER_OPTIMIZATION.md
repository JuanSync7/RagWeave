# Container Image Optimization Guide

## Summary

`containers/Dockerfile.api` and `containers/Dockerfile.runtime` were optimized via a 10-iteration auto-research run on branch `autoresearch/container-2026-04-10`. The biggest single win was **splitting dependencies** so the API image no longer contains torch/docling/transformers.

### Final sizes (measured with `podman images`, which reports true on-disk size)

| Image | Baseline | Final | Reduction |
|---|---|---|---|
| `rag-api` | 6.65 GB | **389 MB** | **−6.26 GB (−94%)** |
| `rag-worker` | 6.65 GB | **5.79 GB** | **−0.86 GB (−13%)** |
| **Combined** | **~13.3 GB** | **~6.18 GB** | **−7.12 GB (−54%)** |

Baseline was a single monolithic image layout (`pip install .` pulled every dep including torch into both images). The dominant win is the API split — it no longer contains torch/docling/transformers/nemoguardrails. The worker still carries full torch (required for GPU inference) but benefits from multi-stage build, cache/test stripping, and no curl.

> **A note on measurement**: The auto-research run used `docker inspect --format='{{.Size}}'` as its metric, which reports a single-platform image slice (no BuildKit provenance attestations) and came in much smaller than the actual disk image. The iteration-by-iteration **deltas** in `iterations.tsv` remain accurate relative measurements, but the absolute numbers there understate the true on-disk size by 2–3×.
>
> `podman images` is the most honest absolute measurement — it reports layer content without attestation overhead, and matches what a deployment host will actually pull and store. Use it for reality checks.

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

- API image: healthcheck moved to `docker-compose.yml` (uses Python stdlib `urllib.request`). Podman's default OCI image format drops `HEALTHCHECK` directives, so keeping it in compose is the portable location.
- Worker image: `curl` removed entirely (no HTTP healthcheck needed — Temporal handles worker liveness)

### 6. BuildKit pip cache mounts

Both builder stages use `RUN --mount=type=cache,target=/root/.cache/pip pip install ...`. Pip's wheel cache is persisted across builds via BuildKit's cache store. Does not affect final image size but speeds up rebuilds dramatically when a dep is added or upgraded — no need to re-download ~2 GB of torch wheels.

## How to build

### Via make (recommended)

```bash
make container-build          # build both with docker (BuildKit enabled)
make container-build-podman   # build both with podman
make container-probe          # run the API import probe
make container-sizes          # list current image sizes
make container-clean          # remove local images from both engines
```

### Manual Docker

```bash
DOCKER_BUILDKIT=1 docker build -t rag-api    -f containers/Dockerfile.api .
DOCKER_BUILDKIT=1 docker build -t rag-worker -f containers/Dockerfile.runtime .

# Or via compose (unchanged)
./scripts/compose.sh --profile app --profile workers up -d --build
```

### Manual Podman

```bash
# --format docker preserves HEALTHCHECK directives if ever re-added to the Dockerfile.
# Without it podman defaults to OCI format and silently drops HEALTHCHECK.
podman build --format docker -t rag-api    -f containers/Dockerfile.api .
podman build --format docker -t rag-worker -f containers/Dockerfile.runtime .
```

The Dockerfiles use only standard syntax (no Docker-specific extensions) and build identically under both engines.

## Verifying the optimization

### Image size check

Preferred: **`podman images`** — shows true on-disk size without BuildKit attestation overhead.

```bash
podman images --format "table {{.Repository}}\t{{.Size}}" | grep rag-
```

Expected (approximate, podman):
```
rag-api     ~390 MB
rag-worker  ~5.8 GB
```

If using docker: **`docker images`** shows virtual size (includes BuildKit attestations), while `docker inspect --format='{{.Size}}'` returns a much smaller single-platform slice. Both are "correct" depending on what you're measuring — use `docker images` for comparison with `podman images`.

### Import probe (catches transitive ML leakage into API image)

```bash
make container-probe
# or manually:
docker run --rm --entrypoint python rag-api -c "from server.api import app; print('OK')"
podman run --rm --entrypoint python rag-api -c "from server.api import app; print('OK')"
```

If this prints `OK`, the API image has all deps it needs. If it fails with `ModuleNotFoundError`, add the missing package to `containers/requirements-api.txt` and rebuild.

## Design decisions (confirmed)

### GPU inference is required → keep full torch
The worker uses GPU inference for embedding and reranking models. Full torch (with bundled CUDA runtime libraries, ~1.5 GB) stays in `requirements-worker.txt`. CPU-only torch (`--index-url https://download.pytorch.org/whl/cpu`) was considered and rejected because it would break GPU inference paths.

### Healthcheck in docker-compose, not Dockerfile
Podman's default OCI image format drops `HEALTHCHECK` directives with a warning. Moving the check to `docker-compose.yml` makes it work identically under both `docker-compose` and `podman-compose`, regardless of image format. The check uses Python stdlib `urllib.request` (no curl dependency needed inside the container).

### BuildKit pip cache mounts are in the Dockerfiles
Attempted in auto-research iter-007 and discarded by the size-only metric (cache mounts don't affect final image size). Re-added manually afterward because the rebuild-speed benefit is significant when adding/upgrading deps.

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
