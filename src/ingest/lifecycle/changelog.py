# @summary
# Schema changelog parser: loads config/schema_changelog.yaml into SchemaVersion
# typed records. Resolves the minimum-cost migration strategy for a version range
# via get_required_migrations() and determine_migration_strategy().
# Exports: SchemaVersion, MigrationStrategy, load_changelog,
#          get_required_migrations, determine_migration_strategy
# Deps: yaml, dataclasses, enum, pathlib, logging
# @end-summary
"""Schema changelog parser and migration strategy resolver (FR-3113).

The changelog is a YAML file (``config/schema_changelog.yaml``) that maps
schema version entries to migration strategies. This module loads that file
into typed :class:`SchemaVersion` records and provides two resolution helpers:

* :func:`get_required_migrations` -- returns every changelog entry in the
  half-open range (from_version, to_version].
* :func:`determine_migration_strategy` -- returns the single most-expensive
  strategy required to bridge two versions.

Strategy cost order (ascending):
  ``none`` < ``metadata_only`` < ``kg_reextract`` < ``full_phase2``
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List

import yaml

logger = logging.getLogger(__name__)

# Default changelog path relative to the project root.
_DEFAULT_CHANGELOG: Path = Path("config/schema_changelog.yaml")

# Cost rank for each strategy.  Higher rank = more expensive.
_STRATEGY_RANK: dict[str, int] = {
    "none": 0,
    "metadata_only": 1,
    "kg_reextract": 2,
    "full_phase2": 3,
}


class MigrationStrategy(str, Enum):
    """Enumeration of supported migration strategies (FR-3113).

    Values are intentionally string-compatible so they can be serialised
    directly to JSON / YAML without conversion.
    """

    NONE = "none"
    METADATA_ONLY = "metadata_only"
    KG_REEXTRACT = "kg_reextract"
    FULL_PHASE2 = "full_phase2"


@dataclass(frozen=True)
class SchemaVersion:
    """A single entry in the schema changelog.

    Attributes:
        version: Semantic version string (e.g. ``"1.0.0"``).
        date: ISO date string for when this version was introduced.
        description: Human-readable description of the schema changes.
        migration_strategy: The strategy required to migrate *to* this version
            from the immediately preceding version.
        fields_added: Field names added in this version.
        fields_removed: Field names removed in this version.
        fields_renamed: ``{"old_name": "new_name"}`` mapping for renamed fields.
    """

    version: str
    date: str
    description: str
    migration_strategy: str
    fields_added: list[str] = field(default_factory=list, compare=False, hash=False)
    fields_removed: list[str] = field(default_factory=list, compare=False, hash=False)
    fields_renamed: dict[str, str] = field(
        default_factory=dict, compare=False, hash=False
    )


def load_changelog(path: str | Path = _DEFAULT_CHANGELOG) -> list[SchemaVersion]:
    """Load and validate the schema changelog from *path*.

    Args:
        path: Path to the YAML changelog file. Defaults to
            ``config/schema_changelog.yaml`` relative to the cwd.

    Returns:
        List of :class:`SchemaVersion` entries in the order they appear in
        the file (oldest first).

    Raises:
        FileNotFoundError: If the changelog file does not exist.
        ValueError: If the file is malformed or an entry is missing a
            required field, or contains an unknown strategy.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Schema changelog not found: {path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or "schema_versions" not in raw:
        raise ValueError(
            f"Changelog {path} must contain a top-level 'schema_versions' key."
        )

    entries: list[SchemaVersion] = []
    seen_versions: set[str] = set()

    for item in raw["schema_versions"]:
        _require_fields(item, ("version", "date", "description", "migration_strategy"))

        version = str(item["version"])
        strategy = str(item["migration_strategy"])

        if strategy not in _STRATEGY_RANK:
            raise ValueError(
                f"Unknown migration_strategy '{strategy}' in version '{version}'. "
                f"Valid values: {sorted(_STRATEGY_RANK.keys())}"
            )
        if version in seen_versions:
            raise ValueError(
                f"Duplicate version '{version}' in changelog {path}."
            )
        seen_versions.add(version)

        entries.append(
            SchemaVersion(
                version=version,
                date=str(item.get("date", "")),
                description=str(item.get("description", "")).strip(),
                migration_strategy=strategy,
                fields_added=list(item.get("fields_added") or []),
                fields_removed=list(item.get("fields_removed") or []),
                fields_renamed=dict(item.get("fields_renamed") or {}),
            )
        )

    logger.debug("load_changelog loaded=%d entries from=%s", len(entries), path)
    return entries


def get_required_migrations(
    from_version: str,
    to_version: str,
    changelog: list[SchemaVersion],
) -> list[SchemaVersion]:
    """Return all changelog entries in the half-open range (from_version, to_version].

    The *from_version* entry itself is excluded; *to_version* is included.
    If *from_version* equals *to_version* the return value is an empty list
    (idempotency).

    Args:
        from_version: Current version of the document (e.g. ``"0.0.0"``).
        to_version: Target version (e.g. ``"1.0.0"``).
        changelog: Loaded changelog entries (from :func:`load_changelog`).

    Returns:
        Ordered list of :class:`SchemaVersion` entries that must be applied.
        Empty list if already at target version or no intermediate entries exist.

    Raises:
        ValueError: If *from_version* or *to_version* are not present in the
            changelog.
    """
    if from_version == to_version:
        return []

    all_versions = [sv.version for sv in changelog]

    if from_version not in all_versions:
        raise ValueError(
            f"from_version '{from_version}' not found in changelog. "
            f"Available: {all_versions}"
        )
    if to_version not in all_versions:
        raise ValueError(
            f"to_version '{to_version}' not found in changelog. "
            f"Available: {all_versions}"
        )

    from_idx = all_versions.index(from_version)
    to_idx = all_versions.index(to_version)

    if to_idx < from_idx:
        # Downgrade is not supported; return empty list so callers skip migration.
        logger.warning(
            "get_required_migrations: to_version '%s' is older than "
            "from_version '%s'; returning empty list (no downgrade support).",
            to_version,
            from_version,
        )
        return []

    return changelog[from_idx + 1 : to_idx + 1]


def determine_migration_strategy(
    from_version: str,
    to_version: str,
    changelog: list[SchemaVersion],
) -> str:
    """Return the single most-expensive migration strategy for a version gap.

    Examines all changelog entries between *from_version* (exclusive) and
    *to_version* (inclusive). Returns the strategy with the highest cost rank
    among the intervening versions.

    Args:
        from_version: Document's current schema version (e.g. ``"0.0.0"``).
        to_version: Target schema version (e.g. ``"1.0.0"``).
        changelog: Loaded changelog entries.

    Returns:
        Migration strategy string (``"none"``, ``"metadata_only"``,
        ``"kg_reextract"``, or ``"full_phase2"``). Returns ``"none"`` when no
        intermediate versions require migration (i.e. already at target).

    Raises:
        ValueError: Forwarded from :func:`get_required_migrations` if versions
            are not in the changelog.
    """
    if from_version == to_version:
        return "none"

    required = get_required_migrations(from_version, to_version, changelog)
    if not required:
        return "none"

    max_rank = 0
    for sv in required:
        rank = _STRATEGY_RANK.get(sv.migration_strategy, 0)
        if rank > max_rank:
            max_rank = rank

    # Reverse-lookup from rank to strategy string.
    for strategy, rank in _STRATEGY_RANK.items():
        if rank == max_rank:
            return strategy

    return "none"


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _require_fields(item: dict, required: tuple[str, ...]) -> None:
    """Raise ValueError if any *required* key is absent from *item*."""
    for key in required:
        if key not in item:
            raise ValueError(
                f"Changelog entry missing required field '{key}': {item!r}"
            )
