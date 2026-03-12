<!-- @summary
Production server setup: FastAPI + Temporal orchestration for multi-user RAG queries.
Models load once at worker startup; users get inference-only latency (~100-500ms).
@end-summary -->

# RAG Server — Production Multi-User Setup

## Architecture

```
Users → FastAPI Server → Temporal Server → Temporal Worker(s)
          (HTTP API)      (orchestration)    (RAGChain singleton,
                                              models in GPU memory)
```

**Key idea**: The 22s model-loading cost happens **once** when the worker boots (or the container starts). After that, every query runs inference against models already in memory.

## Components

| Component | File | What it does |
|-----------|------|--------------|
| **API Server** | `api.py` | Accepts HTTP requests, dispatches Temporal workflows. No GPU needed. |
| **Temporal Worker** | `worker.py` | Loads RAGChain at startup, processes query activities from the queue. |
| **Workflow** | `workflows.py` | Defines `RAGQueryWorkflow` with retry policy and timeouts. |
| **Activities** | `activities.py` | `execute_rag_query` — runs against the preloaded RAGChain singleton. |
| **CLI Client** | `cli_client.py` | Same REPL as `cli.py`, but talks to the API. Starts instantly. |
| **Schemas** | `schemas.py` | Pydantic models for API request/response validation. |

## Quick Start

### 1. Start Temporal (infrastructure)

```bash
# Option A: Docker Compose (recommended)
docker compose up -d

# Option B: Temporal CLI (lightweight, no Docker)
temporal server start-dev
```

### 2. Start the Worker (loads models once)

```bash
python -m server.worker
# ⏳ ~22s first time (loading embeddings + reranker into GPU memory)
# After that, the worker is ready to process queries
```

### 3. Start the API Server

```bash
uvicorn server.api:app --host 0.0.0.0 --port 8000
```

### 4. Query (pick one)

```bash
# Interactive CLI (same experience as cli.py, but instant startup)
python -m server.cli_client

# Or direct HTTP
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "What is retrieval-augmented generation?"}'

# Or browse the API docs
open http://localhost:8000/docs
```

## Managed Container Mode (Optional)

Run API and worker(s) as managed Docker services instead of hand-started terminals:

```bash
# Start Temporal + API + one worker container
docker compose --profile app --profile workers up -d

# Scale workers on the same Temporal task queue (rag-query)
docker compose --profile workers up -d --scale rag-worker=3
```

This stays true to production patterns:
- workers are long-running managed services/containers
- multiple replicas listen on the same `rag-query` queue
- Temporal load-balances activities across available workers
- each worker gets its own embedded Weaviate data directory inside the container

### Monitoring (Optional)

```bash
# Container log dashboard
docker compose --profile monitoring up -d
```

- **Dozzle logs UI**: http://localhost:9999
- **Temporal UI**: http://localhost:8080
- **API health**: http://localhost:8000/health

### Langfuse Observability UI (Optional)

Run self-hosted Langfuse under the `observability` profile:

```bash
docker compose --profile observability up -d
```

Open:
- **Langfuse UI**: http://localhost:3000
- **Prometheus**: http://localhost:9091
- **Grafana**: http://localhost:3001

Then point API/worker traces to this local Langfuse deployment:

```bash
export RAG_OBSERVABILITY_PROVIDER=langfuse
export LANGFUSE_HOST=http://localhost:3000
export LANGFUSE_PUBLIC_KEY=pk-local-dev
export LANGFUSE_SECRET_KEY=sk-local-dev
```

If you run `rag-api` and `rag-worker` via Docker Compose, pass the same env vars
into compose (for example in a local `.env` file) and start with:

```bash
docker compose --profile app --profile workers --profile observability up -d
```

## Current Setup

Your current local flow still works unchanged:

```bash
docker compose up -d
.venv/bin/python -m server.worker
.venv/bin/uvicorn server.api:app --host 0.0.0.0 --port 8000
.venv/bin/python -m server.cli_client
```

### Notes for Containerized Workers

- `rag-worker` expects Ollama on the host (`http://host.docker.internal:11434`).
- It seeds vector data from local `./.weaviate_data` into a per-container directory.
- If you re-run ingestion locally, restart worker containers so they pick up fresh seeded data.

## Scaling

```
                    ┌──── Worker 1 (GPU 0) ────┐
Users → LB → API →  │──── Worker 2 (GPU 1) ────│ ← Temporal routes to available workers
                    └──── Worker 3 (GPU 2) ────┘
```

- **Queue requests**: Single worker handles moderate load (~4 concurrent queries via thread pool)
- **Multiple replicas**: Run N workers on the same Temporal task queue for N× throughput
- **Batch inference**: Worker concurrency is configurable via `RAG_WORKER_CONCURRENCY`

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `RAG_TEMPORAL_TARGET_HOST` | `localhost:7233` | Temporal server address |
| `RAG_API_PORT` | `8000` | API server port |
| `RAG_API_URL` | `http://localhost:8000` | CLI client target (for `cli_client.py`) |
| `RAG_WORKER_CONCURRENCY` | `4` | Max concurrent activities per worker |
| `RAG_AUTH_API_KEYS_REQUIRED` | `false` | Enforce API-key/JWT auth at API boundary |
| `RAG_AUTH_API_KEYS_JSON` | `{}` | API-key map (`token_id -> {key, tenant_id, roles}`) |
| `RAG_AUTH_OIDC_ENABLED` | `false` | Enable OIDC bearer token validation (issuer/audience/JWKS) |
| `RAG_AUTH_OIDC_ISSUER` | `""` | Expected OIDC token issuer |
| `RAG_AUTH_OIDC_AUDIENCE` | `""` | Expected OIDC token audience |
| `RAG_AUTH_OIDC_JWKS_URL` | `""` | JWKS URL used to verify JWT signatures |
| `RAG_RATE_LIMIT_REQUESTS_PER_MINUTE` | `60` | Per-principal fixed-window rate limit |
| `RAG_CACHE_PROVIDER` | `memory` | Cache backend (`memory` or `redis`) |

## Admin API

These endpoints require an `admin` role:

- `GET /admin/api-keys`
- `POST /admin/api-keys`
- `DELETE /admin/api-keys/{key_id}`
- `GET /admin/quotas`
- `PUT /admin/quotas/{tenant_id}`
- `DELETE /admin/quotas/{tenant_id}`

## Monitoring

- **Temporal UI**: http://localhost:8080 — see all workflows, query history, latencies
- **FastAPI docs**: http://localhost:8000/docs — interactive API documentation
- **Health check**: `GET /health` — reports Temporal connectivity and worker status

### Tuning Watch Script

Use the tuning watcher to continuously evaluate scaling/concurrency signals and emit actionable recommendations:

```bash
# One-time snapshot
python scripts/watch_tuning_signals.py --once

# Continuous watch (every 30s)
python scripts/watch_tuning_signals.py --interval-seconds 30

# Send alerts to a webhook (Slack/Teams/etc.)
python scripts/watch_tuning_signals.py --webhook-url "https://example/webhook"
```

What it checks:

- Temporal schedule-to-start latency (query overridable via CLI arg)
- Temporal queue backlog (query overridable via CLI arg)
- API p95 latency from Prometheus (`rag_api_request_latency_ms`)
- Retrieval/generation p95 stage latencies (`rag_pipeline_stage_ms`)
- Worker CPU/memory pressure from `docker stats`
- GPU memory pressure from `nvidia-smi` (when available)
