<!-- @summary
Multi-modal RAG platform with pipeline-first ingestion, visual+text embeddings,
and graph-based orchestration. Includes engineering docs, onboarding guides, and
operations tooling for observability, backup/restore, and scaling.
@end-summary -->

<p align="center">
  <img src="assets/banners/04-woven-hexagon-mesh-animated.svg" alt="RagWeave — Multi-Modal RAG Platform" width="100%"/>
</p>

**RagWeave** is a production-grade, multi-modal Retrieval-Augmented Generation platform. It ingests documents of any format, builds dual-track text and visual embeddings, and serves grounded answers through a full retrieval-reranking-generation pipeline — with guardrails, observability, and confidence routing built in.

### What It Does

- **Ingests anything** — PDFs, DOCX, PPTX, HTML, Markdown, images, tables, and code. A 13-node LangGraph pipeline handles parsing (via Docling), structure detection, VLM figure captioning, text cleaning, semantic chunking, metadata extraction, knowledge graph triples, and quality validation.
- **Dual-track embeddings** — Text chunks are embedded with BGE-M3 (1024-dim dense vectors). Document pages are visually embedded with ColQwen2 (128-dim patch vectors via a 4-bit quantized Qwen2-VL backbone). Both tracks are stored in Weaviate and searched simultaneously at query time.
- **Hybrid retrieval + reranking** — Combines BM25 keyword search with dense vector search (configurable alpha blend), expands queries with knowledge graph terms, reranks with a BGE cross-encoder, and merges visual page results via ColQwen2 MaxSim scoring.
- **Confidence-aware generation** — A 3-signal composite score (retrieval confidence, LLM self-assessment, citation coverage) routes each answer to RETURN, RE_RETRIEVE, FLAG, or BLOCK — no silent hallucinations.
- **Full safety rails** — Input guardrails (intent classification, injection/jailbreak detection, PII redaction, toxicity filtering, topic safety) and output guardrails (faithfulness checking, hallucination detection) run in parallel with per-rail timeouts.
- **Provider-agnostic LLMs** — LiteLLM Router with named aliases (`default`, `vision`, `query`, `smart`, `fast`). Swap between Ollama, OpenAI, Anthropic, or any OpenAI-compatible endpoint via config alone.
- **Temporal orchestration** — Both ingestion and query serving run as durable Temporal workflows with independent retry policies. Workers scale horizontally.
- **Observability built in** — Langfuse LLM tracing, Prometheus metrics, Grafana dashboards, per-stage timing budgets, and token budget tracking per request.

### Key Strengths

| Strength | Detail |
|----------|--------|
| **True multi-modal** | Not just text — visual page embeddings let you search diagrams, charts, and layouts that text extraction misses |
| **Pipeline-first** | Every stage is a discrete LangGraph node with its own config toggle — add, skip, or replace any stage without touching the rest |
| **Swappable backends** | Abstract base classes for vector store, document store, guardrails, observability, and retry — implement the ABC, add one config branch |
| **Runs anywhere** | Local with Ollama + embedded Weaviate, or fully containerized with Docker/Podman profiles for app, workers, monitoring, and HTTPS gateway |
| **Battle-tested safety** | Defense-in-depth: regex + NeMo + LLM semantic classification for injection detection; Presidio + GLiNER for PII; claim-level hallucination scoring |
| **Multi-tenant ready** | JWT + API key auth, per-tenant Redis conversation memory with sliding window + rolling summary, rate limiting and quotas |

## Quick Start

### Prerequisites

