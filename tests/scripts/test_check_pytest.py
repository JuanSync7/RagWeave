"""Unit tests for scripts/check_pytest.py safety validator.

Tests cover all detection categories (FR-102 through FR-114),
conftest exemptions, group overrides, alias tracking, strict mode,
parse error handling, and file discovery.
"""

import sys
import textwrap
from pathlib import Path

import pytest

# Import the validator from scripts/ directory
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from check_pytest import SafetyValidator, Violation, ValidationResult


# ---------------------------------------------------------------------------
# FR-102: Dangerous Call Detection
# ---------------------------------------------------------------------------


class TestDangerousCalls:
    """FR-102: Dangerous call detection.

    Each dangerous call pattern SHALL be detected with category='dangerous_call'
    and severity='block', regardless of location in the AST.
    """

    @pytest.mark.parametrize(
        "code,pattern",
        [
            ("import subprocess; subprocess.run('ls')", "subprocess.run"),
            ("import subprocess; subprocess.call('ls')", "subprocess.call"),
            ("import subprocess; subprocess.Popen('ls')", "subprocess.Popen"),
            (
                "import subprocess; subprocess.check_output('ls')",
                "subprocess.check_output",
            ),
            (
                "import subprocess; subprocess.check_call('ls')",
                "subprocess.check_call",
            ),
            ("import os; os.system('ls')", "os.system"),
            ("import os; os.popen('ls')", "os.popen"),
            ("eval('1+1')", "eval"),
            ("exec('pass')", "exec"),
            ("compile('pass', '<string>', 'exec')", "compile"),
            ("__import__('os')", "__import__"),
        ],
        ids=[
            "subprocess.run",
            "subprocess.call",
            "subprocess.Popen",
            "subprocess.check_output",
            "subprocess.check_call",
            "os.system",
            "os.popen",
            "eval",
            "exec",
            "compile",
            "__import__",
        ],
    )
    def test_detects_dangerous_call(self, code, pattern, tmp_path):
        """Each dangerous call pattern is detected with severity=block."""
        test_file = tmp_path / "test_bad.py"
        test_file.write_text(code)
        validator = SafetyValidator()
        violations = validator.validate_file(str(test_file))
        block_violations = [
            v
            for v in violations
            if v.severity == "block" and v.category == "dangerous_call"
        ]
        assert any(v.pattern == pattern for v in block_violations), (
            f"Expected block violation for {pattern}, got {block_violations}"
        )

    def test_safe_code_no_violations(self, tmp_path):
        """Clean test file produces no dangerous_call violations."""
        test_file = tmp_path / "test_clean.py"
        test_file.write_text("def test_add(): assert 1 + 1 == 2")
        validator = SafetyValidator()
        violations = validator.validate_file(str(test_file))
        assert not [v for v in violations if v.category == "dangerous_call"]

    def test_dangerous_call_inside_function(self, tmp_path):
        """Dangerous calls inside function bodies are still detected."""
        code = textwrap.dedent("""\
            def test_exploit():
                eval('1+1')
        """)
        test_file = tmp_path / "test_inner.py"
        test_file.write_text(code)
        validator = SafetyValidator()
        violations = validator.validate_file(str(test_file))
        assert any(
            v.pattern == "eval" and v.category == "dangerous_call" for v in violations
        )

    def test_dangerous_call_inside_class_method(self, tmp_path):
        """Dangerous calls inside class methods are detected."""
        code = textwrap.dedent("""\
            class TestBad:
                def test_method(self):
                    exec('pass')
        """)
        test_file = tmp_path / "test_class.py"
        test_file.write_text(code)
        validator = SafetyValidator()
        violations = validator.validate_file(str(test_file))
        assert any(
            v.pattern == "exec" and v.category == "dangerous_call" for v in violations
        )

    def test_dangerous_call_nested_function(self, tmp_path):
        """Dangerous calls in nested functions are detected."""
        code = textwrap.dedent("""\
            def outer():
                def inner():
                    eval("1+1")
                inner()
        """)
        test_file = tmp_path / "test_nested.py"
        test_file.write_text(code)
        validator = SafetyValidator()
        violations = validator.validate_file(str(test_file))
        assert any(
            v.pattern == "eval" and v.category == "dangerous_call" for v in violations
        )


