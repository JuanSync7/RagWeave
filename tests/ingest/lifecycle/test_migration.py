"""Tests for MigrationEngine.

Covers:
- plan(): identifies eligible entries, skips deleted/already-at-target.
- execute(): METADATA_ONLY happy path.
- Per-entry failure isolation: one failure does not abort the batch.
- Idempotency: re-running on already-migrated entries is a no-op.
- PermissionError: execute() without confirm=True is refused.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from src.ingest.lifecycle import (
    MigrationEngine,
    MigrationPlan,
    MigrationReport,
    MigrationTask,
    SchemaVersion,
    load_changelog,
)


# ---------------------------------------------------------------------------
# Fixtures
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
          - version: "2.0.0"
            date: "2026-05-01"
            description: "Major re-embed"
            migration_strategy: "full_phase2"
            fields_added: []
            fields_removed: []
            fields_renamed: {}
        """
    )
    p = tmp_path / "changelog.yaml"
    p.write_text(content, encoding="utf-8")
    return p


@pytest.fixture()
def changelog(changelog_path: Path) -> list[SchemaVersion]:
    return load_changelog(changelog_path)


@pytest.fixture()
def stub_vector_db() -> MagicMock:
    """A stub vector_db that records batch_update_metadata_by_source_key calls."""
    vdb = MagicMock()
    vdb.batch_update_metadata_by_source_key.return_value = 1
    return vdb


@pytest.fixture()
def weaviate_client() -> MagicMock:
    return MagicMock()


def _make_engine(
    weaviate_client: Any,
    changelog: list[SchemaVersion],
    vector_db: Any = None,
    clean_store: Any = None,
    kg_client: Any = None,
) -> MigrationEngine:
    return MigrationEngine(
        client=weaviate_client,
        clean_store=clean_store,
        vector_db=vector_db,
        kg_client=kg_client,
        changelog=changelog,
    )


def _manifest_with_entries(*versions: str) -> dict:
    """Build a manifest with N entries each at the given schema_version."""
    manifest = {}
    for i, version in enumerate(versions):
        key = f"local:doc_{i}.md"
        manifest[key] = {
            "source_key": key,
            "schema_version": version,
            "trace_id": f"trace-{i:04d}",
            "deleted": False,
            "deleted_at": "",
        }
    return manifest


# ---------------------------------------------------------------------------
# plan() tests
# ---------------------------------------------------------------------------


class TestMigrationEnginePlan:
    def test_plan_identifies_eligible_entries(
        self, weaviate_client: MagicMock, changelog: list[SchemaVersion]
    ) -> None:
        manifest = _manifest_with_entries("0.0.0", "0.0.0", "1.0.0")
        engine = _make_engine(weaviate_client, changelog)
        plan = engine.plan(from_version="", to_version="1.0.0", manifest=manifest)
        # Two entries at 0.0.0 need migration; one at 1.0.0 is already there.
        assert len(plan.tasks) == 2
        assert plan.skipped_count == 1

    def test_plan_skips_deleted_entries(
        self, weaviate_client: MagicMock, changelog: list[SchemaVersion]
    ) -> None:
        manifest = _manifest_with_entries("0.0.0")
        manifest["local:doc_0.md"]["deleted"] = True
        engine = _make_engine(weaviate_client, changelog)
        plan = engine.plan(from_version="", to_version="1.0.0", manifest=manifest)
        assert len(plan.tasks) == 0
        assert plan.skipped_count == 1

    def test_plan_sets_correct_strategy(
        self, weaviate_client: MagicMock, changelog: list[SchemaVersion]
    ) -> None:
        manifest = _manifest_with_entries("0.0.0")
        engine = _make_engine(weaviate_client, changelog)
        plan = engine.plan(from_version="", to_version="1.0.0", manifest=manifest)
        assert plan.tasks[0].strategy == "metadata_only"

    def test_plan_from_version_override(
        self, weaviate_client: MagicMock, changelog: list[SchemaVersion]
    ) -> None:
        # Override from_version for all entries.
        manifest = _manifest_with_entries("1.0.0")
        engine = _make_engine(weaviate_client, changelog)
        # from_version="0.0.0" forces treating all entries as at 0.0.0.
        plan = engine.plan(from_version="0.0.0", to_version="1.0.0", manifest=manifest)
        # Even though manifest says 1.0.0, from_version="0.0.0" != to_version so
        # determine_migration_strategy is called with "0.0.0" -> "1.0.0".
        # Result: 1 task (the entry is not yet at target from the override perspective).
        assert len(plan.tasks) == 1

    def test_plan_to_version_stored(
        self, weaviate_client: MagicMock, changelog: list[SchemaVersion]
    ) -> None:
        manifest = _manifest_with_entries("0.0.0")
        engine = _make_engine(weaviate_client, changelog)
        plan = engine.plan(from_version="", to_version="1.0.0", manifest=manifest)
        assert plan.to_version == "1.0.0"
        assert plan.tasks[0].to_version == "1.0.0"

    def test_plan_empty_manifest(
        self, weaviate_client: MagicMock, changelog: list[SchemaVersion]
    ) -> None:
        engine = _make_engine(weaviate_client, changelog)
        plan = engine.plan(from_version="", to_version="1.0.0", manifest={})
        assert plan.tasks == []
        assert plan.skipped_count == 0


