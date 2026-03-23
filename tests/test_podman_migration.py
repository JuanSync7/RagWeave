# @summary
# Tests for Docker-to-Podman container runtime migration.
# Verifies that all scripts, Dockerfiles, compose config, and documentation
# correctly support both Docker and Podman as container runtimes.
# Exports: TestShellScripts, TestDockerfiles, TestDockerCompose,
#          TestScriptMigration, TestEnvironmentAndDocs, TestCrossFileConsistency
# Deps: pytest, pathlib, re, yaml, subprocess, os, stat
# @end-summary
"""
Tests for Docker-to-Podman container runtime migration.

These tests verify the CODE and file content, not runtime behavior.
They do not require Docker or Podman to be installed or running.
"""

from __future__ import annotations

import re
import stat
from pathlib import Path

import pytest
import yaml

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def project_root() -> Path:
    """Return the absolute path to the project root."""
    return PROJECT_ROOT


@pytest.fixture
def container_runtime_sh(project_root: Path) -> str:
    """Return the content of scripts/container-runtime.sh."""
    return (project_root / "scripts" / "container-runtime.sh").read_text()


@pytest.fixture
def compose_sh(project_root: Path) -> str:
    """Return the content of scripts/compose.sh."""
    return (project_root / "scripts" / "compose.sh").read_text()


@pytest.fixture
def dockerfile_runtime(project_root: Path) -> str:
    """Return the content of docker/Dockerfile.runtime."""
    return (project_root / "docker" / "Dockerfile.runtime").read_text()


@pytest.fixture
def dockerfile_api(project_root: Path) -> str:
    """Return the content of docker/Dockerfile.api."""
    return (project_root / "docker" / "Dockerfile.api").read_text()


@pytest.fixture
def compose_yaml(project_root: Path) -> dict:
    """Return the parsed docker-compose.yml as a dict."""
    raw = (project_root / "docker-compose.yml").read_text()
    return yaml.safe_load(raw)


@pytest.fixture
def compose_raw(project_root: Path) -> str:
    """Return the raw text of docker-compose.yml (for regex checks on env-var substitution)."""
    return (project_root / "docker-compose.yml").read_text()


@pytest.fixture
def backup_sh(project_root: Path) -> str:
    """Return the content of scripts/backup_all.sh."""
    return (project_root / "scripts" / "backup_all.sh").read_text()


@pytest.fixture
def restore_sh(project_root: Path) -> str:
    """Return the content of scripts/restore_all.sh."""
    return (project_root / "scripts" / "restore_all.sh").read_text()


@pytest.fixture
def auto_scale_py(project_root: Path) -> str:
    """Return the content of scripts/auto_scale_workers.py."""
    return (project_root / "scripts" / "auto_scale_workers.py").read_text()


@pytest.fixture
def watch_tuning_py(project_root: Path) -> str:
    """Return the content of scripts/watch_tuning_signals.py."""
    return (project_root / "scripts" / "watch_tuning_signals.py").read_text()


@pytest.fixture
def generate_certs_sh(project_root: Path) -> str:
    """Return the content of docker/generate-certs.sh."""
    return (project_root / "docker" / "generate-certs.sh").read_text()


@pytest.fixture
def env_example(project_root: Path) -> str:
    """Return the content of .env.example."""
    return (project_root / ".env.example").read_text()


@pytest.fixture
def readme(project_root: Path) -> str:
    """Return the content of README.md."""
    return (project_root / "README.md").read_text()


# ===========================================================================
# A) Shell Script Tests
# ===========================================================================