# ---------------------------------------------------------------------------
# FR-103: Dangerous Import Detection
# ---------------------------------------------------------------------------


class TestDangerousImports:
    """FR-103: Dangerous import detection.

    Each dangerous module import SHALL be detected with category='dangerous_import'
    and severity='block'.
    """

    @pytest.mark.parametrize(
        "code,pattern",
        [
            ("import subprocess", "subprocess"),
            ("import socket", "socket"),
            ("from http.client import HTTPConnection", "http.client"),
            ("import ctypes", "ctypes"),
            ("import multiprocessing", "multiprocessing"),
        ],
        ids=[
            "subprocess",
            "socket",
            "http.client",
            "ctypes",
            "multiprocessing",
        ],
    )
    def test_detects_dangerous_import(self, code, pattern, tmp_path):
        """Each dangerous import is detected with category=dangerous_import, severity=block."""
        test_file = tmp_path / "test_bad.py"
        test_file.write_text(code)
        validator = SafetyValidator()
        violations = validator.validate_file(str(test_file))
        import_violations = [
            v for v in violations if v.category == "dangerous_import"
        ]
        assert any(v.pattern == pattern for v in import_violations), (
            f"Expected dangerous_import for {pattern}, got {import_violations}"
        )
        assert all(v.severity == "block" for v in import_violations)

    def test_from_import_detected(self, tmp_path):
        """'from subprocess import run' detects subprocess as dangerous import."""
        test_file = tmp_path / "test_from.py"
        test_file.write_text("from subprocess import run")
        validator = SafetyValidator()
        violations = validator.validate_file(str(test_file))
        assert any(
            v.category == "dangerous_import" and v.pattern == "subprocess"
            for v in violations
        )

    def test_mock_patch_string_not_flagged(self, tmp_path):
        """AC-103c: mock.patch string argument is NOT an import."""
        code = textwrap.dedent("""\
            from unittest import mock

            @mock.patch("subprocess.run")
            def test_something(mock_run):
                pass
        """)
        test_file = tmp_path / "test_mock.py"
        test_file.write_text(code)
        validator = SafetyValidator()
        violations = validator.validate_file(str(test_file))
        assert not [v for v in violations if v.pattern == "subprocess"]


# ---------------------------------------------------------------------------
# FR-104: Filesystem Write Detection
# ---------------------------------------------------------------------------