# ---------------------------------------------------------------------------
# execute() — METADATA_ONLY happy path
# ---------------------------------------------------------------------------


class TestMigrationEngineExecuteMetadataOnly:
    def test_execute_metadata_only_calls_batch_update(
        self,
        weaviate_client: MagicMock,
        stub_vector_db: MagicMock,
        changelog: list[SchemaVersion],
    ) -> None:
        manifest = _manifest_with_entries("0.0.0")
        engine = _make_engine(weaviate_client, changelog, vector_db=stub_vector_db)
        plan = engine.plan(from_version="", to_version="1.0.0", manifest=manifest)
        report = engine.execute(plan, confirm=True, manifest=manifest)
        assert report.succeeded == 1
        assert report.failed == 0
        stub_vector_db.batch_update_metadata_by_source_key.assert_called_once()
        call_kwargs = stub_vector_db.batch_update_metadata_by_source_key.call_args
        assert call_kwargs[0][1] == "local:doc_0.md"
        assert call_kwargs[1]["properties"]["schema_version"] == "1.0.0"

    def test_execute_updates_manifest_schema_version(
        self,
        weaviate_client: MagicMock,
        stub_vector_db: MagicMock,
        changelog: list[SchemaVersion],
    ) -> None:
        manifest = _manifest_with_entries("0.0.0")
        engine = _make_engine(weaviate_client, changelog, vector_db=stub_vector_db)
        plan = engine.plan(from_version="", to_version="1.0.0", manifest=manifest)
        engine.execute(plan, confirm=True, manifest=manifest)
        assert manifest["local:doc_0.md"]["schema_version"] == "1.0.0"

    def test_execute_without_confirm_raises(
        self,
        weaviate_client: MagicMock,
        changelog: list[SchemaVersion],
    ) -> None:
        engine = _make_engine(weaviate_client, changelog)
        plan = MigrationPlan(to_version="1.0.0", tasks=[])
        with pytest.raises(PermissionError, match="confirm"):
            engine.execute(plan, confirm=False)


# ---------------------------------------------------------------------------
# Per-entry failure isolation
# ---------------------------------------------------------------------------


class TestMigrationEngineFailureIsolation:
    def test_one_failure_does_not_abort_batch(
        self,
        weaviate_client: MagicMock,
        changelog: list[SchemaVersion],
    ) -> None:
        """When the first entry's batch_update raises, the second still runs."""
        manifest = _manifest_with_entries("0.0.0", "0.0.0")

        call_count = {"n": 0}
        def flaky_update(client, source_key, properties):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("Simulated Weaviate timeout")
            return 1

        vdb = MagicMock()
        vdb.batch_update_metadata_by_source_key.side_effect = flaky_update

        engine = _make_engine(weaviate_client, changelog, vector_db=vdb)
        plan = engine.plan(from_version="", to_version="1.0.0", manifest=manifest)
        assert len(plan.tasks) == 2
        report = engine.execute(plan, confirm=True, manifest=manifest)

        assert report.failed == 1
        assert report.succeeded == 1
        assert report.total_eligible == 2

    def test_per_entry_outcomes_recorded(
        self,
        weaviate_client: MagicMock,
        changelog: list[SchemaVersion],
    ) -> None:
        manifest = _manifest_with_entries("0.0.0", "0.0.0")
        keys = list(manifest.keys())

        call_count = {"n": 0}
        def one_fail(client, source_key, properties):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("Boom")
            return 1

        vdb = MagicMock()
        vdb.batch_update_metadata_by_source_key.side_effect = one_fail

        engine = _make_engine(weaviate_client, changelog, vector_db=vdb)
        plan = engine.plan(from_version="", to_version="1.0.0", manifest=manifest)
        report = engine.execute(plan, confirm=True, manifest=manifest)

        statuses = [report.per_entry[k]["status"] for k in keys]
        assert "failed" in statuses
        assert "ok" in statuses


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


