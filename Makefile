# @summary
# Root developer shortcuts for setup, console TypeScript, Python sanity checks, and testing.
# Exports: make targets
# Deps: npm, uv, server/console/web package scripts
# @end-summary

.PHONY: help install console-install console-check console-build console-watch \
        py-compile-check test dep-check import-check all-check setup restart restart-all \
        container-build container-build-api container-build-worker \
        container-build-podman container-probe container-sizes container-clean

# Default target: print the help menu when `make` is run with no arguments.
.DEFAULT_GOAL := help

# ---------------------------------------------------------------------------
# Help
#
# Grouped listing of targets. Keep this in sync with README.md's
# "Make Targets" section — both derive from the same Makefile.
# ---------------------------------------------------------------------------
help:
	@echo ""
	@echo "RagWeave — developer make targets"
	@echo ""
	@echo "Setup & install"
	@echo "  setup              Full one-shot setup: venv + deps + console install + build"
	@echo "  install            (Re)install Python deps into the active env (editable + dev extras)"
	@echo ""
	@echo "Web console (TypeScript)"
	@echo "  console-install    npm install for the web console"
	@echo "  console-check      TypeScript type-check (no emit)"
	@echo "  console-build      Compile TS -> static/main.js"
	@echo "  console-watch      Watch mode — rebuild on TS change"
	@echo ""
	@echo "Checks & tests"
	@echo "  test               Run the pytest suite"
	@echo "  py-compile-check   Smoke compile check on entry-point Python modules"
	@echo "  dep-check          Run deptry (unused / missing deps)"
	@echo "  import-check       Run the custom import_check module"
	@echo "  all-check          Pre-commit bundle: npm ci + py-compile + console-check (NO tests)"
	@echo ""
	@echo "Container lifecycle (docker or podman — auto-detected)"
	@echo "  container-build         Build rag-api + rag-worker with docker (BuildKit)"
	@echo "  container-build-api     Build only rag-api"
	@echo "  container-build-worker  Build only rag-worker"
	@echo "  container-build-podman  Build both with podman (--format docker)"
	@echo "  container-probe         Run the API import probe inside rag-api"
	@echo "  container-sizes         Print current rag-api / rag-worker image sizes"
	@echo "  container-clean         Remove local rag-api / rag-worker images"
	@echo ""
	@echo "Stack restart (uses scripts/restart_stack.sh — auto-detects docker/podman)"
	@echo "  restart            Restart app + workers with rebuild"
	@echo "  restart-all        Restart all profiles with rebuild"
	@echo ""

# Full project setup (Python + TypeScript)
setup:
	uv venv
	uv pip install -e ".[dev]"
	$(MAKE) console-install
	$(MAKE) console-build
	@echo "\n✓ Setup complete. Activate with: source .venv/bin/activate"

install:
	uv pip install -e ".[dev]"

console-install:
	npm --prefix server/console/web install

console-check:
	npm --prefix server/console/web run check

console-build:
	npm --prefix server/console/web run build

console-watch:
	npm --prefix server/console/web run watch

py-compile-check:
	uv run python -m py_compile server/api.py server/activities.py src/retrieval/pipeline/rag_chain.py

test:
	uv run pytest

dep-check:
	uv run deptry .

import-check:
	uv run python -m import_check

all-check:
	npm --prefix server/console/web ci
	$(MAKE) py-compile-check
	$(MAKE) console-check

restart:
	./scripts/restart_stack.sh --app --workers --build

restart-all:
	./scripts/restart_stack.sh --all --build

# ---------------------------------------------------------------------------
# Container images
#
# Two images are built from separate dependency lists (see containers/):
#   - rag-api      ~390 MB  (fastapi, temporalio, weaviate — no ML stack)
#   - rag-worker    ~5.8 GB  (torch, docling, transformers — full ML stack)
#
# Dependencies are tracked in containers/requirements-{api,worker}.txt, NOT
# in pyproject.toml. Local dev uses pyproject.toml via `make install`;
# containers bypass it for strict dep isolation. When adding a new dep:
#   - API-side import → add to pyproject.toml AND containers/requirements-api.txt
#   - Worker-side    → add to pyproject.toml AND containers/requirements-worker.txt
# ---------------------------------------------------------------------------

# Default: build both images with Docker (BuildKit enabled)
container-build: container-build-api container-build-worker container-sizes

container-build-api:
	DOCKER_BUILDKIT=1 docker build -t rag-api -f containers/Dockerfile.api .

container-build-worker:
	DOCKER_BUILDKIT=1 docker build -t rag-worker -f containers/Dockerfile.runtime .

# Build with Podman instead of Docker. Passes --format docker so HEALTHCHECK
# directives are preserved if ever re-added (the compose-level healthcheck
# works regardless of image format).
container-build-podman:
	podman build --format docker -t rag-api    -f containers/Dockerfile.api .
	podman build --format docker -t rag-worker -f containers/Dockerfile.runtime .
	@$(MAKE) container-sizes

# Run the import probe inside the built API image. Catches any transitive
# ML/torch dep leakage after dep-split changes. Detects docker vs podman.
container-probe:
	@if command -v docker >/dev/null 2>&1; then \
		docker run --rm --entrypoint python rag-api \
			-c "from server.api import app; print('[probe] API import OK')"; \
	elif command -v podman >/dev/null 2>&1; then \
		podman run --rm --entrypoint python rag-api \
			-c "from server.api import app; print('[probe] API import OK')"; \
	else \
		echo "neither docker nor podman found"; exit 1; \
	fi

# Print current image sizes (podman reports actual disk usage, docker
# underreports via .Size but shows true sum via 'images').
container-sizes:
	@echo "=== Image sizes ==="
	@if command -v podman >/dev/null 2>&1; then \
		podman images --format "  {{.Repository}}:{{.Tag}}\t{{.Size}}" | grep -E "rag-(api|worker)" || true; \
	fi
	@if command -v docker >/dev/null 2>&1; then \
		docker images --format "  {{.Repository}}:{{.Tag}}\t{{.Size}}" | grep -E "rag-(api|worker)" || true; \
	fi

# Remove locally-built rag-api / rag-worker images from both engines
container-clean:
	-docker rmi rag-api rag-worker 2>/dev/null || true
	-podman rmi rag-api rag-worker 2>/dev/null || true