class TestFilesystemWrites:
    """FR-104: Filesystem write detection.

    File writes outside tmp_path or /tmp SHALL be BLOCK.
    File writes derived from tmp_path SHALL be safe.
    """

    def test_open_write_unsafe_path_blocked(self, tmp_path):
        """open('file.txt', 'w') outside tmp_path produces BLOCK."""
        code = 'open("file.txt", "w")'
        test_file = tmp_path / "test_fs.py"
        test_file.write_text(code)
        validator = SafetyValidator()
        violations = validator.validate_file(str(test_file))
        assert any(
            v.category == "filesystem_write" and v.severity == "block"
            for v in violations
        )

    def test_open_write_tmp_path_safe(self, tmp_path):
        """AC-104b: open(tmp_path / 'file.txt', 'w') is safe via tmp_path heuristic."""
        code = textwrap.dedent("""\
            def test_write(tmp_path):
                f = open(tmp_path / "out.txt", "w")
                f.close()
        """)
        test_file = tmp_path / "test_fs.py"
        test_file.write_text(code)
        validator = SafetyValidator()
        violations = validator.validate_file(str(test_file))
        assert not [
            v
            for v in violations
            if v.category == "filesystem_write" and v.severity == "block"
        ]

    def test_write_text_tmp_path_safe(self, tmp_path):
        """Path.write_text via tmp_path is safe."""
        code = textwrap.dedent("""\
            def test_write(tmp_path):
                (tmp_path / "out.txt").write_text("data")
        """)
        test_file = tmp_path / "test_fs.py"
        test_file.write_text(code)
        validator = SafetyValidator()
        violations = validator.validate_file(str(test_file))
        assert not [
            v
            for v in violations
            if v.category == "filesystem_write" and v.severity == "block"
        ]

    def test_shutil_rmtree_blocked(self, tmp_path):
        """shutil.rmtree('/data') outside tmp_path produces BLOCK."""
        code = 'import shutil; shutil.rmtree("/data")'
        test_file = tmp_path / "test_fs.py"
        test_file.write_text(code)
        validator = SafetyValidator()
        violations = validator.validate_file(str(test_file))
        assert any(
            v.category == "filesystem_write" and v.severity == "block"
            for v in violations
        )

    def test_os_remove_blocked(self, tmp_path):
        """os.remove('/etc/foo') outside tmp_path produces BLOCK."""
        code = 'import os; os.remove("/etc/foo")'
        test_file = tmp_path / "test_fs.py"
        test_file.write_text(code)
        validator = SafetyValidator()
        violations = validator.validate_file(str(test_file))
        assert any(
            v.category == "filesystem_write" and v.severity == "block"
            for v in violations
        )

    def test_open_write_absolute_etc_blocked(self, tmp_path):
        """open('/etc/passwd', 'w') is blocked."""
        code = 'open("/etc/passwd", "w")'
        test_file = tmp_path / "test_fs.py"
        test_file.write_text(code)
        validator = SafetyValidator()
        violations = validator.validate_file(str(test_file))
        assert any(
            v.category == "filesystem_write" and v.severity == "block"
            for v in violations
        )


# ---------------------------------------------------------------------------
# FR-105: Process/Signal Manipulation Detection
# ---------------------------------------------------------------------------


class TestProcessManipulation:
    """FR-105: Process/signal manipulation detection.

    All process/signal manipulation calls SHALL be detected with
    category='process_signal' and severity='block'.
    """

    @pytest.mark.parametrize(
        "code,pattern",
        [
            ("import os; os.kill(1234, 9)", "os.kill"),
            ("import signal; signal.signal(2, lambda s, f: None)", "signal.signal"),
            ("import sys; sys.exit(1)", "sys.exit"),
            ("import os; os._exit(1)", "os._exit"),
            ("import os; os.fork()", "os.fork"),
        ],
        ids=["os.kill", "signal.signal", "sys.exit", "os._exit", "os.fork"],
    )
    def test_detects_process_signal(self, code, pattern, tmp_path):
        """Each process/signal call is detected with severity=block."""
        test_file = tmp_path / "test_proc.py"
        test_file.write_text(code)
        validator = SafetyValidator()
        violations = validator.validate_file(str(test_file))
        assert any(
            v.pattern == pattern
            and v.severity == "block"
            and v.category == "process_signal"
            for v in violations
        ), f"Expected process_signal block for {pattern}, got {violations}"


# ---------------------------------------------------------------------------
# FR-106: Database Access Detection
# ---------------------------------------------------------------------------