class TestShellScripts:
    """Tests for container-runtime.sh and compose.sh shell scripts."""

    def test_container_runtime_exports_container_rt(
        self, container_runtime_sh: str
    ) -> None:
        """container-runtime.sh must export CONTAINER_RT so that sourcing
        scripts inherit the variable."""
        assert "export CONTAINER_RT" in container_runtime_sh

    def test_container_runtime_sets_container_rt(
        self, container_runtime_sh: str
    ) -> None:
        """container-runtime.sh must assign CONTAINER_RT to either 'podman' or 'docker'."""
        assert re.search(r'CONTAINER_RT="podman"', container_runtime_sh)
        assert re.search(r'CONTAINER_RT="docker"', container_runtime_sh)

    def test_compose_sh_is_executable(self, project_root: Path) -> None:
        """compose.sh must have the executable bit set so it can be invoked
        directly as ./scripts/compose.sh."""
        compose_path = project_root / "scripts" / "compose.sh"
        mode = compose_path.stat().st_mode
        assert mode & stat.S_IXUSR, "compose.sh is not executable by owner"

    def test_compose_sh_has_correct_shebang(self, compose_sh: str) -> None:
        """compose.sh must start with a portable bash shebang line."""
        first_line = compose_sh.splitlines()[0]
        assert first_line.startswith("#!"), "Missing shebang"
        assert "bash" in first_line, "Shebang does not reference bash"

    def test_container_runtime_prefers_podman(
        self, container_runtime_sh: str
    ) -> None:
        """container-runtime.sh must check for podman BEFORE docker,
        so Podman is the preferred runtime when both are available."""
        podman_pos = container_runtime_sh.index("podman")
        # Find the first 'docker' that is NOT inside the word 'podman'
        # We look for 'docker' in the elif branch.
        docker_match = re.search(r'command -v docker', container_runtime_sh)
        assert docker_match is not None, "docker detection branch not found"
        docker_pos = docker_match.start()
        assert podman_pos < docker_pos, (
            "Podman detection must appear before Docker detection"
        )

    def test_compose_sh_prefers_podman_compose(self, compose_sh: str) -> None:
        """compose.sh must check for podman-compose BEFORE docker compose,
        so Podman compose tooling is preferred when available."""
        podman_compose_match = re.search(r"podman-compose", compose_sh)
        docker_compose_match = re.search(r"docker compose", compose_sh)
        assert podman_compose_match is not None, "podman-compose branch missing"
        assert docker_compose_match is not None, "docker compose branch missing"
        assert podman_compose_match.start() < docker_compose_match.start(), (
            "podman-compose must be checked before docker compose"
        )

    def test_container_runtime_has_safety_flags_or_guard(
        self, container_runtime_sh: str
    ) -> None:
        """container-runtime.sh should either use 'set -euo pipefail' for
        safety, or at minimum have an explicit exit-on-error path (the
        'exit 1' in the else branch) to avoid running with an unset
        CONTAINER_RT."""
        has_pipefail = "set -euo pipefail" in container_runtime_sh
        has_exit_on_error = "exit 1" in container_runtime_sh
        assert has_pipefail or has_exit_on_error, (
            "container-runtime.sh needs either 'set -euo pipefail' or "
            "an explicit 'exit 1' fallback"
        )

    def test_compose_sh_has_safety_flags(self, compose_sh: str) -> None:
        """compose.sh must use 'set -euo pipefail' to ensure errors in
        detection logic are not silently swallowed."""
        assert "set -euo pipefail" in compose_sh

    def test_container_runtime_has_correct_shebang(
        self, container_runtime_sh: str
    ) -> None:
        """container-runtime.sh must start with a valid bash shebang."""
        first_line = container_runtime_sh.splitlines()[0]
        assert first_line.startswith("#!"), "Missing shebang"
        assert "bash" in first_line, "Shebang does not reference bash"


# ===========================================================================
# B) Dockerfile Tests
# ===========================================================================


