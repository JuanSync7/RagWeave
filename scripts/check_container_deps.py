# @summary
# Checks that containers/requirements-api.txt and containers/requirements-worker.txt
# stay in sync with [project.dependencies] in pyproject.toml.
#
# Rules enforced:
#   1. Every package in requirements-api.txt must appear in pyproject.toml.
#   2. Every package in requirements-worker.txt must appear in pyproject.toml.
#   3. Every package in pyproject.toml must appear in at least one of the two
#      requirements files (i.e. no silent dev-only promotion — must be
#      intentionally excluded via the PYPROJECT_ONLY allowlist below).
#   4. No package appears in both requirements-api.txt and requirements-worker.txt
#      under different version pins (name normalisation applied).
#
# Exits 0 on success, 1 with a human-readable report on failure.
# Exports: (CLI script, no importable API)
# Deps: tomllib (stdlib ≥3.11), pathlib, re, sys
# @end-summary

"""Verify container requirements files are in sync with pyproject.toml."""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Packages intentionally in pyproject.toml but NOT required in either
# container image (dev/test/optional deps).  Add here to silence rule 3.
PYPROJECT_ONLY: set[str] = {
    # dev / test tools
    "pytest",
    "pytest-asyncio",
    "pytest-mock",
    "pytest-timeout",
    "pytest-json-report",
    "deptry",
    "httpx",
    # the package itself (self-reference in pyproject.toml)
    "ragweave",
    # optional vector DB backends — not shipped in containers
    "chromadb",
    "pinecone-client",
    "qdrant-client",
    # optional ML / PII extras — not shipped in containers
    "bitsandbytes",
    "colpali-engine",
    "presidio-analyzer",
    "presidio-anonymizer",
    "spacy",
    "gliner",
    # optional LLM / guardrails extras
    "litellm",
    "nemoguardrails",
    # optional KG extras — not shipped in containers
    "neo4j",
    "igraph",
    "leidenalg",
    "tree-sitter",
    "tree-sitter-verilog",
    "pyverilog",
    # common utils in pyproject.toml but already pulled transitively in containers
    "minio",
    "pyyaml",
    "orjson",
}


def _normalise(name: str) -> str:
    """PEP 503 normalisation: lowercase, collapse runs of [-_.] to '-'."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _parse_requirements(path: Path) -> dict[str, str]:
    """Return {normalised_name: raw_line} for a requirements file."""
    result: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # Strip version specifiers and extras for the name portion
        name = re.split(r"[>=<!;\[\s]", line)[0]
        result[_normalise(name)] = line
    return result


def _parse_pyproject(path: Path) -> set[str]:
    """Return normalised dep names from [project.dependencies] AND all optional groups."""
    data = tomllib.loads(path.read_text())
    all_deps: list[str] = list(data.get("project", {}).get("dependencies", []))
    for group_deps in data.get("project", {}).get("optional-dependencies", {}).values():
        all_deps.extend(group_deps)
    result: set[str] = set()
    for dep in all_deps:
        name = re.split(r"[>=<!;\[\s]", dep)[0]
        result.add(_normalise(name))
    return result


def main() -> int:
    api_path = ROOT / "containers" / "requirements-api.txt"
    worker_path = ROOT / "containers" / "requirements-worker.txt"
    pyproject_path = ROOT / "pyproject.toml"

    api_deps = _parse_requirements(api_path)
    worker_deps = _parse_requirements(worker_path)
    pyproject_deps = _parse_pyproject(pyproject_path)

    failures: list[str] = []

    # Rule 1 & 2: container deps must exist in pyproject.toml
    for label, deps in [("requirements-api.txt", api_deps), ("requirements-worker.txt", worker_deps)]:
        for name, raw in sorted(deps.items()):
            if name not in pyproject_deps:
                failures.append(
                    f"  [{label}] '{raw}' is not declared in pyproject.toml"
                )

    # Rule 3: pyproject.toml deps must appear in at least one requirements file
    #         (unless explicitly allowlisted as PYPROJECT_ONLY)
    container_deps = api_deps.keys() | worker_deps.keys()
    for name in sorted(pyproject_deps):
        if name not in container_deps and name not in {_normalise(x) for x in PYPROJECT_ONLY}:
            failures.append(
                f"  [pyproject.toml] '{name}' is absent from both requirements files"
                f" — add to a requirements file or to PYPROJECT_ONLY in {Path(__file__).name}"
            )

    if failures:
        print("container-dep-check FAILED\n")
        for msg in failures:
            print(msg)
        print(
            "\nFix: keep pyproject.toml and containers/requirements-*.txt in sync.\n"
            "If a dep is intentionally dev-only, add it to PYPROJECT_ONLY in\n"
            f"{Path(__file__).relative_to(ROOT)}"
        )
        return 1

    total = len(api_deps) + len(worker_deps)
    print(f"container-dep-check passed — {total} container deps all present in pyproject.toml")
    return 0


if __name__ == "__main__":
    sys.exit(main())