class TestDatabaseAccess:
    """FR-106: Database access detection.

    sqlite3.connect(':memory:') SHALL be allowed.
    sqlite3.connect('/data/db') SHALL produce WARN.
    psycopg2.connect() SHALL produce BLOCK.
    """

    def test_sqlite_memory_allowed(self, tmp_path):
        """AC-106a: sqlite3.connect(':memory:') is safe -- no violation."""
        code = 'import sqlite3; sqlite3.connect(":memory:")'
        test_file = tmp_path / "test_db.py"
        test_file.write_text(code)
        validator = SafetyValidator()
        violations = validator.validate_file(str(test_file))
        db_violations = [v for v in violations if v.category == "database_access"]
        assert not [v for v in db_violations if v.severity == "block"]

    def test_sqlite_file_path_warned(self, tmp_path):
        """sqlite3.connect('/data/db') produces WARN."""
        code = 'import sqlite3; sqlite3.connect("/data/db")'
        test_file = tmp_path / "test_db.py"
        test_file.write_text(code)
        validator = SafetyValidator()
        violations = validator.validate_file(str(test_file))
        assert any(
            v.category == "database_access" and v.severity == "warn"
            for v in violations
        )

    def test_psycopg2_blocked(self, tmp_path):
        """AC-106b: psycopg2.connect() produces BLOCK."""
        code = 'import psycopg2; psycopg2.connect("dbname=test")'
        test_file = tmp_path / "test_db.py"
        test_file.write_text(code)
        validator = SafetyValidator()
        violations = validator.validate_file(str(test_file))
        assert any(
            v.pattern == "psycopg2.connect"
            and v.severity == "block"
            and v.category == "database_access"
            for v in violations
        )

    def test_pymongo_blocked(self, tmp_path):
        """pymongo.MongoClient() produces BLOCK."""
        code = 'import pymongo; pymongo.MongoClient("mongodb://localhost")'
        test_file = tmp_path / "test_db.py"
        test_file.write_text(code)
        validator = SafetyValidator()
        violations = validator.validate_file(str(test_file))
        assert any(
            v.pattern == "pymongo.MongoClient"
            and v.severity == "block"
            and v.category == "database_access"
            for v in violations
        )


# ---------------------------------------------------------------------------
# FR-107: Network Library Detection
# ---------------------------------------------------------------------------


class TestNetworkLibraries:
    """FR-107: Network library detection.

    Module-level import of network libraries SHALL be BLOCK.
    Function-level import SHALL be WARN.
    """

    def test_module_level_import_blocked(self, tmp_path):
        """AC-107a: Module-level 'import requests' produces BLOCK."""
        code = "import requests"
        test_file = tmp_path / "test_net.py"
        test_file.write_text(code)
        validator = SafetyValidator()
        violations = validator.validate_file(str(test_file))
        assert any(
            v.category == "network_library" and v.severity == "block"
            for v in violations
        )

    def test_function_level_import_warned(self, tmp_path):
        """AC-107b: Function-level 'import requests' produces WARN."""
        code = textwrap.dedent("""\
            def test_foo():
                import requests
        """)
        test_file = tmp_path / "test_net.py"
        test_file.write_text(code)
        validator = SafetyValidator()
        violations = validator.validate_file(str(test_file))
        assert any(
            v.category == "network_library" and v.severity == "warn"
            for v in violations
        )

    def test_httpx_module_level_blocked(self, tmp_path):
        """Module-level 'import httpx' produces BLOCK."""
        code = "import httpx"
        test_file = tmp_path / "test_net.py"
        test_file.write_text(code)
        validator = SafetyValidator()
        violations = validator.validate_file(str(test_file))
        assert any(
            v.category == "network_library" and v.severity == "block"
            for v in violations
        )

    def test_aiohttp_function_level_warned(self, tmp_path):
        """Function-level 'import aiohttp' produces WARN."""
        code = textwrap.dedent("""\
            def test_async():
                import aiohttp
        """)
        test_file = tmp_path / "test_net.py"
        test_file.write_text(code)
        validator = SafetyValidator()
        violations = validator.validate_file(str(test_file))
        assert any(
            v.category == "network_library" and v.severity == "warn"
            for v in violations
        )

    def test_urllib_request_module_level_blocked(self, tmp_path):
        """Module-level 'from urllib import request' produces BLOCK."""
        code = "from urllib import request"
        test_file = tmp_path / "test_net.py"
        test_file.write_text(code)
        validator = SafetyValidator()
        violations = validator.validate_file(str(test_file))
        assert any(
            v.category == "network_library" and v.severity == "block"
            for v in violations
        )


# ---------------------------------------------------------------------------
# FR-108: Alias Tracking
# ---------------------------------------------------------------------------


