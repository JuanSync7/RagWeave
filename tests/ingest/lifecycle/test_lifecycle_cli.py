"""Tests for the migrate and validate CLI entry points.

Covers:
- run_migration_cli: --dry-run; --from/--to; --confirm required; JSON/text output.
- run_validation_cli: --trace-id; --all; --sample; JSON/text output.
- Argparse integration: missing required args, mutually exclusive args.
"""

from __future__ import annotations

import json
import textwrap
from io import StringIO
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.ingest.lifecycle.migration import run_migration_cli
from src.ingest.lifecycle.validation import run_validation_cli


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def changelog_path(tmp_path: Path) -> Path:
    content = textwrap.dedent(
        """\
        schema_versions:
          - version: "0.0.0"
            date: "2026-01-01"
            description: "Baseline"
            migration_strategy: "none"
            fields_added: []
            fields_removed: []
            fields_renamed: {}
          - version: "1.0.0"
            date: "2026-04-15"
            description: "Hardening"
            migration_strategy: "metadata_only"
            fields_added: ["trace_id"]
            fields_removed: []
            fields_renamed: {}
        """
    )
    p = tmp_path / "changelog.yaml"
    p.write_text(content, encoding="utf-8")
    return p


def _empty_manifest() -> dict:
    return {}


def _manifest_one_entry(version: str = "0.0.0") -> dict:
    return {
        "local:doc_a.md": {
            "source_key": "local:doc_a.md",
            "schema_version": version,
            "trace_id": "trace-0001",
            "deleted": False,
        }
    }


# ---------------------------------------------------------------------------
# run_migration_cli tests
# ---------------------------------------------------------------------------


class TestRunMigrationCli:
    def test_dry_run_json_output(
        self, capsys, changelog_path: Path
    ) -> None:
        """--dry-run should emit JSON with dry_run=True and no store mutations."""
        with (
            patch(
                "src.ingest.lifecycle.migration._open_weaviate_client",
                return_value=MagicMock(),
            ),
            patch(
                "src.ingest.lifecycle.migration._open_minio_client",
                return_value=None,
            ),
            patch(
                "src.ingest.lifecycle.migration._resolve_minio_bucket",
                return_value="",
            ),
            patch(
                "src.ingest.lifecycle.migration._load_manifest_cli",
                return_value=_manifest_one_entry("0.0.0"),
            ),
        ):
            exit_code = run_migration_cli(
                [
                    "--from", "0.0.0",
                    "--to", "1.0.0",
                    "--dry-run",
                    "--changelog", str(changelog_path),
                    "--format", "json",
                ]
            )
        assert exit_code == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["dry_run"] is True
        assert data["to_version"] == "1.0.0"
        assert data["eligible"] == 1

    def test_dry_run_text_output(
        self, capsys, changelog_path: Path
    ) -> None:
        """--dry-run --format text should emit a human-readable header."""
        with (
            patch(
                "src.ingest.lifecycle.migration._open_weaviate_client",
                return_value=MagicMock(),
            ),
            patch(
                "src.ingest.lifecycle.migration._open_minio_client",
                return_value=None,
            ),
            patch(
                "src.ingest.lifecycle.migration._resolve_minio_bucket",
                return_value="",
            ),
            patch(
                "src.ingest.lifecycle.migration._load_manifest_cli",
                return_value=_manifest_one_entry("0.0.0"),
            ),
        ):
            exit_code = run_migration_cli(
                [
                    "--from", "0.0.0",
                    "--to", "1.0.0",
                    "--dry-run",
                    "--changelog", str(changelog_path),
                    "--format", "text",
                ]
            )
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Migration Dry Run" in captured.out

    def test_no_confirm_no_dry_run_fails(
        self, changelog_path: Path
    ) -> None:
        """Without --dry-run or --confirm, the CLI must exit non-zero."""
        with pytest.raises(SystemExit) as exc_info:
            run_migration_cli(
                [
                    "--from", "0.0.0",
                    "--to", "1.0.0",
                    "--changelog", str(changelog_path),
                ]
            )
        assert exc_info.value.code != 0

    def test_execute_with_confirm_json(
        self, capsys, changelog_path: Path
    ) -> None:
        """--confirm should run migrations and emit a report with succeeded count."""
        stub_vdb = MagicMock()
        stub_vdb.batch_update_metadata_by_source_key.return_value = 1

        with (
            patch(
                "src.ingest.lifecycle.migration._open_weaviate_client",
                return_value=MagicMock(),
            ),
            patch(
                "src.ingest.lifecycle.migration._open_minio_client",
                return_value=None,
            ),
            patch(
                "src.ingest.lifecycle.migration._resolve_minio_bucket",
                return_value="",
            ),
            patch(
                "src.ingest.lifecycle.migration._load_manifest_cli",
                return_value=_manifest_one_entry("0.0.0"),
            ),
            patch(
                "src.ingest.lifecycle.migration._save_manifest_cli",
            ),
            patch(
                "src.ingest.lifecycle.migration.MigrationEngine._get_vector_db",
                return_value=stub_vdb,
            ),
        ):
            exit_code = run_migration_cli(
                [
                    "--from", "0.0.0",
                    "--to", "1.0.0",
                    "--confirm",
                    "--changelog", str(changelog_path),
                    "--format", "json",
                ]
            )
        assert exit_code == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["to_version"] == "1.0.0"
        assert data["succeeded"] == 1

    def test_empty_manifest_dry_run(
        self, capsys, changelog_path: Path
    ) -> None:
        """Dry-run with empty manifest reports 0 eligible entries."""
        with (
            patch(
                "src.ingest.lifecycle.migration._open_weaviate_client",
                return_value=MagicMock(),
            ),
            patch(
                "src.ingest.lifecycle.migration._open_minio_client",
                return_value=None,
            ),
            patch(
                "src.ingest.lifecycle.migration._resolve_minio_bucket",
                return_value="",
            ),
            patch(
                "src.ingest.lifecycle.migration._load_manifest_cli",
                return_value=_empty_manifest(),
            ),
        ):
            exit_code = run_migration_cli(
                [
                    "--from", "0.0.0",
                    "--to", "1.0.0",
                    "--dry-run",
                    "--changelog", str(changelog_path),
                ]
            )
        assert exit_code == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["eligible"] == 0