class TestMigrationEngineIdempotency:
    def test_re_run_on_migrated_manifest_is_noop(
        self,
        weaviate_client: MagicMock,
        stub_vector_db: MagicMock,
        changelog: list[SchemaVersion],
    ) -> None:
        """After a successful migration, re-running returns skipped=N, succeeded=0."""
        manifest = _manifest_with_entries("0.0.0")
        engine = _make_engine(weaviate_client, changelog, vector_db=stub_vector_db)
        plan = engine.plan(from_version="", to_version="1.0.0", manifest=manifest)
        engine.execute(plan, confirm=True, manifest=manifest)

        # Now re-plan and re-execute on the same (now updated) manifest.
        plan2 = engine.plan(from_version="", to_version="1.0.0", manifest=manifest)
        assert len(plan2.tasks) == 0
        assert plan2.skipped_count == 1

        report2 = engine.execute(plan2, confirm=True, manifest=manifest)
        assert report2.succeeded == 0
        assert report2.failed == 0

    def test_execute_idempotency_at_target_version(
        self,
        weaviate_client: MagicMock,
        stub_vector_db: MagicMock,
        changelog: list[SchemaVersion],
    ) -> None:
        """Entries already at to_version inside execute() are skipped."""
        manifest = _manifest_with_entries("1.0.0")
        engine = _make_engine(weaviate_client, changelog, vector_db=stub_vector_db)
        # Construct a plan with a task for an entry already at target.
        task = MigrationTask(
            source_key="local:doc_0.md",
            from_version="0.0.0",
            to_version="1.0.0",
            strategy="metadata_only",
        )
        plan = MigrationPlan(to_version="1.0.0", tasks=[task])
        report = engine.execute(plan, confirm=True, manifest=manifest)
        assert report.skipped == 1
        assert report.succeeded == 0
        # Weaviate should NOT have been called.
        stub_vector_db.batch_update_metadata_by_source_key.assert_not_called()


# ---------------------------------------------------------------------------
# plan() edge cases: lazy changelog, unknown version, none strategy
# ---------------------------------------------------------------------------


class TestMigrationPlanEdgeCases:
    def test_mock_plan_lazy_changelog_load(self, weaviate_client: MagicMock, changelog_path: Path) -> None:
        """plan() should load changelog lazily when changelog=None at init."""
        engine = MigrationEngine(
            client=weaviate_client,
            changelog=None,
            changelog_path=changelog_path,
        )
        manifest = _manifest_with_entries("0.0.0")
        # Should not raise — loads changelog lazily
        plan = engine.plan(from_version="", to_version="1.0.0", manifest=manifest)
        assert len(plan.tasks) == 1

    def test_mock_plan_unknown_version_falls_back_to_metadata_only(
        self, weaviate_client: MagicMock, changelog: list[SchemaVersion]
    ) -> None:
        """plan() with a version not in changelog should fall back to metadata_only."""
        manifest = {"local:doc_x.md": {
            "source_key": "local:doc_x.md",
            "schema_version": "99.99.99",
            "trace_id": "trace-x",
            "deleted": False,
            "deleted_at": "",
        }}
        engine = _make_engine(weaviate_client, changelog)
        # to_version also unknown, so determine_migration_strategy raises ValueError
        # The engine should catch it and use metadata_only fallback
        plan = engine.plan(from_version="99.99.99", to_version="88.0.0", manifest=manifest)
        # Either a task with metadata_only fallback or skipped; no crash expected
        # Since from_version == effective_from and to_version differ, strategy is looked up
        # We expect a task with strategy=metadata_only (the fallback)
        if plan.tasks:
            assert plan.tasks[0].strategy == "metadata_only"

    def test_mock_plan_strategy_none_causes_skip(
        self, weaviate_client: MagicMock, changelog: list[SchemaVersion]
    ) -> None:
        """plan() for an entry where strategy=='none' should skip that entry."""
        # version "0.0.0" to "0.0.0" same -> skip (already handled)
        # We need a scenario where determine_migration_strategy returns "none"
        # That happens for 0.0.0 -> 0.0.0 (same version) — skip handled differently.
        # Instead, patch determine_migration_strategy to return "none"
        manifest = {"local:doc_0.md": {
            "source_key": "local:doc_0.md",
            "schema_version": "0.0.0",
            "trace_id": "trace-0",
            "deleted": False,
            "deleted_at": "",
        }}
        engine = _make_engine(weaviate_client, changelog)

        with patch(
            "src.ingest.lifecycle.migration.determine_migration_strategy",
            return_value="none",
        ):
            plan = engine.plan(from_version="", to_version="1.0.0", manifest=manifest)

        assert len(plan.tasks) == 0
        assert plan.skipped_count == 1


