# @summary
# Root developer shortcuts for setup, console TypeScript, Python sanity checks, and testing.
# Exports: make targets
# Deps: npm, uv, server/console/web package scripts
# @end-summary

.PHONY: install console-install console-check console-build console-watch \
        py-compile-check test all-check setup

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
	uv run python -m py_compile server/api.py server/activities.py src/retrieval/rag_chain.py

test:
	uv run pytest

all-check:
	npm --prefix server/console/web ci
	$(MAKE) py-compile-check
	$(MAKE) console-check
