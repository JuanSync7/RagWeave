"""Tests for the schema changelog parser and migration strategy resolver.

Covers:
- load_changelog: valid file, missing file, malformed file, duplicate versions.
- get_required_migrations: empty range, forward range, downgrade.
- determine_migration_strategy: various version pairs, strategy escalation.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml

from src.ingest.lifecycle.changelog import (
    MigrationStrategy,
    SchemaVersion,
    determine_migration_strategy,
    get_required_migrations,
    load_changelog,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def changelog_yaml(tmp_path: Path) -> Path:
    """Write a minimal valid changelog to a temp file."""
    content = textwrap.dedent(
        """\
        schema_versions:
          - version: "0.0.0"
            date: "2026-01-01"
            description: "Baseline"
            migration_strategy: "none"
            fields_added: []
            fields_removed: []
            fields_renamed: []

          - version: "1.0.0"
            date: "2026-04-15"
            description: "First versioned schema"
            migration_strategy: "metadata_only"
            fields_added: ["trace_id", "batch_id"]
            fields_removed: []
            fields_renamed: []

          - version: "2.0.0"
            date: "2026-05-01"
            description: "Full re-embedding required"
            migration_strategy: "full_phase2"
            fields_added: ["new_vector"]
            fields_removed: ["old_vector"]
            fields_renamed: {}

          - version: "2.1.0"
            date: "2026-05-15"
            description: "KG extraction change"
            migration_strategy: "kg_reextract"
            fields_added: []
            fields_removed: []
            fields_renamed: {}
        """
    )
    p = tmp_path / "changelog.yaml"
    p.write_text(content, encoding="utf-8")
    return p


@pytest.fixture()
def changelog(changelog_yaml: Path) -> list[SchemaVersion]:
    return load_changelog(changelog_yaml)


# ---------------------------------------------------------------------------
# load_changelog tests
# ---------------------------------------------------------------------------


class TestLoadChangelog:
    def test_loads_all_entries(self, changelog: list[SchemaVersion]) -> None:
        assert len(changelog) == 4

    def test_first_entry_is_baseline(self, changelog: list[SchemaVersion]) -> None:
        assert changelog[0].version == "0.0.0"
        assert changelog[0].migration_strategy == "none"

    def test_fields_added_parsed(self, changelog: list[SchemaVersion]) -> None:
        v100 = next(sv for sv in changelog if sv.version == "1.0.0")
        assert "trace_id" in v100.fields_added
        assert "batch_id" in v100.fields_added

    def test_fields_removed_parsed(self, changelog: list[SchemaVersion]) -> None:
        v200 = next(sv for sv in changelog if sv.version == "2.0.0")
        assert "old_vector" in v200.fields_removed

    def test_strategy_full_phase2(self, changelog: list[SchemaVersion]) -> None:
        v200 = next(sv for sv in changelog if sv.version == "2.0.0")
        assert v200.migration_strategy == "full_phase2"

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_changelog(tmp_path / "nonexistent.yaml")

    def test_missing_required_field_raises(self, tmp_path: Path) -> None:
        bad = textwrap.dedent(
            """\
            schema_versions:
              - version: "1.0.0"
                date: "2026-01-01"
                description: "ok"
                # migration_strategy is intentionally missing
            """
        )
        p = tmp_path / "bad.yaml"
        p.write_text(bad, encoding="utf-8")
        with pytest.raises(ValueError, match="migration_strategy"):
            load_changelog(p)

    def test_unknown_strategy_raises(self, tmp_path: Path) -> None:
        bad = textwrap.dedent(
            """\
            schema_versions:
              - version: "1.0.0"
                date: "2026-01-01"
                description: "ok"
                migration_strategy: "teleport"
            """
        )
        p = tmp_path / "bad.yaml"
        p.write_text(bad, encoding="utf-8")
        with pytest.raises(ValueError, match="teleport"):
            load_changelog(p)

    def test_no_schema_versions_key_raises(self, tmp_path: Path) -> None:
        bad = "not_schema_versions: []\n"
        p = tmp_path / "bad.yaml"
        p.write_text(bad, encoding="utf-8")
        with pytest.raises(ValueError, match="schema_versions"):
            load_changelog(p)

    def test_duplicate_version_raises(self, tmp_path: Path) -> None:
        dup = textwrap.dedent(
            """\
            schema_versions:
              - version: "1.0.0"
                date: "2026-01-01"
                description: "first"
                migration_strategy: "none"
              - version: "1.0.0"
                date: "2026-01-02"
                description: "duplicate"
                migration_strategy: "metadata_only"
            """
        )
        p = tmp_path / "dup.yaml"
        p.write_text(dup, encoding="utf-8")
        with pytest.raises(ValueError, match="Duplicate"):
            load_changelog(p)

    def test_real_project_changelog_parses(self) -> None:
        """The actual project changelog must parse cleanly."""
        project_root = Path(__file__).parents[3]
        real_path = project_root / "config" / "schema_changelog.yaml"
        if not real_path.exists():
            pytest.skip("config/schema_changelog.yaml not found")
        entries = load_changelog(real_path)
        assert len(entries) >= 1
        assert entries[0].version == "0.0.0"


# ---------------------------------------------------------------------------
# get_required_migrations tests
# ---------------------------------------------------------------------------


class TestGetRequiredMigrations:
    def test_same_version_returns_empty(
        self, changelog: list[SchemaVersion]
    ) -> None:
        result = get_required_migrations("1.0.0", "1.0.0", changelog)
        assert result == []

    def test_single_step_forward(
        self, changelog: list[SchemaVersion]
    ) -> None:
        result = get_required_migrations("0.0.0", "1.0.0", changelog)
        assert len(result) == 1
        assert result[0].version == "1.0.0"

    def test_multi_step_forward(
        self, changelog: list[SchemaVersion]
    ) -> None:
        result = get_required_migrations("0.0.0", "2.1.0", changelog)
        assert [sv.version for sv in result] == ["1.0.0", "2.0.0", "2.1.0"]

    def test_partial_range(self, changelog: list[SchemaVersion]) -> None:
        result = get_required_migrations("1.0.0", "2.1.0", changelog)
        assert [sv.version for sv in result] == ["2.0.0", "2.1.0"]

    def test_downgrade_returns_empty(
        self, changelog: list[SchemaVersion]
    ) -> None:
        result = get_required_migrations("2.0.0", "1.0.0", changelog)
        assert result == []

    def test_unknown_from_version_raises(
        self, changelog: list[SchemaVersion]
    ) -> None:
        with pytest.raises(ValueError, match="from_version"):
            get_required_migrations("9.9.9", "1.0.0", changelog)

    def test_unknown_to_version_raises(
        self, changelog: list[SchemaVersion]
    ) -> None:
        with pytest.raises(ValueError, match="to_version"):
            get_required_migrations("0.0.0", "9.9.9", changelog)


# ---------------------------------------------------------------------------
# determine_migration_strategy tests
# ---------------------------------------------------------------------------


class TestDetermineMigrationStrategy:
    def test_same_version_is_none(self, changelog: list[SchemaVersion]) -> None:
        assert determine_migration_strategy("1.0.0", "1.0.0", changelog) == "none"

    def test_metadata_only_range(self, changelog: list[SchemaVersion]) -> None:
        # 0.0.0 -> 1.0.0 only passes through metadata_only entry
        assert (
            determine_migration_strategy("0.0.0", "1.0.0", changelog)
            == "metadata_only"
        )

    def test_full_phase2_dominates(self, changelog: list[SchemaVersion]) -> None:
        # 0.0.0 -> 2.0.0 passes through metadata_only AND full_phase2;
        # full_phase2 should win (higher rank).
        assert (
            determine_migration_strategy("0.0.0", "2.0.0", changelog)
            == "full_phase2"
        )

    def test_full_phase2_dominates_kg_reextract(
        self, changelog: list[SchemaVersion]
    ) -> None:
        # 0.0.0 -> 2.1.0 passes through full_phase2 AND kg_reextract;
        # full_phase2 rank > kg_reextract, so full_phase2 wins.
        assert (
            determine_migration_strategy("0.0.0", "2.1.0", changelog)
            == "full_phase2"
        )

    def test_kg_reextract_range(self, changelog: list[SchemaVersion]) -> None:
        # 2.0.0 -> 2.1.0 only has kg_reextract
        assert (
            determine_migration_strategy("2.0.0", "2.1.0", changelog)
            == "kg_reextract"
        )

    def test_strategy_enum_values(self) -> None:
        assert MigrationStrategy.NONE.value == "none"
        assert MigrationStrategy.METADATA_ONLY.value == "metadata_only"
        assert MigrationStrategy.KG_REEXTRACT.value == "kg_reextract"
        assert MigrationStrategy.FULL_PHASE2.value == "full_phase2"