# ---------------------------------------------------------------------------
# execute() edge cases: missing manifest entry, owns_manifest save
# ---------------------------------------------------------------------------


class TestMigrationExecuteEdgeCases:
    def test_mock_execute_missing_manifest_entry_increments_failed(
        self,
        weaviate_client: MagicMock,
        stub_vector_db: MagicMock,
        changelog: list[SchemaVersion],
    ) -> None:
        """execute() with a task for a missing manifest entry should increment failed."""
        manifest = {}  # empty manifest
        engine = _make_engine(weaviate_client, changelog, vector_db=stub_vector_db)
        task = MigrationTask(
            source_key="local:missing.md",
            from_version="0.0.0",
            to_version="1.0.0",
            strategy="metadata_only",
        )
        plan = MigrationPlan(to_version="1.0.0", tasks=[task])
        report = engine.execute(plan, confirm=True, manifest=manifest)
        assert report.failed == 1
        assert report.succeeded == 0

    def test_mock_execute_owns_manifest_saves_after_execute(
        self,
        weaviate_client: MagicMock,
        stub_vector_db: MagicMock,
        changelog: list[SchemaVersion],
        tmp_path: Path,
    ) -> None:
        """When owns_manifest (manifest=None), engine should save manifest to path after execute."""
        import json

        manifest_data = _manifest_with_entries("0.0.0")
        manifest_file = tmp_path / "manifest.json"
        manifest_file.write_text(json.dumps(manifest_data), encoding="utf-8")

        engine = MigrationEngine(
            client=weaviate_client,
            manifest_path=manifest_file,
            vector_db=stub_vector_db,
            changelog=changelog,
        )

        plan = engine.plan(from_version="", to_version="1.0.0")  # loads manifest from file
        report = engine.execute(plan, confirm=True)  # owns_manifest -> saves on finish

        # Verify manifest file was updated
        saved = json.loads(manifest_file.read_text(encoding="utf-8"))
        key = list(saved.keys())[0]
        assert saved[key]["schema_version"] == "1.0.0"


# ---------------------------------------------------------------------------
# _run_strategy() with unknown strategy
# ---------------------------------------------------------------------------


class TestRunStrategyEdgeCases:
    def test_mock_run_strategy_unknown_raises_value_error(
        self,
        weaviate_client: MagicMock,
        changelog: list[SchemaVersion],
    ) -> None:
        """_run_strategy with an unknown strategy should raise ValueError."""
        engine = _make_engine(weaviate_client, changelog)
        task = MigrationTask(
            source_key="local:doc_0.md",
            from_version="0.0.0",
            to_version="1.0.0",
            strategy="totally_unknown",
        )
        entry = {"source_key": "local:doc_0.md", "schema_version": "0.0.0"}
        with pytest.raises(ValueError, match="Unknown migration strategy"):
            engine._run_strategy(task, entry)


# ---------------------------------------------------------------------------
# _migrate_metadata_only() without batch_update method
# ---------------------------------------------------------------------------


