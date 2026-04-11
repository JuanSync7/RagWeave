# @summary
# Root developer shortcuts for setup, console TypeScript, Python sanity checks, and testing.
# Exports: make targets
# Deps: npm, uv, server/console/web package scripts
# @end-summary

.PHONY: help install console-install console-check console-build console-watch \
        py-compile-check test dep-check import-check all-check setup restart restart-all \
        venv-doctor _venv-auto-heal \
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
	@echo "  venv-doctor        Check .venv health (detects stale shebangs after dir rename)"
	@echo ""
	@echo "Web console (TypeScript)"
	@echo "  console-install    npm install for the web console"
	@echo "  console-check      TypeScript type-check (no emit)"
	@echo "  console-build      Compile TS -> static/main.js"
	@echo "  console-watch      Watch mode — rebuild on TS change"
	@echo ""
	@echo "Static checks (3 layers — each catches a distinct bug class)"
	@echo "  py-compile-check   L1 syntax: compileall across src/ server/ config/ import_check/"
	@echo "  import-check       L2 internal: do 'from X import Y' resolve to real symbols?"
	@echo "  dep-check          L3 external: is pyproject.toml in sync with actual imports? (deptry)"
	@echo "  all-check          Pre-commit gate: L1 + L2 + L3 + npm ci + console-check (NO pytest)"
	@echo ""
	@echo "Tests"
	@echo "  test               Run the pytest suite (not included in all-check)"
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

# ---------------------------------------------------------------------------
# Virtual env health
#
# pip/uv install console scripts (deptry, pytest, uvicorn, ...) with an
# ABSOLUTE-path shebang pointing at the venv's python. If the project
# directory is renamed after setup, every console script in .venv/bin/
# silently breaks with "Permission denied" or "No such file or directory".
# The python interpreter itself (.venv/bin/python3 -> /usr/bin/python3 or
# similar) is a symlink and keeps working, which makes the failure mode
# confusing — `python ...` works but `pytest` / `deptry` / `uvicorn` don't.
#
# `venv-doctor` detects the mismatch by comparing a known console script's
# shebang to the current project path. `_venv-auto-heal` is the silent
# version used as an implicit dep by `setup` and `install` so repair is
# automatic on re-run. Neither touches .venv unless the mismatch is real.
# ---------------------------------------------------------------------------

# Verbose health check — prints either "ok" or a diagnosis.
venv-doctor:
	@if [ ! -d .venv ]; then \
		echo "venv-doctor: no .venv/ present — run 'make setup'"; exit 1; \
	elif [ ! -x .venv/bin/python3 ]; then \
		echo "venv-doctor: .venv/ exists but has no python3 — run 'rm -rf .venv && make setup'"; exit 1; \
	else \
		expected="$$(pwd)/.venv/bin/python3"; \
		for script in .venv/bin/pytest .venv/bin/pip .venv/bin/python3; do \
			if [ -f "$$script" ]; then \
				first="$$(head -c 2 $$script)"; \
				if [ "$$first" = "#!" ]; then \
					actual="$$(head -n 1 $$script | sed 's|^#!||')"; \
					if [ "$$actual" != "$$expected" ]; then \
						echo "venv-doctor: STALE venv detected"; \
						echo "  $$script shebang:   $$actual"; \
						echo "  expected:          $$expected"; \
						echo "  cause:             project directory was renamed after 'make setup'"; \
						echo "  fix:               rm -rf .venv && make setup"; \
						echo "                     (or: make install — auto-heals before reinstalling)"; \
						exit 1; \
					fi; \
					break; \
				fi; \
			fi; \
		done; \
		echo "venv-doctor: .venv/ healthy"; \
	fi

# Silent version used as a hidden dep of setup/install. Nukes and rebuilds
# .venv ONLY when a stale shebang is detected — no-op on a healthy venv.
_venv-auto-heal:
	@if [ -d .venv ] && [ -f .venv/bin/pip ]; then \
		expected="$$(pwd)/.venv/bin/python3"; \
		actual="$$(head -n 1 .venv/bin/pip | sed 's|^#!||')"; \
		if [ "$$actual" != "$$expected" ]; then \
			echo ">>> Stale venv detected (shebang points to $$actual)"; \
			echo ">>> Removing .venv/ so it can be recreated at $$expected"; \
			rm -rf .venv; \
		fi; \
	fi

# Full project setup (Python + TypeScript). Auto-heals a stale venv first.
setup: _venv-auto-heal
	uv venv
	uv pip install -e ".[dev]"
	$(MAKE) console-install
	$(MAKE) console-build
	@echo "\n✓ Setup complete. Activate with: source .venv/bin/activate"

# (Re)install Python deps into the active env. Auto-heals a stale venv
# first so `make install` after a directory rename Just Works.
install: _venv-auto-heal
	@if [ ! -d .venv ]; then uv venv; fi
	uv pip install -e ".[dev]"

console-install:
	npm --prefix server/console/web install

console-check:
	npm --prefix server/console/web run check

console-build:
	npm --prefix server/console/web run build

console-watch:
	npm --prefix server/console/web run watch

# ---------------------------------------------------------------------------
# Static checks & tests
#
# Three Python checks that stack in layers — each catches a distinct bug class:
#
#   py-compile-check  Layer 1: does every .py parse as valid Python syntax?
#                     (python -m compileall, fast, skips unchanged files)
#   import-check      Layer 2: do project-internal `from X import Y` statements
#                     resolve to real symbols? Catches stale imports after
#                     refactors and encapsulation violations.
#   dep-check         Layer 3: is pyproject.toml in sync with actual third-party
#                     imports? (deptry — unused/missing/misplaced deps)
#
# `all-check` is the pre-commit gate that runs all of the above plus the web
# console type-check. It does NOT run the pytest suite — use `make test` for
# that (intentional split: pre-commit should stay fast).
# ---------------------------------------------------------------------------

# Layer 1: syntax-only check on the whole source tree. compileall is fast
# because it skips .py files whose cached .pyc is already current.
py-compile-check:
	uv run python -m compileall -q src server config import_check

test:
	uv run pytest

# Layer 3: deptry verifies pyproject.toml matches actual imports.
# Invoked via `python -m deptry` instead of the deptry console script so it
# survives venv-path rot (e.g. directory renames that break cached shebangs).
dep-check:
	uv run python -m deptry .

# Layer 2: internal import resolution + encapsulation violations.
import-check:
	uv run python -m import_check

# Pre-commit gate. Every fast static check, NO pytest.
# Order: cheap -> expensive so failures surface the lowest-level issue first.
all-check:
	$(MAKE) py-compile-check
	$(MAKE) import-check
	$(MAKE) dep-check
	npm --prefix server/console/web ci
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
