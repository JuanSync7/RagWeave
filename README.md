<!-- @summary
RAG platform with modular ingestion, retrieval/query serving, and Temporal-based
multi-user API orchestration. Includes engineering docs, onboarding guides, and
operations tooling for observability, backup/restore, and scaling.
@end-summary -->

# RAG

An end-to-end Retrieval-Augmented Generation system with modular ingestion, multi-tenant retrieval, and Temporal-orchestrated API serving.

## Quick Start

### Prerequisites

- **Python 3.10+** (3.12 recommended)
- **[uv](https://docs.astral.sh/uv/)** — fast Python package manager
- **Node.js 18+** and **npm** — for the web console TypeScript build
- **Docker** and **Docker Compose** (or **Podman** and **podman-compose**) — for infrastructure services (Temporal, Redis)
- **[Ollama](https://ollama.com/)** — for local LLM inference (or set `RAG_LLM_*` vars for cloud providers)

> **Podman users**: Podman is supported as a drop-in replacement for Docker.
> See [Podman Setup](#podman-setup) below for one-time configuration.

### 1. Clone and install Python dependencies

```bash
git clone <repo-url> && cd RAG
uv venv
uv pip install -e ".[dev]"
```

This creates a `.venv/`, installs all runtime dependencies plus dev tools (pytest, etc.).

> **Alternative** (pip only): `python -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"`

#### Optional dependency groups

Some features require extra packages that are not installed by default:

```bash
uv pip install -e ".[pii]"          # PII detection (presidio, spacy)
uv pip install -e ".[gliner]"       # GLiNER entity extraction
uv pip install -e ".[chromadb]"     # ChromaDB vector store
uv pip install -e ".[pinecone]"     # Pinecone vector store
uv pip install -e ".[qdrant]"       # Qdrant vector store
uv pip install -e ".[all]"          # All optional dependencies
```

### 2. Build the web console

```bash
make console-install   # npm install for TypeScript deps
make console-build     # compiles src/main.ts → static/main.js
```

Or directly:

```bash
npm --prefix server/console/web install
npm --prefix server/console/web run build
```

### 3. Start infrastructure services

```bash
./scripts/compose.sh up -d
```

This starts the core services: **Temporal** (orchestration) + **Temporal UI** (port 8080).
The `compose.sh` wrapper auto-detects Docker or Podman — no configuration needed.

Redis starts automatically when you use the `app` or `workers` profiles (see below).

### 4. Configure environment

```bash
cp .env.example .env
# Edit .env with your settings (LLM provider, API keys, etc.)
```

Key settings:

| Variable | Default | Description |
|----------|---------|-------------|
| `RAG_LLM_MODEL` | `ollama/qwen2.5:3b` | LiteLLM model string (`ollama/...`, `openai/...`, `anthropic/...`) |
| `RAG_LLM_API_BASE` | `http://localhost:11434` | Base URL for local models (Ollama) |
| `RAG_LLM_API_KEY` | (empty) | API key for cloud providers (OpenAI, Anthropic) |

See [.env.example](.env.example) for the full list.

### 5. Pull an Ollama model (if using local LLM)

```bash
ollama pull qwen2.5:3b
```

### 6. Run

```bash
# Activate the virtual environment
source .venv/bin/activate

# Ingest documents
python ingest.py --dir ./documents

# Query locally (no server needed)
python query.py "What is RAG?"

# Or use the interactive CLI
python cli.py
```

## Running the API Server

For multi-user / production use, run the API server with Temporal workers:

```bash
# Terminal 1: Start API server
source .venv/bin/activate
uvicorn server.api:app --host 0.0.0.0 --port 8000

# Terminal 2: Start Temporal worker
source .venv/bin/activate
python -m server.worker
```

Or use Docker/Podman profiles for a fully containerized stack:

```bash
./scripts/compose.sh --profile app --profile workers up -d
# Scale workers: ./scripts/compose.sh --profile workers up -d --scale rag-worker=3
```

Then use the CLI client or web console:

```bash
# CLI client (targets the API server)
python -m server.cli_client

# Web console: open http://localhost:8000/console
```

## Running Tests

```bash
source .venv/bin/activate
pytest                    # full suite
pytest tests/ingest/ -v   # ingestion tests only
```

## Container Profiles

| Profile | Services | Use Case |
|---------|----------|----------|
| *(default)* | Temporal + Temporal UI | Local development (run API/worker in terminals) |
| `app` | + API server + Redis | Containerized API |
| `workers` | + Temporal worker(s) + Redis | Containerized workers |
| `monitoring` | + Prometheus, Grafana, Alertmanager, Dozzle | Observability stack |
| `observability` | + Langfuse (full stack) | LLM tracing and evaluation |
| `gateway` | + nginx HTTPS reverse proxy | TLS termination for `rag-api` |

```bash
# Example: full production stack with monitoring
./scripts/compose.sh --profile app --profile workers --profile monitoring up -d
```

## HTTPS Gateway (nginx)

Add HTTPS support in front of the API server using nginx:

### One-time setup

```bash
# 1. Install mkcert
sudo apt install mkcert          # Debian/Ubuntu
# brew install mkcert             # macOS

# 2. Generate locally-trusted certs
./scripts/generate-certs.sh

# 3. Add hostname to /etc/hosts
echo "127.0.0.1  aion.local" | sudo tee -a /etc/hosts
```

### Start with HTTPS

```bash
./scripts/compose.sh --profile app --profile gateway up -d
# Browse: https://aion.local
```

The `gateway` profile requires the `app` profile. See `certs/README.md` for details.

> **Security note:** When the gateway is active, port 8000 remains directly accessible (bypassing TLS). For LAN demos, set `RAG_API_HOST_PORT=127.0.0.1:8000` in `.env` to restrict direct access to localhost only.

### Internet access (Cloudflare Tunnel)

For demos on a different network, use [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) (free) to get a public HTTPS URL:

```bash
# Install (one-time)
sudo apt install cloudflared          # Debian/Ubuntu
# brew install cloudflared             # macOS

# Start a quick tunnel pointing to your local nginx
cloudflared tunnel --url https://localhost:443 --no-tls-verify
```

This prints a public URL like `https://random-name.trycloudflare.com` — share it with anyone. Kill with Ctrl+C when done.

## Podman Setup

Podman is supported as a rootless, daemonless alternative to Docker. One-time setup:

```bash
# 1. Install Podman
sudo apt-get install -y podman podman-compose   # Debian/Ubuntu

# 2. Enable user socket (needed for Dozzle log viewer)
systemctl --user enable --now podman.socket

# 3. Verify rootless mode
podman info | grep -i rootless   # should show: rootless: true

# 4. Set the container socket in .env
echo "CONTAINER_SOCK=\$XDG_RUNTIME_DIR/podman/podman.sock" >> .env

# 5. Use compose.sh as normal — it auto-detects Podman
./scripts/compose.sh --profile app up -d
```

See `docs/operations/PODMAN_SPEC.md` for full details.

## Model Cache (Containerized Workers)

Containerized workers expect embedding/reranker models mounted at `/models`. Set `RAG_MODEL_ROOT` to your local model directory:

```bash
export RAG_MODEL_ROOT=/path/to/your/models
./scripts/compose.sh --profile workers up -d
```

Default model paths inside the container:
- Embeddings: `/models/baai/bge-m3`
- Reranker: `/models/baai/bge-reranker-v2-m3`

## Overview

This repository contains:

- A modular **13-node ingestion workflow** (`src/ingest/`) for document-to-vector/KG processing
- A **retrieval and query-serving runtime** (`src/retrieval/`, `server/`) with Temporal orchestration
- Tenant-aware **conversation memory** (Redis-backed) with sliding-window + rolling-summary context management
- **Platform modules** for auth, limits, observability, and caching (`src/platform/`)
- **LiteLLM SDK integration** for provider-agnostic LLM access (Ollama, OpenAI, Anthropic, etc.)
- Operations and architecture documentation (`docs/`)

### Architecture (Runtime)

```text
Users/CLI -> FastAPI (server/api.py) -> Temporal workflow -> Worker activity
                                                    |
                                                    v
                                          RAGChain singleton
                                  (retrieval, reranking, optional generation)
```

Ingestion runs separately and writes processed content/embeddings consumed by retrieval.

### Ingestion Source Identity

The ingestion pipeline uses stable source identity metadata instead of filename-only matching:

- `source_key`: stable ingestion identity for manifest and update cleanup.
- `source_id`: immutable connector-native document identifier.
- `source_uri`: canonical source location used for retrieval trace-back.

## Directory Map

| Directory | Purpose |
| --- | --- |
| `src/common/` | Cross-domain deterministic helpers reused across ingestion/retrieval features |
| `src/ingest/` | Modular ingestion pipeline (node-per-file, shared helpers, LangGraph workflow) |
| `src/retrieval/` | Query processing, retrieval orchestration, reranking, and generation |
| `src/platform/` | Cross-cutting platform services: auth, quotas/rate limits, cache, metrics, observability |
| `server/` | FastAPI/Temporal runtime: API, workflows, activities, worker, schemas, and CLI client |
| `config/` | Central environment-driven settings (`config/settings.py`) |
| `docs/` | Engineering guides, specs, operations runbooks, onboarding checklists |
| `tests/` | Unit/integration tests, including ingestion-focused tests in `tests/ingest/` |
| `scripts/` | Ops helpers (backup/restore, DR drill, tuning signal watcher, smoke test) |
| `prompts/` | Prompt templates for retrieval query processing |

## Entry Points

| Command | Description |
|---------|-------------|
| `python ingest.py --dir ./documents` | CLI for ingestion runs |
| `python query.py "question"` | Local retrieval query CLI |
| `python cli.py [query\|ingest]` | Unified interactive CLI |
| `python -m server.worker` | Temporal worker process |
| `uvicorn server.api:app --host 0.0.0.0 --port 8000` | API server |
| `python -m server.cli_client` | Interactive client targeting the API server |
| `python -m server.mcp_adapter` | MCP tooling adapter over the API (`stdio` transport) |

## Console UI Dev Shortcuts

```bash
make console-install    # npm install
make console-check      # TypeScript type-check (no emit)
make console-build      # compile TS → JS
make all-check          # full check (npm ci + py-compile + TS check)
```

## Engineering Docs

| Directory | Contents |
|-----------|----------|
| `docs/ingestion/` | Ingestion pipeline spec (split: pipeline nodes + platform/cross-cutting), implementation guide, engineering guide, onboarding checklist |
| `docs/retrieval/` | Retrieval pipeline specs (split: query/ranking + generation/safety), NeMo Guardrails, engineering guide, onboarding checklist |
| `docs/server/` | Server API spec + implementation, platform services spec (auth, tenancy, rate limits, caching) |
| `docs/ui/` | CLI spec + implementation, web console spec + implementation, token budget spec + implementation |
| `docs/performance/` | Retrieval performance spec (runtime controls, benchmarking, load testing) |
| `docs/operations/` | Operations platform spec (deployment, scaling, monitoring, DR, CI/CD), 100-user plan, Podman migration |
| `docs/llm/` | LiteLLM SDK integration guide |

Key starting points:
- Ingestion: `docs/ingestion/INGESTION_PIPELINE_ENGINEERING_GUIDE.md`
- Retrieval: `docs/retrieval/RETRIEVAL_ENGINEERING_GUIDE.md`
- Server/runtime: `server/README.md`

## License

See [LICENSE](LICENSE) for details.