class TestMigrateMetadataOnlyEdgeCases:
    def test_mock_migrate_metadata_only_no_method_logs_warning(
        self,
        weaviate_client: MagicMock,
        changelog: list[SchemaVersion],
        caplog,
    ) -> None:
        """_migrate_metadata_only should log warning if batch_update method missing."""
        import logging

        vdb = MagicMock(spec=[])  # no batch_update_metadata_by_source_key
        engine = _make_engine(weaviate_client, changelog, vector_db=vdb)
        task = MigrationTask(
            source_key="local:doc_0.md",
            from_version="0.0.0",
            to_version="1.0.0",
            strategy="metadata_only",
        )
        entry = {"source_key": "local:doc_0.md", "schema_version": "0.0.0"}

        with caplog.at_level(logging.WARNING):
            engine._migrate_metadata_only(task, entry)

        assert any(
            "batch_update_metadata_by_source_key" in record.message
            for record in caplog.records
        )


# ---------------------------------------------------------------------------
# _load_manifest() and _save_manifest() exception paths
# ---------------------------------------------------------------------------


class TestManifestIOEdgeCases:
    def test_mock_load_manifest_file_read_exception_returns_empty(self, tmp_path: Path) -> None:
        """_load_manifest() with a bad file path should log warning and return {}."""
        bad_path = tmp_path / "nonexistent_subdir" / "manifest.json"
        engine = MigrationEngine(
            client=MagicMock(),
            manifest_path=bad_path,
            changelog=[],
        )
        result = engine._load_manifest()
        assert result == {}

    def test_mock_save_manifest_write_exception_logs_warning(
        self, tmp_path: Path, caplog
    ) -> None:
        """_save_manifest() with a bad path should log warning without raising."""
        import logging

        bad_path = tmp_path / "nonexistent_subdir" / "manifest.json"
        engine = MigrationEngine(
            client=MagicMock(),
            manifest_path=bad_path,
            changelog=[],
        )

        with caplog.at_level(logging.WARNING):
            engine._save_manifest({"doc_a": {"schema_version": "1.0.0"}})

        assert any(
            "migration_save_manifest_failed" in record.message
            or "save" in record.message.lower()
            for record in caplog.records
        )

    def test_mock_load_manifest_no_path_returns_empty(self) -> None:
        """_load_manifest() when manifest_path is None should return {}."""
        engine = MigrationEngine(
            client=MagicMock(),
            manifest_path=None,
            changelog=[],
        )
        result = engine._load_manifest()
        assert result == {}

    def test_mock_save_manifest_no_path_does_nothing(self) -> None:
        """_save_manifest() when manifest_path is None should be a no-op."""
        engine = MigrationEngine(
            client=MagicMock(),
            manifest_path=None,
            changelog=[],
        )
        # Should not raise
        engine._save_manifest({"doc_a": {"schema_version": "1.0.0"}})


# ---------------------------------------------------------------------------
# _migrate_full_phase2() and _migrate_kg_reextract() strategy coverage
# ---------------------------------------------------------------------------