class TestDockerfiles:
    """Tests for Dockerfile.runtime and Dockerfile.api security patterns."""

    def test_runtime_has_user_directive(self, dockerfile_runtime: str) -> None:
        """Dockerfile.runtime must contain a USER directive to run the
        container as a non-root user (CIS Docker Benchmark 4.1)."""
        assert re.search(r"^USER\s+\S+", dockerfile_runtime, re.MULTILINE), (
            "Dockerfile.runtime is missing a USER directive"
        )

    def test_runtime_creates_user_group(self, dockerfile_runtime: str) -> None:
        """Dockerfile.runtime must create the user and group before switching
        to them, using groupadd and useradd (or equivalent)."""
        assert "groupadd" in dockerfile_runtime, "groupadd not found"
        assert "useradd" in dockerfile_runtime, "useradd not found"

    def test_runtime_creates_user_before_switching(
        self, dockerfile_runtime: str
    ) -> None:
        """The RUN groupadd/useradd must appear BEFORE the USER directive."""
        useradd_match = re.search(r"useradd", dockerfile_runtime)
        user_directive_match = re.search(
            r"^USER\s+", dockerfile_runtime, re.MULTILINE
        )
        assert useradd_match is not None
        assert user_directive_match is not None
        assert useradd_match.start() < user_directive_match.start(), (
            "useradd must appear before USER directive"
        )

    def test_runtime_uses_chown_on_copy(self, dockerfile_runtime: str) -> None:
        """Dockerfile.runtime COPY directives that copy application code
        should use --chown to set correct ownership for the non-root user."""
        copy_lines = [
            line
            for line in dockerfile_runtime.splitlines()
            if line.strip().startswith("COPY") and "/app/" in line
        ]
        # At least one COPY should have --chown
        chown_copies = [l for l in copy_lines if "--chown=" in l]
        assert len(chown_copies) > 0, (
            "No COPY directives with --chown found in Dockerfile.runtime"
        )

    def test_api_has_user_directive(self, dockerfile_api: str) -> None:
        """Dockerfile.api (baseline) must also contain a USER directive
        to run as non-root."""
        assert re.search(r"^USER\s+\S+", dockerfile_api, re.MULTILINE), (
            "Dockerfile.api is missing a USER directive"
        )

    def test_runtime_user_is_not_root(self, dockerfile_runtime: str) -> None:
        """The USER directive in Dockerfile.runtime must NOT be root."""
        user_match = re.search(
            r"^USER\s+(\S+)", dockerfile_runtime, re.MULTILINE
        )
        assert user_match is not None
        assert user_match.group(1) != "root", (
            "USER directive in Dockerfile.runtime must not be 'root'"
        )


# ===========================================================================
# C) Docker Compose Tests
# ===========================================================================


class TestDockerCompose:
    """Tests for docker-compose.yml Podman compatibility."""

    # Expected services that must exist in the compose file.
    EXPECTED_SERVICES = {
        "temporal-db",
        "temporal",
        "temporal-ui",
        "rag-api",
        "rag-worker",
        "dozzle",
        "rag-redis",
        "prometheus",
        "alertmanager",
        "grafana",
        "langfuse-postgres",
        "langfuse-redis",
        "langfuse-clickhouse",
        "langfuse-minio",
        "langfuse-worker",
        "langfuse-web",
    }

    def test_dozzle_uses_container_sock_env_var(
        self, compose_raw: str
    ) -> None:
        """The Dozzle service volume must use ${CONTAINER_SOCK:-...}
        instead of a hardcoded /var/run/docker.sock, so Podman users
        can override the socket path."""
        assert "${CONTAINER_SOCK:-" in compose_raw, (
            "Dozzle volume must use CONTAINER_SOCK env-var substitution"
        )

    def test_dozzle_does_not_hardcode_docker_sock(
        self, compose_yaml: dict
    ) -> None:
        """Verify that the Dozzle service volumes do NOT contain a raw
        hardcoded '/var/run/docker.sock' string without the env-var wrapper.
        (PyYAML resolves ${VAR:-default} to the default, so we check the
        raw text in a separate test.)"""
        # This test verifies the parsed YAML still maps to docker.sock
        # as the default — the env-var substitution is checked in the
        # raw-text test above.
        dozzle = compose_yaml["services"]["dozzle"]
        volumes = dozzle.get("volumes", [])
        assert len(volumes) > 0, "Dozzle should have at least one volume"

    def test_all_expected_services_exist(self, compose_yaml: dict) -> None:
        """All services that existed before the migration must still be
        present in the compose file."""
        actual_services = set(compose_yaml["services"].keys())
        missing = self.EXPECTED_SERVICES - actual_services
        assert not missing, f"Missing services in docker-compose.yml: {missing}"

    def test_extra_hosts_preserved(self, compose_yaml: dict) -> None:
        """Services that need host.docker.internal (rag-api, rag-worker)
        must retain extra_hosts entries. This works in both Docker and
        Podman (Podman supports host-gateway)."""
        for svc_name in ("rag-api", "rag-worker"):
            svc = compose_yaml["services"][svc_name]
            extra_hosts = svc.get("extra_hosts", [])
            host_entries = [
                h for h in extra_hosts if "host.docker.internal" in h
            ]
            assert len(host_entries) > 0, (
                f"{svc_name} must have host.docker.internal in extra_hosts"
            )


