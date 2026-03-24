<!-- @summary
Dockerfile definitions and nginx/cert configuration for the containerized API server (Dockerfile.api), worker runtime (Dockerfile.runtime), and HTTPS gateway (nginx.conf).
@end-summary -->

# containers

## Overview

This directory contains Dockerfile definitions and supporting configuration for building and running the RAG API server and worker as containers.

## Files

| File | Purpose |
| --- | --- |
| `Dockerfile.api` | API server image (FastAPI + platform dependencies, no GPU required). Used by the `rag-api` service. |
| `Dockerfile.runtime` | Worker runtime image (embeddings, reranker, GPU-capable). Used by the `rag-worker` service. |
| `nginx.conf` | nginx HTTPS reverse proxy configuration for the `gateway` compose profile. |
| `proxy_params.conf` | nginx proxy header pass-through parameters (forwarded IPs, request IDs). |
| `generate-certs.sh` | Certificate generation helper script for the nginx TLS setup (delegates to `scripts/generate-certs.sh`). |

## Image Build Context

Images are built and orchestrated via `docker-compose.yml` at the repo root. The build context is the repo root (not this directory), so Dockerfiles can `COPY` from anywhere in the project.

## Usage

```bash
# Build and start API + worker containers
./scripts/compose.sh --profile app --profile workers up -d

# Rebuild images after code changes
./scripts/compose.sh --profile app --profile workers up -d --build
```

See `docs/operations/PODMAN_SPEC.md` for Podman-specific setup and `README.md` for container profile reference.