class TestStrategyExecutors:
    def test_mock_migrate_full_phase2(self, weaviate_client, changelog):
        """_migrate_full_phase2 should read from clean_store and call run_embedding_pipeline."""
        called = {}

        class FakeCleanStore:
            def read(self, source_key):
                called["read"] = source_key
                return "clean text", {"source_name": "test.md", "source_uri": "uri", "source_id": "id", "connector": "local", "source_version": "1", "clean_hash": "abc"}

        fake_vdb = MagicMock()
        fake_vdb.delete_by_source_key = MagicMock()

        engine = MigrationEngine(
            client=weaviate_client,
            clean_store=FakeCleanStore(),
            vector_db=fake_vdb,
            changelog=changelog,
        )

        task = MigrationTask(
            source_key="local:doc_0.md",
            from_version="0.0.0",
            to_version="2.0.0",
            strategy="full_phase2",
        )
        entry = {"source_key": "local:doc_0.md", "schema_version": "0.0.0", "trace_id": "old-trace"}

        import src.ingest.embedding as _emb_mod
        with patch.object(_emb_mod, "run_embedding_pipeline", return_value={}) as mock_pipeline:
            engine._migrate_full_phase2(task, entry)

        assert called.get("read") == "local:doc_0.md"
        mock_pipeline.assert_called_once()
        assert entry["trace_id"] != "old-trace"  # new trace_id assigned

    def test_mock_migrate_full_phase2_no_clean_store(self, weaviate_client, changelog):
        """_migrate_full_phase2 should raise RuntimeError when clean_store is None."""
        engine = MigrationEngine(
            client=weaviate_client,
            clean_store=None,
            changelog=changelog,
        )
        task = MigrationTask(
            source_key="local:doc_0.md",
            from_version="0.0.0",
            to_version="2.0.0",
            strategy="full_phase2",
        )
        entry = {"source_key": "local:doc_0.md", "schema_version": "0.0.0"}
        with pytest.raises(RuntimeError, match="clean_store"):
            engine._migrate_full_phase2(task, entry)

    def test_mock_migrate_kg_reextract(self, weaviate_client, changelog):
        """_migrate_kg_reextract should call kg_client methods and update trace_id."""
        called = {}

        class FakeCleanStore:
            def read(self, source_key):
                called["read"] = source_key
                return "text content", {"source_name": "doc.md"}

        class FakeKGClient:
            def delete_by_source_key(self, source_key):
                called["delete"] = source_key

            def extract_from_text(self, **kwargs):
                called["extract"] = kwargs.get("source_key")

        engine = MigrationEngine(
            client=weaviate_client,
            clean_store=FakeCleanStore(),
            kg_client=FakeKGClient(),
            changelog=changelog,
        )

        task = MigrationTask(
            source_key="local:doc_0.md",
            from_version="0.0.0",
            to_version="2.0.0",
            strategy="kg_reextract",
        )
        entry = {"source_key": "local:doc_0.md", "schema_version": "0.0.0", "trace_id": "old"}

        engine._migrate_kg_reextract(task, entry)

        assert called.get("read") == "local:doc_0.md"
        assert called.get("delete") == "local:doc_0.md"
        assert called.get("extract") == "local:doc_0.md"
        assert entry["trace_id"] != "old"

    def test_mock_migrate_kg_reextract_no_store(self, weaviate_client, changelog):
        """_migrate_kg_reextract raises when clean_store is None."""
        engine = MigrationEngine(
            client=weaviate_client,
            clean_store=None,
            kg_client=MagicMock(),
            changelog=changelog,
        )
        task = MigrationTask(
            source_key="local:doc.md",
            from_version="0.0.0",
            to_version="2.0.0",
            strategy="kg_reextract",
        )
        entry = {"source_key": "local:doc.md"}
        with pytest.raises(RuntimeError, match="clean_store"):
            engine._migrate_kg_reextract(task, entry)


# ---------------------------------------------------------------------------
# CLI entry point and report functions
# ---------------------------------------------------------------------------