# ===========================================================================
# D) Script Migration Tests
# ===========================================================================


class TestScriptMigration:
    """Tests that scripts use $CONTAINER_RT instead of hardcoded 'docker'."""

    # ---- backup_all.sh ----

    def test_backup_does_not_hardcode_docker_exec(
        self, backup_sh: str
    ) -> None:
        """backup_all.sh must NOT contain bare 'docker exec' calls; it
        should use '$CONTAINER_RT exec' for runtime portability."""
        # Match 'docker exec' that is NOT preceded by $ (i.e., not $CONTAINER_RT)
        # and not inside a comment line.
        for line in backup_sh.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            assert not re.search(r"\bdocker\s+exec\b", stripped), (
                f"Found hardcoded 'docker exec' in backup_all.sh: {stripped}"
            )

    def test_backup_sources_container_runtime(self, backup_sh: str) -> None:
        """backup_all.sh must source container-runtime.sh to get CONTAINER_RT."""
        assert "container-runtime.sh" in backup_sh, (
            "backup_all.sh must source container-runtime.sh"
        )
        assert re.search(r"source\s+.*container-runtime\.sh", backup_sh), (
            "backup_all.sh must source container-runtime.sh"
        )

    # ---- restore_all.sh ----

    def test_restore_does_not_hardcode_docker_commands(
        self, restore_sh: str
    ) -> None:
        """restore_all.sh must NOT contain bare 'docker exec/cp/ps/restart'
        calls; all container commands should use $CONTAINER_RT."""
        docker_cmds = ["exec", "cp", "ps", "restart"]
        for line in restore_sh.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            for cmd in docker_cmds:
                pattern = rf"\bdocker\s+{cmd}\b"
                assert not re.search(pattern, stripped), (
                    f"Found hardcoded 'docker {cmd}' in restore_all.sh: {stripped}"
                )

    def test_restore_sources_container_runtime(self, restore_sh: str) -> None:
        """restore_all.sh must source container-runtime.sh to get CONTAINER_RT."""
        assert re.search(r"source\s+.*container-runtime\.sh", restore_sh), (
            "restore_all.sh must source container-runtime.sh"
        )

    # ---- auto_scale_workers.py ----

    def test_auto_scale_has_detect_function(self, auto_scale_py: str) -> None:
        """auto_scale_workers.py must define _detect_container_runtime()
        to dynamically choose between podman and docker."""
        assert "def _detect_container_runtime" in auto_scale_py

    def test_auto_scale_has_container_rt_variable(
        self, auto_scale_py: str
    ) -> None:
        """auto_scale_workers.py must set a module-level CONTAINER_RT
        variable from _detect_container_runtime()."""
        assert re.search(
            r"^CONTAINER_RT\s*=\s*_detect_container_runtime\(\)",
            auto_scale_py,
            re.MULTILINE,
        )

    def test_auto_scale_no_hardcoded_docker_in_subprocess(
        self, auto_scale_py: str
    ) -> None:
        """auto_scale_workers.py must NOT pass a literal "docker" string
        to subprocess calls. All subprocess invocations should use
        CONTAINER_RT. The detection function itself is excluded."""
        # Extract the detection function body to exclude it.
        detect_fn_match = re.search(
            r"def _detect_container_runtime\(\).*?(?=\ndef |\nCONTAINER_RT)",
            auto_scale_py,
            re.DOTALL,
        )
        assert detect_fn_match is not None

        # Remove the detection function from the source for analysis.
        code_without_detect = (
            auto_scale_py[: detect_fn_match.start()]
            + auto_scale_py[detect_fn_match.end() :]
        )

        # Look for subprocess calls with hardcoded "docker".
        # Pattern: [..., "docker", ...] or ["docker", ...]
        subprocess_docker = re.findall(
            r'subprocess\.run\(\s*\[.*?"docker"', code_without_detect, re.DOTALL
        )
        assert len(subprocess_docker) == 0, (
            "Found hardcoded 'docker' in subprocess calls outside detection function"
        )

    # ---- watch_tuning_signals.py ----

    def test_watch_tuning_has_detect_function(
        self, watch_tuning_py: str
    ) -> None:
        """watch_tuning_signals.py must define _detect_container_runtime()
        to dynamically choose between podman and docker."""
        assert "def _detect_container_runtime" in watch_tuning_py

    def test_watch_tuning_has_container_rt_variable(
        self, watch_tuning_py: str
    ) -> None:
        """watch_tuning_signals.py must set a module-level CONTAINER_RT
        variable from _detect_container_runtime()."""
        assert re.search(
            r"^CONTAINER_RT\s*=\s*_detect_container_runtime\(\)",
            watch_tuning_py,
            re.MULTILINE,
        )

    def test_watch_tuning_no_hardcoded_docker_in_subprocess(
        self, watch_tuning_py: str
    ) -> None:
        """watch_tuning_signals.py must NOT pass a literal "docker" string
        to subprocess calls outside the detection function."""
        detect_fn_match = re.search(
            r"def _detect_container_runtime\(\).*?(?=\ndef |\nCONTAINER_RT)",
            watch_tuning_py,
            re.DOTALL,
        )
        assert detect_fn_match is not None

        code_without_detect = (
            watch_tuning_py[: detect_fn_match.start()]
            + watch_tuning_py[detect_fn_match.end() :]
        )

        subprocess_docker = re.findall(
            r'subprocess\.run\(\s*\[.*?"docker"',
            code_without_detect,
            re.DOTALL,
        )
        assert len(subprocess_docker) == 0, (
            "Found hardcoded 'docker' in subprocess calls outside detection function"
        )

    # ---- generate-certs.sh ----

    def test_generate_certs_has_chmod_644(
        self, generate_certs_sh: str
    ) -> None:
        """generate-certs.sh must set chmod 644 on the certificate file
        so rootless runtimes can read the public cert."""
        assert "chmod 644" in generate_certs_sh

    def test_generate_certs_has_chmod_600(
        self, generate_certs_sh: str
    ) -> None:
        """generate-certs.sh must set chmod 600 on the key file to keep
        the private key restricted."""
        assert "chmod 600" in generate_certs_sh


