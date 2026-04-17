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