class TestAliasTracking:
    """FR-108: Import alias tracking.

    Aliases created via 'import X as Y' and 'from X import Y as Z' SHALL
    be resolved so that dangerous calls via aliases are detected.
    """

    def test_import_as_alias_call_detected(self, tmp_path):
        """AC-108a: 'import subprocess as sp; sp.run()' detected as subprocess.run."""
        code = textwrap.dedent("""\
            import subprocess as sp
            sp.run("ls")
        """)
        test_file = tmp_path / "test_alias.py"
        test_file.write_text(code)
        validator = SafetyValidator()
        violations = validator.validate_file(str(test_file))
        assert any(v.pattern == "subprocess.run" for v in violations)

    def test_from_import_alias_call_detected(self, tmp_path):
        """AC-108b: 'from os import system as syscmd; syscmd()' detected as os.system."""
        code = textwrap.dedent("""\
            from os import system as syscmd
            syscmd("ls")
        """)
        test_file = tmp_path / "test_alias.py"
        test_file.write_text(code)
        validator = SafetyValidator()
        violations = validator.validate_file(str(test_file))
        assert any(
            v.pattern == "os.system" and v.category == "dangerous_call"
            for v in violations
        )

    def test_from_import_bare_name(self, tmp_path):
        """'from os import system; system()' detected as os.system."""
        code = textwrap.dedent("""\
            from os import system
            system("ls")
        """)
        test_file = tmp_path / "test_alias.py"
        test_file.write_text(code)
        validator = SafetyValidator()
        violations = validator.validate_file(str(test_file))
        assert any(
            v.pattern == "os.system" and v.category == "dangerous_call"
            for v in violations
        )

    def test_import_as_alias_import_still_detected(self, tmp_path):
        """'import subprocess as sp' is still flagged as dangerous_import for subprocess."""
        code = "import subprocess as sp"
        test_file = tmp_path / "test_alias.py"
        test_file.write_text(code)
        validator = SafetyValidator()
        violations = validator.validate_file(str(test_file))
        assert any(
            v.category == "dangerous_import" and v.pattern == "subprocess"
            for v in violations
        )


# ---------------------------------------------------------------------------
# FR-109: conftest.py Exemption Policy
# ---------------------------------------------------------------------------


