# @summary
# Static validation tests for project configuration, dependency declarations,
# README installation instructions, and environment-driven config usage.
# Verifies that pyproject.toml and requirements.txt stay in sync, all third-party
# imports are declared, ports/URLs are configurable via env vars, and README
# documents installation steps.
# Exports: TestDependencyCompleteness, TestRequirementsTxtSync, TestReadmeInstallation,
#          TestConfigNotHardcoded, TestDockerfileBuildDeps
# Deps: pytest, pathlib, re, ast, tomllib
# @end-summary
"""
Static project configuration tests.

These tests verify file contents and structure — no runtime dependencies needed.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Standard library modules (Python 3.10+) — not third-party
_STDLIB_MODULES = frozenset({
    "__future__", "abc", "aifc", "argparse", "array", "ast", "asyncio",
    "atexit", "base64", "binascii", "bisect", "builtins", "bz2",
    "calendar", "cgi", "cgitb", "chunk", "cmath", "cmd", "code",
    "codecs", "codeop", "collections", "colorsys", "compileall",
    "concurrent", "configparser", "contextlib", "contextvars", "copy",
    "copyreg", "cProfile", "csv", "ctypes", "curses", "dataclasses",
    "datetime", "dbm", "decimal", "difflib", "dis", "distutils",
    "doctest", "email", "encodings", "enum", "errno", "faulthandler",
    "fcntl", "filecmp", "fileinput", "fnmatch", "fractions",
    "ftplib", "functools", "gc", "getopt", "getpass", "gettext",
    "glob", "graphlib", "grp", "gzip", "hashlib", "heapq", "hmac",
    "html", "http", "idlelib", "imaplib", "imghdr", "importlib",
    "inspect", "io", "ipaddress", "itertools", "json", "keyword",
    "lib2to3", "linecache", "locale", "logging", "lzma", "mailbox",
    "mailcap", "marshal", "math", "mimetypes", "mmap", "modulefinder",
    "multiprocessing", "netrc", "nis", "nntplib", "numbers",
    "operator", "optparse", "os", "ossaudiodev", "pathlib", "pdb",
    "pickle", "pickletools", "pipes", "pkgutil", "platform",
    "plistlib", "poplib", "posix", "posixpath", "pprint",
    "profile", "pstats", "pty", "pwd", "py_compile", "pyclbr",
    "pydoc", "queue", "quopri", "random", "re", "readline",
    "reprlib", "resource", "rlcompleter", "runpy", "sched",
    "secrets", "select", "selectors", "shelve", "shlex", "shutil",
    "signal", "site", "smtpd", "smtplib", "sndhdr", "socket",
    "socketserver", "spwd", "sqlite3", "ssl", "stat", "statistics",
    "string", "stringprep", "struct", "subprocess", "sunau",
    "symtable", "sys", "sysconfig", "syslog", "tabnanny", "tarfile",
    "telnetlib", "tempfile", "termios", "test", "textwrap",
    "threading", "time", "timeit", "tkinter", "token", "tokenize",
    "tomllib", "trace", "traceback", "tracemalloc", "tty", "turtle",
    "turtledemo", "types", "typing", "unicodedata", "unittest",
    "urllib", "uu", "uuid", "venv", "warnings", "wave", "weakref",
    "webbrowser", "winreg", "winsound", "wsgiref", "xdrlib", "xml",
    "xmlrpc", "zipapp", "zipfile", "zipimport", "zlib",
    # Internal/private
    "_thread", "_io", "_collections_abc", "_csv", "typing_extensions",
})

# Mapping from pyproject.toml package name -> importable module name(s)
_PYPROJECT_IMPORT_MAP: dict[str, set[str]] = {
    "weaviate-client": {"weaviate"},
    "sentence-transformers": {"sentence_transformers"},
    "transformers": {"transformers"},
    "torch": {"torch"},
    "networkx": {"networkx"},
    "langchain-core": {"langchain_core"},
    "langchain-text-splitters": {"langchain_text_splitters"},
    "langgraph": {"langgraph"},
    "numpy": {"numpy"},
    "temporalio": {"temporalio"},
    "langfuse": {"langfuse"},
    "fastapi": {"fastapi", "starlette"},  # starlette is a fastapi sub-dependency
    "uvicorn": {"uvicorn"},
    "pydantic": {"pydantic"},
    "accelerate": {"accelerate"},
    "prometheus-client": {"prometheus_client"},
    "redis": {"redis"},
    "pyjwt": {"jwt"},
    "mcp": {"mcp"},
    "docling": {"docling"},
    "nemoguardrails": {"nemoguardrails"},
    "litellm": {"litellm"},
    "pyyaml": {"yaml"},
    "orjson": {"orjson"},
    # Dev deps
    "pytest": {"pytest"},
    "pytest-mock": {"pytest_mock"},
}

# All importable names that pyproject.toml covers
_DECLARED_IMPORTS = frozenset(
    name for names in _PYPROJECT_IMPORT_MAP.values() for name in names
)

# Optional dependencies that are conditionally/lazily imported inside functions.
# These are NOT required at install time — they are loaded only when specific
# features are enabled (e.g., GLiNER entity extraction, PII detection, alt vector stores).
_OPTIONAL_IMPORTS = frozenset({
    "chromadb", "pinecone", "qdrant_client",  # alternative vector stores (query.py)
    "gliner",                                  # entity extraction (src/core/knowledge_graph.py)
    "presidio_analyzer", "presidio_anonymizer", "spacy",  # PII detection (src/guardrails/pii.py)
})

# Root-level scripts that are importable but not third-party packages
_LOCAL_ROOT_MODULES = frozenset({"ingest", "query", "cli", "colang_demo"})


@pytest.fixture
def project_root() -> Path:
    return PROJECT_ROOT


@pytest.fixture
def pyproject_text(project_root: Path) -> str:
    return (project_root / "pyproject.toml").read_text()


@pytest.fixture
def requirements_text(project_root: Path) -> str:
    return (project_root / "requirements.txt").read_text()


@pytest.fixture
def readme_text(project_root: Path) -> str:
    return (project_root / "README.md").read_text()


@pytest.fixture
def settings_text(project_root: Path) -> str:
    return (project_root / "config" / "settings.py").read_text()


@pytest.fixture
def env_example_text(project_root: Path) -> str:
    return (project_root / ".env.example").read_text()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_pyproject_deps(text: str) -> list[str]:
    """Extract dependency names from pyproject.toml dependencies list."""
    deps: list[str] = []
    in_deps = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("dependencies = ["):
            in_deps = True
            continue
        if in_deps:
            if stripped == "]":
                break
            # Extract bare package name from "package>=version",
            match = re.match(r'"([a-zA-Z0-9_-]+)', stripped)
            if match:
                deps.append(match.group(1).lower())
    return deps


def _parse_requirements_deps(text: str) -> list[str]:
    """Extract dependency names from requirements.txt."""
    deps: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = re.match(r"([a-zA-Z0-9_-]+)", stripped)
        if match:
            deps.append(match.group(1).lower())
    return deps


def _collect_third_party_imports(source_dirs: list[Path]) -> set[str]:
    """Walk Python files and return top-level third-party import names."""
    third_party: set[str] = set()
    local_prefixes = {"src", "server", "config", "tests"}

    for source_dir in source_dirs:
        if not source_dir.exists():
            continue
        py_files = list(source_dir.rglob("*.py"))
        for py_file in py_files:
            try:
                tree = ast.parse(py_file.read_text(), filename=str(py_file))
            except SyntaxError:
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        top = alias.name.split(".")[0]
                        if top not in _STDLIB_MODULES and top not in local_prefixes:
                            third_party.add(top)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        top = node.module.split(".")[0]
                        if top not in _STDLIB_MODULES and top not in local_prefixes:
                            third_party.add(top)
    return third_party


# =========================================================================
# Test Class A: Dependency Completeness
# =========================================================================

class TestDependencyCompleteness:
    """Verify that all third-party imports have matching pyproject.toml entries."""

    def test_all_imports_are_declared(self, project_root: Path):
        """Every third-party import in src/server/config/scripts should be
        covered by a pyproject.toml dependency (direct or transitive)."""
        source_dirs = [
            project_root / "src",
            project_root / "server",
            project_root / "config",
            project_root / "scripts",
        ]
        # Also check root-level .py files
        root_py = list(project_root.glob("*.py"))
        # We handle root .py files by adding them to a temp set
        third_party = _collect_third_party_imports(source_dirs)

        # Root-level .py files
        for py_file in root_py:
            try:
                tree = ast.parse(py_file.read_text(), filename=str(py_file))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        top = alias.name.split(".")[0]
                        if top not in _STDLIB_MODULES and top not in {"src", "server", "config", "tests"}:
                            third_party.add(top)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        top = node.module.split(".")[0]
                        if top not in _STDLIB_MODULES and top not in {"src", "server", "config", "tests"}:
                            third_party.add(top)

        undeclared = third_party - _DECLARED_IMPORTS - _OPTIONAL_IMPORTS - _LOCAL_ROOT_MODULES
        assert not undeclared, (
            f"Third-party imports not covered by pyproject.toml: {sorted(undeclared)}. "
            "Add them to [project.dependencies] or update _PYPROJECT_IMPORT_MAP."
        )

    def test_pyproject_has_python_version(self, pyproject_text: str):
        """pyproject.toml should declare a minimum Python version."""
        assert "requires-python" in pyproject_text

    def test_pyproject_has_build_system(self, pyproject_text: str):
        """pyproject.toml should declare a build system."""
        assert "[build-system]" in pyproject_text


# =========================================================================
# Test Class B: requirements.txt ↔ pyproject.toml Sync
# =========================================================================

class TestRequirementsTxtSync:
    """Verify requirements.txt stays in sync with pyproject.toml."""

    def test_requirements_matches_pyproject(
        self, pyproject_text: str, requirements_text: str
    ):
        """Every dependency in pyproject.toml should appear in requirements.txt."""
        pyproject_deps = set(_parse_pyproject_deps(pyproject_text))
        req_deps = set(_parse_requirements_deps(requirements_text))
        missing_from_req = pyproject_deps - req_deps
        assert not missing_from_req, (
            f"Dependencies in pyproject.toml but missing from requirements.txt: "
            f"{sorted(missing_from_req)}"
        )

    def test_requirements_no_extras_vs_pyproject(
        self, pyproject_text: str, requirements_text: str
    ):
        """requirements.txt should not list dependencies absent from pyproject.toml."""
        pyproject_deps = set(_parse_pyproject_deps(pyproject_text))
        req_deps = set(_parse_requirements_deps(requirements_text))
        extra_in_req = req_deps - pyproject_deps
        assert not extra_in_req, (
            f"Dependencies in requirements.txt but not in pyproject.toml: "
            f"{sorted(extra_in_req)}"
        )

    def test_requirements_has_header_comment(self, requirements_text: str):
        """requirements.txt should document that it mirrors pyproject.toml."""
        first_line = requirements_text.splitlines()[0].lower()
        assert "pyproject" in first_line, (
            "requirements.txt should reference pyproject.toml in its header comment"
        )


# =========================================================================
# Test Class C: README Installation Instructions
# =========================================================================

class TestReadmeInstallation:
    """Verify README.md has complete installation/setup instructions."""

    def test_readme_has_prerequisites_section(self, readme_text: str):
        """README should list prerequisites."""
        assert re.search(r"#+\s+Prerequisites", readme_text), (
            "README.md should have a 'Prerequisites' section"
        )

    def test_readme_mentions_python_version(self, readme_text: str):
        """README should specify the minimum Python version."""
        assert re.search(r"Python\s+3\.1[0-9]", readme_text), (
            "README.md should specify a Python version requirement (3.10+)"
        )

    def test_readme_has_install_command(self, readme_text: str):
        """README should include pip or uv install command."""
        has_pip = "pip install" in readme_text
        has_uv = "uv pip install" in readme_text or "uv venv" in readme_text
        assert has_pip or has_uv, (
            "README.md should include a pip or uv install command"
        )

    def test_readme_mentions_env_setup(self, readme_text: str):
        """README should tell users to copy .env.example."""
        assert ".env.example" in readme_text, (
            "README.md should reference .env.example for environment setup"
        )

    def test_readme_has_compose_start_command(self, readme_text: str):
        """README should show how to start infrastructure services."""
        assert "compose.sh" in readme_text or "compose" in readme_text.lower(), (
            "README.md should show how to start container services"
        )

    def test_readme_has_run_section(self, readme_text: str):
        """README should have a section for running the application."""
        has_run = re.search(r"#+\s+(Run|Quick Start|Getting Started)", readme_text)
        assert has_run, "README.md should have a 'Run' or 'Quick Start' section"

    def test_readme_documents_container_profiles(self, readme_text: str):
        """README should document available container profiles."""
        assert "profile" in readme_text.lower() and (
            "app" in readme_text and "workers" in readme_text
        ), "README.md should document container profiles (app, workers, etc.)"

    def test_readme_has_test_instructions(self, readme_text: str):
        """README should include instructions for running tests."""
        assert "pytest" in readme_text, (
            "README.md should include test running instructions (pytest)"
        )

    def test_readme_documents_podman_setup(self, readme_text: str):
        """README should have Podman setup instructions."""
        assert re.search(r"(?i)podman\s+setup", readme_text), (
            "README.md should have a Podman setup section"
        )

    def test_readme_entry_points_match_actual_files(self, project_root: Path, readme_text: str):
        """Entry point files referenced in README should exist."""
        expected_files = ["ingest.py", "query.py", "cli.py"]
        for filename in expected_files:
            filepath = project_root / filename
            if filename in readme_text:
                assert filepath.exists(), (
                    f"README references '{filename}' but the file does not exist"
                )


# =========================================================================
# Test Class D: Config Not Hardcoded
# =========================================================================

class TestConfigNotHardcoded:
    """Verify that ports and URLs in source code use config/env, not hardcoded values."""

    def test_settings_ports_from_env(self, settings_text: str):
        """config/settings.py should read port numbers from environment variables."""
        # These port variables should use os.environ.get
        port_vars = ["RAG_API_PORT", "RAG_OLLAMA_PORT", "RAG_REDIS_PORT", "RAG_TEMPORAL_PORT"]
        for var in port_vars:
            assert var in settings_text, (
                f"config/settings.py should reference env var {var}"
            )

    def test_settings_urls_from_env(self, settings_text: str):
        """config/settings.py should build URLs from env vars, not hardcode them."""
        url_vars = ["RAG_API_URL", "RAG_OLLAMA_URL", "RAG_CACHE_REDIS_URL", "RAG_TEMPORAL_TARGET_HOST"]
        for var in url_vars:
            assert var in settings_text, (
                f"config/settings.py should reference env var {var}"
            )

    def test_settings_uses_environ_get(self, settings_text: str):
        """config/settings.py should use os.environ.get for configuration."""
        count = settings_text.count("os.environ.get")
        assert count >= 20, (
            f"config/settings.py uses os.environ.get only {count} times — "
            "expected at least 20 for full env-driven config"
        )

    def test_api_port_from_env(self, project_root: Path):
        """server/api.py should read API port from environment, not hardcode it."""
        api_text = (project_root / "server" / "api.py").read_text()
        assert "os.environ.get" in api_text or "RAG_API_PORT" in api_text, (
            "server/api.py should read port from environment variable"
        )

    def test_cli_client_url_from_env(self, project_root: Path):
        """server/cli_client.py should read server URL from environment."""
        cli_text = (project_root / "server" / "cli_client.py").read_text()
        assert "RAG_API_URL" in cli_text or "RAG_API_PORT" in cli_text, (
            "server/cli_client.py should read API URL/port from environment"
        )

    def test_no_hardcoded_localhost_urls_in_source(self, project_root: Path):
        """Source files should not hardcode localhost URLs without env var fallback.

        We check that any http://localhost:NNNN pattern appears within an
        os.environ.get() call or f-string with a config variable.
        Skips comments and docstrings."""
        source_dirs = [project_root / "src", project_root / "server"]
        violations: list[str] = []

        url_pattern = re.compile(r'http://localhost:\d{4,5}')
        env_pattern = re.compile(r'os\.environ\.get|f".*\{.*\}|f\'.*\{.*\}')

        for source_dir in source_dirs:
            for py_file in source_dir.rglob("*.py"):
                source = py_file.read_text()
                lines = source.splitlines()

                # Use AST to find docstring line ranges to skip
                docstring_lines: set[int] = set()
                try:
                    tree = ast.parse(source, filename=str(py_file))
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                            for ln in range(node.lineno, node.end_lineno + 1):
                                docstring_lines.add(ln)
                except SyntaxError:
                    continue

                for i, line in enumerate(lines, 1):
                    stripped = line.strip()
                    # Skip comments and docstrings
                    if stripped.startswith("#") or i in docstring_lines:
                        continue
                    if url_pattern.search(line) and not env_pattern.search(line):
                        violations.append(f"{py_file.relative_to(project_root)}:{i}")

        assert not violations, (
            f"Hardcoded localhost URLs found without env var fallback:\n"
            + "\n".join(f"  {v}" for v in violations)
        )

    def test_env_example_has_all_port_vars(self, env_example_text: str):
        """'.env.example' should document all port variables."""
        expected_ports = [
            "RAG_API_PORT",
            "RAG_API_HOST_PORT",
            "RAG_OLLAMA_PORT",
            "RAG_REDIS_PORT",
            "RAG_TEMPORAL_PORT",
            "RAG_TEMPORAL_UI_PORT",
        ]
        for var in expected_ports:
            assert var in env_example_text, (
                f".env.example should document {var}"
            )

    def test_env_example_has_derived_urls(self, env_example_text: str):
        """.env.example should show derived URL variables."""
        expected_urls = ["RAG_API_URL", "RAG_LLM_API_BASE"]
        for var in expected_urls:
            assert var in env_example_text, (
                f".env.example should document {var}"
            )


# =========================================================================
# Test Class E: Dockerfile Build Dependencies
# =========================================================================

class TestDockerfileBuildDeps:
    """Verify Dockerfiles install necessary build tools for pip install."""

    def test_api_dockerfile_has_pip_install(self, project_root: Path):
        """Dockerfile.api should install Python dependencies via pip."""
        text = (project_root / "containers" / "Dockerfile.api").read_text()
        assert "pip install" in text, "Dockerfile.api should install pip dependencies"

    def test_runtime_dockerfile_has_pip_install(self, project_root: Path):
        """Dockerfile.runtime should install Python dependencies via pip."""
        text = (project_root / "containers" / "Dockerfile.runtime").read_text()
        assert "pip install" in text, "Dockerfile.runtime should install pip dependencies"

    def test_api_dockerfile_copies_pyproject(self, project_root: Path):
        """Dockerfile.api should copy pyproject.toml for dependency installation."""
        text = (project_root / "containers" / "Dockerfile.api").read_text()
        assert "pyproject.toml" in text, (
            "Dockerfile.api should COPY pyproject.toml for pip install"
        )

    def test_runtime_dockerfile_copies_pyproject(self, project_root: Path):
        """Dockerfile.runtime should copy pyproject.toml for dependency installation."""
        text = (project_root / "containers" / "Dockerfile.runtime").read_text()
        assert "pyproject.toml" in text, (
            "Dockerfile.runtime should COPY pyproject.toml for pip install"
        )

    def test_api_dockerfile_has_curl(self, project_root: Path):
        """Dockerfile.api should install curl for health checks."""
        text = (project_root / "containers" / "Dockerfile.api").read_text()
        assert "curl" in text, "Dockerfile.api should install curl for HEALTHCHECK"

    def test_api_dockerfile_uses_env_for_port(self, project_root: Path):
        """Dockerfile.api should use RAG_API_PORT env var, not hardcode port."""
        text = (project_root / "containers" / "Dockerfile.api").read_text()
        assert "RAG_API_PORT" in text, (
            "Dockerfile.api should use RAG_API_PORT environment variable"
        )