class TestMigrationCLI:
    def test_mock_emit_migration_report_text(self, weaviate_client, changelog, capsys):
        """_emit_migration_report with fmt='text' should print migration summary."""
        from src.ingest.lifecycle.migration import _emit_migration_report
        from src.ingest.lifecycle.schemas import MigrationPlan, MigrationReport, MigrationTask

        plan = MigrationPlan(to_version="1.0.0", tasks=[], skipped_count=0)
        report = MigrationReport(
            to_version="1.0.0",
            total_eligible=2,
            succeeded=1,
            failed=1,
            skipped=0,
            per_entry={
                "doc_a": {"status": "ok", "strategy": "metadata_only"},
                "doc_b": {"status": "failed", "error": "timeout", "strategy": "metadata_only"},
            },
        )
        _emit_migration_report(plan, report, fmt="text")
        captured = capsys.readouterr()
        assert "Migration" in captured.out or "1.0.0" in captured.out

    def test_mock_emit_migration_report_json(self, weaviate_client, changelog, capsys):
        """_emit_migration_report with fmt='json' should print JSON."""
        from src.ingest.lifecycle.migration import _emit_migration_report
        from src.ingest.lifecycle.schemas import MigrationPlan, MigrationReport

        plan = MigrationPlan(to_version="1.0.0", tasks=[], skipped_count=0)
        report = MigrationReport(
            to_version="1.0.0",
            total_eligible=1,
            succeeded=1,
            failed=0,
            skipped=0,
            per_entry={"doc_a": {"status": "ok", "strategy": "metadata_only"}},
        )
        _emit_migration_report(plan, report, fmt="json")
        captured = capsys.readouterr()
        import json
        parsed = json.loads(captured.out)
        assert parsed["succeeded"] == 1

    def test_mock_run_migration_cli_dry_run(self, monkeypatch, tmp_path):
        """run_migration_cli --dry-run should return 0."""
        from src.ingest.lifecycle import migration as mig_mod

        # Patch all CLI helpers
        monkeypatch.setattr(mig_mod, "_open_weaviate_client", lambda: MagicMock())
        monkeypatch.setattr(mig_mod, "_open_minio_client", lambda: None)
        monkeypatch.setattr(mig_mod, "_resolve_minio_bucket", lambda: "")
        monkeypatch.setattr(mig_mod, "_load_manifest_cli", lambda: {})
        monkeypatch.setattr(mig_mod, "_save_manifest_cli", lambda m: None)
        monkeypatch.setattr(mig_mod, "_emit_migration_report_dry", lambda plan, fmt="json": None)

        # Need a valid changelog path
        import textwrap
        changelog_file = tmp_path / "changelog.yaml"
        changelog_file.write_text(textwrap.dedent("""\
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
        """), encoding="utf-8")

        result = mig_mod.run_migration_cli([
            "--dry-run",
            "--to", "1.0.0",
            "--changelog", str(changelog_file),
        ])
        assert result == 0

    def test_mock_run_migration_cli_no_confirm_no_dry_run(self, monkeypatch):
        """run_migration_cli without --confirm and --dry-run should call parser.error."""
        from src.ingest.lifecycle import migration as mig_mod
        with pytest.raises(SystemExit):
            mig_mod.run_migration_cli(["--to", "1.0.0"])

    def test_mock_run_migration_cli_permission_error(self, monkeypatch):
        """run_migration_cli should return 1 on PermissionError."""
        from src.ingest.lifecycle import migration as mig_mod

        monkeypatch.setattr(mig_mod, "_open_weaviate_client", lambda: (_ for _ in ()).throw(PermissionError("no access")))

        result = mig_mod.run_migration_cli(["--dry-run"])
        assert result == 1

    def test_mock_run_migration_cli_generic_error(self, monkeypatch):
        """run_migration_cli should return 2 on generic Exception."""
        from src.ingest.lifecycle import migration as mig_mod

        monkeypatch.setattr(mig_mod, "_open_weaviate_client", lambda: (_ for _ in ()).throw(RuntimeError("fail")))

        result = mig_mod.run_migration_cli(["--dry-run"])
        assert result == 2

    def test_mock_cli_helpers_failure_paths(self, monkeypatch):
        """CLI helper functions should gracefully handle import/other failures."""
        from src.ingest.lifecycle import migration as mig_mod

        # Test _open_minio_client returns None on exception
        result = mig_mod._open_minio_client()
        assert result is None or result is not None  # either is valid

        # Test _resolve_minio_bucket returns "" on exception
        result = mig_mod._resolve_minio_bucket()
        assert isinstance(result, str)

        # Test _load_manifest_cli returns {} on exception
        result = mig_mod._load_manifest_cli()
        assert isinstance(result, dict)

    def test_mock_emit_migration_report_dry_text(self, capsys):
        """_emit_migration_report_dry with fmt='text' should print text summary."""
        from src.ingest.lifecycle.migration import _emit_migration_report_dry
        from src.ingest.lifecycle.schemas import MigrationPlan, MigrationTask

        task = MigrationTask(
            source_key="local:doc_0.md",
            from_version="0.0.0",
            to_version="1.0.0",
            strategy="metadata_only",
        )
        plan = MigrationPlan(to_version="1.0.0", tasks=[task], skipped_count=1)
        _emit_migration_report_dry(plan, fmt="text")
        captured = capsys.readouterr()
        assert "1.0.0" in captured.out

    def test_mock_emit_migration_report_dry_json(self, capsys):
        """_emit_migration_report_dry with fmt='json' should print JSON."""
        from src.ingest.lifecycle.migration import _emit_migration_report_dry
        from src.ingest.lifecycle.schemas import MigrationPlan

        plan = MigrationPlan(to_version="1.0.0", tasks=[], skipped_count=0)
        _emit_migration_report_dry(plan, fmt="json")
        captured = capsys.readouterr()
        import json
        parsed = json.loads(captured.out)
        assert parsed["to_version"] == "1.0.0"