- **Python 3.10+** (3.12 recommended)
- **[uv](https://docs.astral.sh/uv/)** — fast Python package manager
- **Node.js 18+** and **npm** — for the web console TypeScript build
- **Docker** and **Docker Compose** (or **Podman** and **podman-compose**) — for infrastructure services (Temporal, Redis)
- **[Ollama](https://ollama.com/)** — for local LLM inference (or set `RAG_LLM_*` vars for cloud providers)

> **Podman users**: Podman is supported as a drop-in replacement for Docker.
> See [Podman Setup](#podman-setup) below for one-time configuration.

### 1. Clone and set up the project

```bash
git clone <repo-url> && cd RAG
make setup
```

`make setup` runs the full one-shot: creates `.venv/`, installs all runtime + dev dependencies via `uv`, installs web-console npm deps, and compiles the TypeScript console. Run once per clone.

> Prefer explicit steps? `make install` does just the Python deps; `make console-install && make console-build` handles the console. Or skip `make` entirely:
> `uv venv && uv pip install -e ".[dev]"`, or `python -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"`.

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

### 2. Web console (already built by `make setup`)

`make setup` already installs and compiles the web console. You only need these targets when iterating on the TypeScript source:

```bash
make console-watch   # rebuild on change (live dev)
make console-check   # type-check only, no emit
make console-build   # one-shot production build
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
python -m src.ingest.cli --dir ./documents

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

# After code changes, rebuild + restart:
make restart        # app + workers
make restart-all    # all profiles (monitoring, gateway, etc.)
```

Then use the CLI client or web console:

```bash
# CLI client (targets the API server)
python -m server.cli_client

# User Console (chat):  open http://localhost:8000/console
# Admin Console (ops):  open http://localhost:8000/console/admin
```

## Running Tests

```bash
make test                          # full suite (uv run pytest)
make dep-check                     # deptry — unused / missing deps
make import-check                  # custom import_check module
make all-check                     # pre-commit bundle: npm ci + py-compile + TS check (NO tests)

# Targeted pytest invocations still work directly:
source .venv/bin/activate
pytest tests/ingest/ -v            # ingestion tests only
```

> `make all-check` intentionally does **not** run the pytest suite — it's the fast "will this compile?" gate. Run `make test` separately for the full suite.

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

## Container Images

The stack uses two images with strict dependency isolation (both measured with `podman images`):

| Image | Size | Baseline | Δ | Contents |
|---|---|---|---|---|
| `rag-api` | **389 MB** | 6.65 GB | **−94%** | FastAPI, Temporal client, Weaviate client — no torch, no docling, no ML stack |
| `rag-worker` | **5.79 GB** | 6.65 GB | **−13%** | Full ML stack (torch, sentence-transformers, docling, langchain, nemoguardrails) |

Baseline was a single monolithic image built from `pip install .`. The dominant win is the API split; the worker still carries full torch because GPU inference is required.

Dependencies live in `containers/requirements-api.txt` and `containers/requirements-worker.txt` — **not** in `pyproject.toml`. This is deliberate: `pip install .` would install every dep listed under `[project.dependencies]`, which undoes the isolation. Local dev still uses `pyproject.toml` via `make install`; containers bypass it.

**Adding a new dependency:**
- If the API server imports it → add to `pyproject.toml` AND `containers/requirements-api.txt`
- If only the worker uses it → add to `pyproject.toml` AND `containers/requirements-worker.txt`
- Dev-only (pytest, deptry, etc.) → `pyproject.toml` only

### Build the images

**With make (recommended):**

```bash
make container-build          # build both with docker (BuildKit)
make container-build-podman   # build both with podman (preferred for production)
make container-probe          # run API import probe — catches transitive ML leakage
make container-sizes          # show current image sizes
make container-clean          # remove local rag-api / rag-worker images
```

**Manual Docker:**

```bash
DOCKER_BUILDKIT=1 docker build -t rag-api    -f containers/Dockerfile.api .
DOCKER_BUILDKIT=1 docker build -t rag-worker -f containers/Dockerfile.runtime .
```

**Manual Podman:**

```bash
# --format docker preserves HEALTHCHECK directives if ever re-added to the Dockerfile
podman build --format docker -t rag-api    -f containers/Dockerfile.api .
podman build --format docker -t rag-worker -f containers/Dockerfile.runtime .
```

### Architecture notes

- **Multi-stage builds** — `build-essential` (gcc et al) lives in the builder stage only; the runtime stage copies just the installed `site-packages`. Saves ~170 MB per image.
- **BuildKit pip cache mounts** — `RUN --mount=type=cache,target=/root/.cache/pip` persists pip's wheel cache across rebuilds. Does not affect final image size but dramatically speeds up dep-change rebuilds (e.g. bumping torch version).
- **`.dockerignore`** — excludes `.venv/`, `tests/`, `evals/`, `docs/`, `node_modules/`, etc. Fully-cached rebuilds take ~1.5 seconds.
- **HEALTHCHECK lives in `docker-compose.yml`**, not in the Dockerfile — podman's default OCI image format drops `HEALTHCHECK` directives, and compose-level healthchecks work identically under both docker-compose and podman-compose.
- **Source code is on `PYTHONPATH=/app`**, so there's no `pip install .` step. Changing source doesn't invalidate the dep layer.
- **GPU inference is supported** in the worker image — full torch with bundled CUDA libs. To enable on the host: set `gpus: all` under `rag-worker` in `docker-compose.yml` and ensure the NVIDIA container runtime is installed.

Full optimization history (9-iteration auto-research run): [`docs/operations/DOCKER_OPTIMIZATION.md`](docs/operations/DOCKER_OPTIMIZATION.md)

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

## Make Targets

Run `make help` for this list in the terminal. All targets are also documented in comments in the [Makefile](Makefile) itself.

| Target | Purpose |
|---|---|
| **Setup & install** | |
| `make setup` | **First-time setup.** Creates venv, installs Python deps, runs `npm install`, builds the web console |
| `make install` | (Re)install Python deps into the active env (`uv pip install -e ".[dev]"`) |
| **Web console (TypeScript)** | |
| `make console-install` | `npm install` for the web console |
| `make console-check` | TypeScript type-check (no emit) |
| `make console-build` | Compile TS → `static/main.js` |
| `make console-watch` | Watch mode — rebuild on TS change |
| **Checks & tests** | |
| `make test` | Run the pytest suite |
| `make py-compile-check` | Smoke compile check on entry-point Python modules |
| `make dep-check` | Run `deptry` — detect unused / missing deps |
| `make import-check` | Run the custom `import_check` module |
| `make all-check` | Pre-commit bundle: `npm ci` + py-compile + console-check (does **not** run tests) |
| **Container images** (see [Container Images](#container-images) for details) | |
| `make container-build` | Build `rag-api` + `rag-worker` with docker (BuildKit) |
| `make container-build-api` | Build only `rag-api` |
| `make container-build-worker` | Build only `rag-worker` |
| `make container-build-podman` | Build both with podman (`--format docker`) |
| `make container-probe` | Run the API import probe inside `rag-api` — catches transitive ML leakage |
| `make container-sizes` | Print current `rag-api` / `rag-worker` image sizes |
| `make container-clean` | Remove local `rag-api` / `rag-worker` images |
| **Stack restart** (uses `scripts/restart_stack.sh` — auto-detects docker/podman) | |
| `make restart` | Restart `app` + `workers` profiles with rebuild |
| `make restart-all` | Restart all profiles with rebuild |

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