class TestConftestExemptions:
    """FR-109: conftest.py exemption policy.

    Certain patterns in conftest.py files SHALL be exempted (logged as
    conftest_exemptions) rather than blocked. Dangerous imports remain blocked.
    """

    def test_sys_modules_allowed_in_conftest(self, tmp_path):
        """AC-109a: sys.modules manipulation in conftest is exempted."""
        code = textwrap.dedent("""\
            import sys
            import types
            sys.modules["torch"] = types.ModuleType("torch")
        """)
        conftest = tmp_path / "conftest.py"
        conftest.write_text(code)
        validator = SafetyValidator()
        result = validator.validate_scope([str(conftest)])
        assert result.status == "passed"
        assert len(result.conftest_exemptions) > 0
        assert any(
            "sys.modules" in e.pattern for e in result.conftest_exemptions
        )

    def test_importlib_util_allowed_in_conftest(self, tmp_path):
        """importlib.util usage in conftest is exempted."""
        code = textwrap.dedent("""\
            import importlib.util
            _spec = importlib.util.spec_from_file_location("mod", "/path/mod.py")
            _mod = importlib.util.module_from_spec(_spec)
        """)
        conftest = tmp_path / "conftest.py"
        conftest.write_text(code)
        validator = SafetyValidator()
        result = validator.validate_scope([str(conftest)])
        assert result.status == "passed"
        assert any(
            "importlib" in e.pattern for e in result.conftest_exemptions
        )

    def test_exec_module_allowed_in_conftest(self, tmp_path):
        """AC-109b: spec.loader.exec_module() in conftest is exempted."""
        code = textwrap.dedent("""\
            import importlib.util
            _spec = importlib.util.spec_from_file_location("mod", "/path/mod.py")
            _mod = importlib.util.module_from_spec(_spec)
            _spec.loader.exec_module(_mod)
        """)
        conftest = tmp_path / "conftest.py"
        conftest.write_text(code)
        validator = SafetyValidator()
        result = validator.validate_scope([str(conftest)])
        assert result.status == "passed"
        assert any(
            "exec_module" in e.pattern for e in result.conftest_exemptions
        )

    def test_types_module_type_allowed_in_conftest(self, tmp_path):
        """types.ModuleType() in conftest is exempted."""
        code = textwrap.dedent("""\
            import types
            stub = types.ModuleType("fake_module")
        """)
        conftest = tmp_path / "conftest.py"
        conftest.write_text(code)
        validator = SafetyValidator()
        result = validator.validate_scope([str(conftest)])
        assert result.status == "passed"
        assert any(
            "ModuleType" in e.pattern for e in result.conftest_exemptions
        )

    def test_subprocess_still_blocked_in_conftest(self, tmp_path):
        """AC-109c: Dangerous imports are NOT exempted in conftest."""
        code = "import subprocess"
        conftest = tmp_path / "conftest.py"
        conftest.write_text(code)
        validator = SafetyValidator()
        result = validator.validate_scope([str(conftest)])
        assert result.status == "blocked"
        assert any(v.pattern == "subprocess" for v in result.violations)

    def test_exemptions_not_in_regular_test_file(self, tmp_path):
        """sys.modules assignment in a regular test file is NOT exempted."""
        code = textwrap.dedent("""\
            import sys
            import types
            sys.modules["torch"] = types.ModuleType("torch")
        """)
        test_file = tmp_path / "test_regular.py"
        test_file.write_text(code)
        validator = SafetyValidator()
        result = validator.validate_scope([str(test_file)])
        # Should have violations, not exemptions
        assert result.conftest_exemptions == [] or not any(
            "sys.modules" in e.pattern for e in result.conftest_exemptions
        )


# ---------------------------------------------------------------------------
# FR-110: Per-Group Validation Overrides
# ---------------------------------------------------------------------------


class TestGroupOverrides:
    """FR-110: Per-group validation overrides.

    --allow subprocess SHALL downgrade import BLOCK to ALLOW (logged in overrides).
    --allow subprocess SHALL NOT override dangerous calls (subprocess.run() still blocked).
    """

    def test_allow_overrides_import_block(self, tmp_path):
        """AC-110a: --allow subprocess downgrades import subprocess to ALLOW."""
        code = "import subprocess"
        test_file = tmp_path / "test_override.py"
        test_file.write_text(code)
        validator = SafetyValidator(allowed_patterns=["subprocess"])
        result = validator.validate_scope([str(test_file)])
        assert result.status == "passed"
        # The override should be logged
        has_override = any(
            o.pattern == "subprocess" for o in result.overrides_applied
        ) or any(
            e.reason == "group_override" for e in result.conftest_exemptions
        )
        assert has_override, "Override should be logged in overrides_applied or conftest_exemptions"

    def test_allow_does_not_override_calls(self, tmp_path):
        """AC-110b: --allow subprocess does NOT suppress subprocess.run() call detection."""
        code = textwrap.dedent("""\
            import subprocess
            subprocess.run("ls")
        """)
        test_file = tmp_path / "test_override.py"
        test_file.write_text(code)
        validator = SafetyValidator(allowed_patterns=["subprocess"])
        result = validator.validate_scope([str(test_file)])
        assert result.status == "blocked"
        call_violations = [
            v for v in result.violations if v.category == "dangerous_call"
        ]
        assert any(v.pattern == "subprocess.run" for v in call_violations), (
            "subprocess.run() call should still be blocked even with --allow subprocess"
        )

    def test_allow_multiple_patterns(self, tmp_path):
        """Multiple --allow patterns work together."""
        code = textwrap.dedent("""\
            import subprocess
            import socket
        """)
        test_file = tmp_path / "test_multi.py"
        test_file.write_text(code)
        validator = SafetyValidator(allowed_patterns=["subprocess", "socket"])
        result = validator.validate_scope([str(test_file)])
        assert result.status == "passed"