# ---------------------------------------------------------------------------
# run_validation_cli tests
# ---------------------------------------------------------------------------


class TestRunValidationCli:
    def _patch_validation_deps(self, monkeypatch, chunk_count: int = 3) -> None:
        """Patch all external deps for the validation CLI."""
        import src.vector_db as vdb_module

        monkeypatch.setattr(
            vdb_module,
            "count_by_trace_id",
            lambda client, tid, collection=None: chunk_count,
            raising=False,
        )

    def test_trace_id_json_consistent(
        self, capsys, monkeypatch
    ) -> None:
        self._patch_validation_deps(monkeypatch, chunk_count=5)
        manifest = {
            "local:doc_a.md": {
                "source_key": "local:doc_a.md",
                "trace_id": "trace-0001",
                "schema_version": "1.0.0",
                "deleted": False,
            }
        }
        with (
            patch(
                "src.ingest.lifecycle.validation._open_weaviate_client",
                return_value=MagicMock(),
            ),
            patch(
                "src.ingest.lifecycle.validation._build_minio_store",
                return_value=None,
            ),
            patch(
                "src.ingest.lifecycle.validation._open_kg_client",
                return_value=None,
            ),
            patch(
                "src.ingest.lifecycle.validation._load_manifest_cli",
                return_value=manifest,
            ),
        ):
            exit_code = run_validation_cli(
                ["--trace-id", "trace-0001", "--format", "json"]
            )
        # Weaviate ok + manifest ok + minio None = consistent
        assert exit_code == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["consistent"] is True
        assert len(data["findings"]) == 1

    def test_trace_id_text_output(
        self, capsys, monkeypatch
    ) -> None:
        self._patch_validation_deps(monkeypatch, chunk_count=2)
        manifest = {
            "local:doc_b.md": {
                "source_key": "local:doc_b.md",
                "trace_id": "trace-0002",
                "schema_version": "1.0.0",
                "deleted": False,
            }
        }
        with (
            patch(
                "src.ingest.lifecycle.validation._open_weaviate_client",
                return_value=MagicMock(),
            ),
            patch(
                "src.ingest.lifecycle.validation._build_minio_store",
                return_value=None,
            ),
            patch(
                "src.ingest.lifecycle.validation._open_kg_client",
                return_value=None,
            ),
            patch(
                "src.ingest.lifecycle.validation._load_manifest_cli",
                return_value=manifest,
            ),
        ):
            exit_code = run_validation_cli(
                ["--trace-id", "trace-0002", "--format", "text"]
            )
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "E2E Validation Report" in captured.out

    def test_all_flag_json(
        self, capsys, monkeypatch
    ) -> None:
        self._patch_validation_deps(monkeypatch, chunk_count=4)
        manifest = {
            "local:doc_c.md": {
                "source_key": "local:doc_c.md",
                "trace_id": "trace-c",
                "schema_version": "1.0.0",
                "deleted": False,
            },
            "local:doc_d.md": {
                "source_key": "local:doc_d.md",
                "trace_id": "trace-d",
                "schema_version": "1.0.0",
                "deleted": False,
            },
        }
        with (
            patch(
                "src.ingest.lifecycle.validation._open_weaviate_client",
                return_value=MagicMock(),
            ),
            patch(
                "src.ingest.lifecycle.validation._build_minio_store",
                return_value=None,
            ),
            patch(
                "src.ingest.lifecycle.validation._open_kg_client",
                return_value=None,
            ),
            patch(
                "src.ingest.lifecycle.validation._load_manifest_cli",
                return_value=manifest,
            ),
        ):
            exit_code = run_validation_cli(["--all", "--format", "json"])
        assert exit_code == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["total_checked"] == 2
        assert data["consistent"] is True

    def test_all_with_sample_flag(
        self, capsys, monkeypatch
    ) -> None:
        self._patch_validation_deps(monkeypatch, chunk_count=1)
        manifest = {
            f"local:doc_{i}.md": {
                "source_key": f"local:doc_{i}.md",
                "trace_id": f"trace-{i:04d}",
                "schema_version": "1.0.0",
                "deleted": False,
            }
            for i in range(8)
        }
        with (
            patch(
                "src.ingest.lifecycle.validation._open_weaviate_client",
                return_value=MagicMock(),
            ),
            patch(
                "src.ingest.lifecycle.validation._build_minio_store",
                return_value=None,
            ),
            patch(
                "src.ingest.lifecycle.validation._open_kg_client",
                return_value=None,
            ),
            patch(
                "src.ingest.lifecycle.validation._load_manifest_cli",
                return_value=manifest,
            ),
        ):
            exit_code = run_validation_cli(
                ["--all", "--sample", "3", "--format", "json"]
            )
        assert exit_code == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["total_checked"] == 3

    def test_mutual_exclusion_trace_id_and_all(self) -> None:
        """--trace-id and --all are mutually exclusive."""
        with pytest.raises(SystemExit) as exc_info:
            run_validation_cli(["--trace-id", "x", "--all"])
        assert exc_info.value.code != 0

    def test_no_args_fails(self) -> None:
        """No --trace-id or --all should exit with error."""
        with pytest.raises(SystemExit) as exc_info:
            run_validation_cli([])
        assert exc_info.value.code != 0

    def test_inconsistent_returns_exit_1(
        self, capsys, monkeypatch
    ) -> None:
        """validate_all with an inconsistent finding returns exit code 1."""
        # Zero chunks in Weaviate for this trace_id => inconsistent.
        self._patch_validation_deps(monkeypatch, chunk_count=0)
        manifest = {
            "local:doc_z.md": {
                "source_key": "local:doc_z.md",
                "trace_id": "trace-z",
                "schema_version": "1.0.0",
                "deleted": False,
            }
        }
        with (
            patch(
                "src.ingest.lifecycle.validation._open_weaviate_client",
                return_value=MagicMock(),
            ),
            patch(
                "src.ingest.lifecycle.validation._build_minio_store",
                return_value=None,
            ),
            patch(
                "src.ingest.lifecycle.validation._open_kg_client",
                return_value=None,
            ),
            patch(
                "src.ingest.lifecycle.validation._load_manifest_cli",
                return_value=manifest,
            ),
        ):
            exit_code = run_validation_cli(["--all", "--format", "json"])
        assert exit_code == 1
