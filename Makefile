# @summary
# Root developer shortcuts for setup, console TypeScript, Python sanity checks, and testing.
# Exports: make targets
# Deps: npm, uv, server/console/web package scripts
# @end-summary

.PHONY: install console-install console-check console-build console-watch \
        py-compile-check test dep-check import-check all-check setup restart restart-all \
        container-build container-build-api container-build-worker \
        container-build-podman container-probe container-sizes container-clean

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