# ---------------------------------------------------------------------------
# FR-114: Strict Mode
# ---------------------------------------------------------------------------


class TestStrictMode:
    """FR-114: --strict flag.

    WARN violations without --strict SHALL pass (exit 0).
    WARN violations with --strict SHALL be upgraded to BLOCK (exit 1).
    """

    def test_warn_without_strict_passes(self, tmp_path):
        """WARN-only violations without --strict produce status=passed."""
        code = textwrap.dedent("""\
            def test_foo():
                import requests
        """)
        test_file = tmp_path / "test_warn.py"
        test_file.write_text(code)
        validator = SafetyValidator(strict=False)
        result = validator.validate_scope([str(test_file)])
        assert result.status == "passed"

    def test_warn_with_strict_blocked(self, tmp_path):
        """AC-114: WARN violations with --strict are upgraded to BLOCK."""
        code = textwrap.dedent("""\
            def test_foo():
                import requests
        """)
        test_file = tmp_path / "test_strict.py"
        test_file.write_text(code)
        validator = SafetyValidator(strict=True)
        result = validator.validate_scope([str(test_file)])
        assert result.status == "blocked"
        assert all(v.severity == "block" for v in result.violations)

    def test_strict_does_not_affect_already_blocked(self, tmp_path):
        """Files that are already BLOCK remain BLOCK in strict mode."""
        code = "import subprocess"
        test_file = tmp_path / "test_strict.py"
        test_file.write_text(code)
        validator = SafetyValidator(strict=True)
        result = validator.validate_scope([str(test_file)])
        assert result.status == "blocked"


# ---------------------------------------------------------------------------
# Parse Error Handling
# ---------------------------------------------------------------------------


class TestParseErrors:
    """Files with syntax errors produce status='error' with synthetic violations.

    Remaining files SHALL still be validated (no early abort).
    """

    def test_syntax_error_returns_error_status(self, tmp_path):
        """AC-112c: Invalid Python syntax causes status=error."""
        test_file = tmp_path / "test_broken.py"
        test_file.write_text("def broken(\n")
        validator = SafetyValidator()
        result = validator.validate_scope([str(test_file)])
        assert result.status == "error"

    def test_syntax_error_produces_synthetic_violation(self, tmp_path):
        """Parse error files produce a synthetic violation with category=parse_error."""
        test_file = tmp_path / "test_broken.py"
        test_file.write_text("def broken(\n")
        validator = SafetyValidator()
        result = validator.validate_scope([str(test_file)])
        parse_errors = [
            v for v in result.violations if v.category == "parse_error"
        ]
        assert len(parse_errors) >= 1

    def test_remaining_files_still_validated(self, tmp_path):
        """Other files are still validated even when one has a parse error."""
        broken = tmp_path / "test_broken.py"
        broken.write_text("def broken(\n")

        dangerous = tmp_path / "test_dangerous.py"
        dangerous.write_text("import subprocess")

        clean = tmp_path / "test_clean.py"
        clean.write_text("def test_ok(): assert True")

        validator = SafetyValidator()
        result = validator.validate_scope(
            [str(broken), str(dangerous), str(clean)]
        )
        # Should have both parse_error and dangerous_import violations
        categories = {v.category for v in result.violations}
        assert "parse_error" in categories
        assert "dangerous_import" in categories


# ---------------------------------------------------------------------------
# FR-113: File Discovery
# ---------------------------------------------------------------------------