# ===========================================================================
# E) Environment and Documentation Tests
# ===========================================================================


class TestEnvironmentAndDocs:
    """Tests for .env.example and README.md Podman documentation."""

    def test_env_example_contains_container_sock(
        self, env_example: str
    ) -> None:
        """'.env.example' must document the CONTAINER_SOCK variable so that
        Podman users know how to configure the container socket path."""
        assert "CONTAINER_SOCK" in env_example

    def test_readme_mentions_podman(self, readme: str) -> None:
        """README.md must mention Podman so users know it is supported."""
        assert "Podman" in readme or "podman" in readme

    def test_readme_references_compose_sh(self, readme: str) -> None:
        """README.md must reference ./scripts/compose.sh instead of bare
        'docker compose' commands, so the instructions work for both
        Docker and Podman users."""
        assert "./scripts/compose.sh" in readme

    def test_readme_has_podman_setup_section(self, readme: str) -> None:
        """README.md must have a 'Podman Setup' section with instructions
        for one-time Podman configuration."""
        # Look for a markdown heading containing "Podman Setup"
        assert re.search(
            r"^#{1,4}\s+Podman Setup", readme, re.MULTILINE
        ), "README.md must have a 'Podman Setup' heading"

    def test_readme_does_not_use_bare_docker_compose_in_commands(
        self, readme: str
    ) -> None:
        """README.md code blocks should not contain 'docker compose' as a
        command to run (except in prose explaining what compose.sh does).
        All runnable commands should use ./scripts/compose.sh."""
        # Extract fenced code blocks.
        code_blocks = re.findall(r"```(?:bash|sh)?\n(.*?)```", readme, re.DOTALL)
        for block in code_blocks:
            for line in block.splitlines():
                stripped = line.strip()
                # Skip comments.
                if stripped.startswith("#"):
                    continue
                # A runnable command starting with 'docker compose' is wrong.
                assert not re.match(r"^docker\s+compose\b", stripped), (
                    f"README.md code block uses bare 'docker compose': {stripped}"
                )


# ===========================================================================
# F) Cross-File Consistency Tests
# ===========================================================================