class TestFileDiscovery:
    """FR-113: Recursive file discovery.

    Directories SHALL be recursively searched for test_*.py and *_test.py.
    conftest.py ancestry SHALL be discovered.
    """

    def test_discovers_test_files_in_directory(self, tmp_path):
        """Recursive discovery finds nested test files."""
        from check_pytest import discover_files

        test_dir = tmp_path / "tests" / "ingest"
        test_dir.mkdir(parents=True)
        (test_dir / "test_foo.py").write_text("def test_x(): pass")
        (test_dir / "test_bar.py").write_text("def test_y(): pass")
        (test_dir / "helper.py").write_text("# not a test")

        test_files, conftest_files = discover_files([str(test_dir)])
        assert len(test_files) == 2
        assert all("test_" in f.name for f in test_files)
        # helper.py should NOT be in test_files
        assert not any("helper" in f.name for f in test_files)

    def test_discovers_conftest_in_ancestors(self, tmp_path):
        """conftest.py in parent directories is discovered."""
        from check_pytest import discover_files

        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "conftest.py").write_text("# root conftest")
        sub_dir = tests_dir / "sub"
        sub_dir.mkdir()
        (sub_dir / "test_foo.py").write_text("def test_x(): pass")

        test_files, conftest_files = discover_files([str(sub_dir)])
        assert any(f.name == "conftest.py" for f in conftest_files)

    def test_discovers_deeply_nested_tests(self, tmp_path):
        """Test files in deeply nested directories are found."""
        from check_pytest import discover_files

        deep_dir = tmp_path / "tests" / "a" / "b" / "c"
        deep_dir.mkdir(parents=True)
        (deep_dir / "test_deep.py").write_text("def test_z(): pass")

        test_files, _ = discover_files([str(tmp_path / "tests")])
        assert len(test_files) == 1
        assert test_files[0].name == "test_deep.py"

    def test_discovers_test_suffix_files(self, tmp_path):
        """Files matching *_test.py pattern are discovered."""
        from check_pytest import discover_files

        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "integration_test.py").write_text("def test_i(): pass")

        test_files, _ = discover_files([str(test_dir)])
        assert len(test_files) == 1
        assert test_files[0].name == "integration_test.py"

    def test_conftest_discovered_at_multiple_levels(self, tmp_path):
        """conftest.py files at multiple levels are all discovered."""
        from check_pytest import discover_files

        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "conftest.py").write_text("# root conftest")
        sub_dir = tests_dir / "sub"
        sub_dir.mkdir()
        (sub_dir / "conftest.py").write_text("# sub conftest")
        (sub_dir / "test_foo.py").write_text("def test_x(): pass")

        _, conftest_files = discover_files([str(sub_dir)])
        conftest_names = [str(f) for f in conftest_files]
        # Both conftest files should be found
        assert len(conftest_files) >= 2


# ---------------------------------------------------------------------------
# Exit Code Behavior (FR-112)
# ---------------------------------------------------------------------------


class TestExitCodes:
    """FR-112: Exit code behavior via the main() function."""

    def test_main_returns_0_for_clean_files(self, tmp_path, capsys):
        """AC-112a: Clean files produce exit code 0."""
        from check_pytest import main

        test_file = tmp_path / "test_clean.py"
        test_file.write_text("def test_add(): assert 1 + 1 == 2")
        exit_code = main([str(test_file)])
        assert exit_code == 0

    def test_main_returns_1_for_violations(self, tmp_path, capsys):
        """AC-112b: BLOCK violations produce exit code 1."""
        from check_pytest import main

        test_file = tmp_path / "test_bad.py"
        test_file.write_text("import subprocess")
        exit_code = main([str(test_file)])
        assert exit_code == 1

    def test_main_returns_2_for_parse_error(self, tmp_path, capsys):
        """AC-112c: Parse errors produce exit code 2."""
        from check_pytest import main

        test_file = tmp_path / "test_broken.py"
        test_file.write_text("def broken(\n")
        exit_code = main([str(test_file)])
        assert exit_code == 2

    def test_main_json_output_is_valid(self, tmp_path, capsys):
        """AC-111: main() produces valid JSON on stdout."""
        import json
        from check_pytest import main

        test_file = tmp_path / "test_clean.py"
        test_file.write_text("def test_ok(): pass")
        main([str(test_file), "--json"])
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert "status" in result
        assert "timestamp" in result
        assert "files_scanned" in result
        assert "violations" in result
        assert "conftest_exemptions" in result