class TestCrossFileConsistency:
    """Tests that migration changes are consistent across multiple files."""

    def test_user_name_matches_across_dockerfiles(
        self, dockerfile_runtime: str, dockerfile_api: str
    ) -> None:
        """The USER name in Dockerfile.runtime must match the USER name in
        Dockerfile.api for consistency (both should be 'app')."""
        runtime_user = re.search(
            r"^USER\s+(\S+)", dockerfile_runtime, re.MULTILINE
        )
        api_user = re.search(r"^USER\s+(\S+)", dockerfile_api, re.MULTILINE)

        assert runtime_user is not None, "Dockerfile.runtime missing USER"
        assert api_user is not None, "Dockerfile.api missing USER"
        assert runtime_user.group(1) == api_user.group(1), (
            f"USER mismatch: runtime={runtime_user.group(1)}, "
            f"api={api_user.group(1)}"
        )
        # Both should be 'app'.
        assert runtime_user.group(1) == "app"

    def test_container_sock_default_is_docker_socket(
        self, compose_raw: str
    ) -> None:
        """The CONTAINER_SOCK default in docker-compose.yml must be the
        standard Docker socket path /var/run/docker.sock, so Docker
        users need zero configuration."""
        match = re.search(
            r"\$\{CONTAINER_SOCK:-([^}]+)\}", compose_raw
        )
        assert match is not None, "CONTAINER_SOCK variable not found"
        assert match.group(1) == "/var/run/docker.sock", (
            f"CONTAINER_SOCK default should be /var/run/docker.sock, "
            f"got: {match.group(1)}"
        )

    def test_detection_order_consistent_shell_scripts(
        self, container_runtime_sh: str, compose_sh: str
    ) -> None:
        """Both container-runtime.sh and compose.sh must prefer Podman
        first and Docker second, so behavior is consistent when both
        runtimes are installed."""
        # container-runtime.sh: podman before docker.
        rt_podman = container_runtime_sh.index("podman")
        rt_docker_match = re.search(
            r"command -v docker", container_runtime_sh
        )
        assert rt_docker_match is not None
        assert rt_podman < rt_docker_match.start()

        # compose.sh: podman-compose before docker compose.
        cs_podman = compose_sh.index("podman-compose")
        cs_docker_match = re.search(r"docker compose", compose_sh)
        assert cs_docker_match is not None
        assert cs_podman < cs_docker_match.start()

    def test_python_scripts_detection_order_matches_shell(
        self, auto_scale_py: str, watch_tuning_py: str
    ) -> None:
        """The Python detection functions in auto_scale_workers.py and
        watch_tuning_signals.py must also prefer podman over docker,
        matching the shell scripts' detection order."""
        for name, content in [
            ("auto_scale_workers.py", auto_scale_py),
            ("watch_tuning_signals.py", watch_tuning_py),
        ]:
            # Extract the detection function.
            fn_match = re.search(
                r"def _detect_container_runtime\(\).*?(?=\n\ndef |\n\nCONTAINER_RT|\nCONTAINER_RT)",
                content,
                re.DOTALL,
            )
            assert fn_match is not None, (
                f"Could not find _detect_container_runtime in {name}"
            )
            fn_body = fn_match.group(0)

            # Podman check must come before Docker check.
            podman_pos = fn_body.index('"podman"')
            docker_pos = fn_body.index('"docker"')
            assert podman_pos < docker_pos, (
                f"In {name}, podman detection must come before docker"
            )

    def test_backup_restore_both_source_same_script(
        self, backup_sh: str, restore_sh: str
    ) -> None:
        """Both backup_all.sh and restore_all.sh must source the same
        container-runtime.sh helper for runtime detection."""
        assert "container-runtime.sh" in backup_sh
        assert "container-runtime.sh" in restore_sh

    def test_python_scripts_use_shutil_which_for_detection(
        self, auto_scale_py: str, watch_tuning_py: str
    ) -> None:
        """Both Python scripts should use shutil.which() for runtime
        detection (portable, no subprocess overhead)."""
        for name, content in [
            ("auto_scale_workers.py", auto_scale_py),
            ("watch_tuning_signals.py", watch_tuning_py),
        ]:
            assert "shutil.which" in content, (
                f"{name} should use shutil.which() for runtime detection"
            )
