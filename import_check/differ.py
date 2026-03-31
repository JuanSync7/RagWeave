# @summary
# Inventory differ — compares old and new SymbolInventory objects to detect
# symbol migrations (moves, renames, splits, merges) between refactor states.
# Exports: diff_inventories
# Deps: import_check.schemas (MigrationEntry, SymbolInfo, SymbolInventory)
# @end-summary
"""Inventory differ — detects symbol migrations between old and new states.

Compares two SymbolInventory objects and produces a list of MigrationEntry
records describing how symbols moved, were renamed, split, or merged.

Detection runs in three ordered phases:
1. Moves — same symbol name, different module path.
2. Renames — symbol disappeared from a module, new symbol appeared in the
   same file with matching type and nearby line number.
3. Splits and merges — symbols from one old file scattered across multiple
   new files (split), or symbols from multiple old files collected into one
   new file (merge).

Each phase feeds an ``already_matched`` set into subsequent phases so that
a single symbol is never double-counted.
"""

from __future__ import annotations

import logging
from collections import defaultdict

from .schemas import MigrationEntry, SymbolInfo, SymbolInventory

logger = logging.getLogger("import_check")

# Maximum line-number distance to consider two symbols as rename candidates.
_RENAME_LINE_PROXIMITY = 30


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def diff_inventories(old: SymbolInventory, new: SymbolInventory) -> list[MigrationEntry]:
    """Diff two symbol inventories to detect migrations.

    Detection strategy:
    1. MOVE: Symbol with same name exists in old and new but different module_path.
    2. RENAME: Symbol disappeared from old module; a new symbol appeared in
       the same module with no other explanation. Uses heuristic: same file,
       same symbol_type, close line number.
    3. SPLIT: Symbol from one old module now appears in multiple new modules.
    4. MERGE: Symbols from multiple old modules now appear in one new module.

    Symbols present in both inventories at the same location are ignored
    (no migration needed). Symbols only in old (deleted) or only in new
    (added) are not migrations — they are not included in the output.

    Args:
        old: Symbol inventory from the previous git state.
        new: Symbol inventory from the current filesystem state.

    Returns:
        List of MigrationEntry records. Empty if no migrations detected.
    """
    already_matched: set[tuple[str, str]] = set()

    # Phase 1: detect moves (same name, different module).
    moves = _detect_moves(old, new)
    for entry in moves:
        already_matched.add((entry.old_name, entry.old_module))
        already_matched.add((entry.new_name, entry.new_module))

    # Phase 2: detect renames (disappeared + appeared in same file/type).
    renames = _detect_renames(old, new, already_matched)
    for entry in renames:
        already_matched.add((entry.old_name, entry.old_module))
        already_matched.add((entry.new_name, entry.new_module))

    # Phase 3: detect splits and merges.
    splits_merges = _detect_splits_and_merges(old, new, already_matched)

    result = moves + renames + splits_merges
    logger.debug(
        "diff_inventories: %d moves, %d renames, %d splits/merges",
        len(moves),
        len(renames),
        len(splits_merges),
    )
    return result


# ---------------------------------------------------------------------------
# Phase 1: move detection
# ---------------------------------------------------------------------------


def _detect_moves(old: SymbolInventory, new: SymbolInventory) -> list[MigrationEntry]:
    """Detect symbols that moved between modules (same name, different path).

    For each symbol name that exists in both inventories, compare the set of
    module_paths. If the symbol appeared at module A in old and module B in new
    (and is no longer at A), that is a move.

    When a symbol name exists in multiple modules in old or new, we only emit
    a move when there is a single unambiguous old location that disappeared and
    a single unambiguous new location that appeared. Ambiguous cases are skipped.

    Args:
        old: Old inventory.
        new: New inventory.

    Returns:
        List of move MigrationEntry records.
    """
    entries: list[MigrationEntry] = []
    common_names = set(old) & set(new)

    for name in common_names:
        old_modules = {si.module_path for si in old[name]}
        new_modules = {si.module_path for si in new[name]}

        # Modules that the symbol left and modules it arrived at.
        departed = old_modules - new_modules
        arrived = new_modules - old_modules

        if not departed or not arrived:
            # Symbol still exists at all old locations, or no new locations — no move.
            continue

        # Simple 1-to-1 move: exactly one departed, exactly one arrived.
        if len(departed) == 1 and len(arrived) == 1:
            old_mod = next(iter(departed))
            new_mod = next(iter(arrived))
            entries.append(
                MigrationEntry(
                    old_module=old_mod,
                    old_name=name,
                    new_module=new_mod,
                    new_name=name,
                    migration_type="move",
                )
            )
            logger.debug("move detected: %s  %s -> %s", name, old_mod, new_mod)
            continue

        # N-departed, N-arrived with same count — attempt positional matching
        # by file_path similarity. Only emit if we can match every departed to
        # exactly one arrived (conservative).
        if len(departed) == len(arrived):
            matched = _match_modules_by_file(name, departed, arrived, old, new)
            if matched is not None:
                entries.extend(matched)
                continue

        # Ambiguous — skip to avoid false positives.
        logger.debug(
            "move skipped (ambiguous): %s departed=%s arrived=%s",
            name,
            departed,
            arrived,
        )

    return entries


def _match_modules_by_file(
    name: str,
    departed: set[str],
    arrived: set[str],
    old: SymbolInventory,
    new: SymbolInventory,
) -> list[MigrationEntry] | None:
    """Try to match departed modules to arrived modules by file_path basename.

    Returns a list of MigrationEntry if a 1-to-1 mapping is found, else None.
    """
    # Build maps: module_path -> file_path for this symbol name.
    old_lookup: dict[str, str] = {}
    for si in old[name]:
        if si.module_path in departed:
            old_lookup[si.module_path] = si.file_path

    new_lookup: dict[str, str] = {}
    for si in new[name]:
        if si.module_path in arrived:
            new_lookup[si.module_path] = si.file_path

    # Try basename matching.
    old_by_base: dict[str, list[str]] = defaultdict(list)
    for mod, fp in old_lookup.items():
        base = fp.rsplit("/", 1)[-1] if "/" in fp else fp
        old_by_base[base].append(mod)

    new_by_base: dict[str, list[str]] = defaultdict(list)
    for mod, fp in new_lookup.items():
        base = fp.rsplit("/", 1)[-1] if "/" in fp else fp
        new_by_base[base].append(mod)

    entries: list[MigrationEntry] = []
    used_new: set[str] = set()

    for base, old_mods in old_by_base.items():
        new_mods = new_by_base.get(base, [])
        if len(old_mods) != 1 or len(new_mods) != 1:
            return None  # ambiguous
        new_mod = new_mods[0]
        if new_mod in used_new:
            return None
        used_new.add(new_mod)
        entries.append(
            MigrationEntry(
                old_module=old_mods[0],
                old_name=name,
                new_module=new_mod,
                new_name=name,
                migration_type="move",
            )
        )

    if len(entries) != len(departed):
        return None  # not all matched

    return entries


# ---------------------------------------------------------------------------
# Phase 2: rename detection
# ---------------------------------------------------------------------------


def _detect_renames(
    old: SymbolInventory, new: SymbolInventory, already_matched: set[tuple[str, str]]
) -> list[MigrationEntry]:
    """Detect symbols that were renamed within the same module.

    Uses heuristics: same file, same symbol_type, close line number,
    and the old symbol no longer exists while a new one appeared.

    Strategy:
    - Build per-module lists of disappeared old symbols and appeared new symbols.
    - For each disappeared symbol, find the best candidate among new symbols
      in the same module/file with same type and closest line number within
      the proximity threshold.
    - Each new symbol can only be matched once (greedy, closest-first).

    Args:
        old: Old inventory.
        new: New inventory.
        already_matched: Set of (name, module_path) tuples already explained
            by move detection — skip these.

    Returns:
        List of rename MigrationEntry records.
    """
    # Collect per-module disappeared and appeared symbols.
    old_by_module: dict[str, list[SymbolInfo]] = defaultdict(list)
    new_by_module: dict[str, list[SymbolInfo]] = defaultdict(list)

    # Symbols that exist only in old (disappeared).
    for name, infos in old.items():
        for si in infos:
            if (si.name, si.module_path) in already_matched:
                continue
            # Check if this exact symbol still exists in new at the same location.
            if _symbol_exists_at(new, si.name, si.module_path):
                continue
            old_by_module[si.module_path].append(si)

    # Symbols that exist only in new (appeared).
    for name, infos in new.items():
        for si in infos:
            if (si.name, si.module_path) in already_matched:
                continue
            # Check if this symbol existed in old at the same location.
            if _symbol_exists_at(old, si.name, si.module_path):
                continue
            new_by_module[si.module_path].append(si)

    entries: list[MigrationEntry] = []
    used_new: set[tuple[str, str]] = set()  # (name, module_path) of matched new symbols

    # For each module with disappeared symbols, try to match with appeared ones.
    for module_path, disappeared in old_by_module.items():
        appeared = new_by_module.get(module_path, [])
        if not appeared:
            continue

        # Sort disappeared by line number for deterministic processing.
        disappeared_sorted = sorted(disappeared, key=lambda s: s.lineno)

        for old_sym in disappeared_sorted:
            best_candidate: SymbolInfo | None = None
            best_distance = _RENAME_LINE_PROXIMITY + 1

            for new_sym in appeared:
                if (new_sym.name, new_sym.module_path) in used_new:
                    continue
                # Must be same file and same symbol type.
                if new_sym.file_path != old_sym.file_path:
                    continue
                if new_sym.symbol_type != old_sym.symbol_type:
                    continue
                distance = abs(new_sym.lineno - old_sym.lineno)
                if distance < best_distance:
                    best_distance = distance
                    best_candidate = new_sym

            if best_candidate is not None:
                entries.append(
                    MigrationEntry(
                        old_module=module_path,
                        old_name=old_sym.name,
                        new_module=module_path,
                        new_name=best_candidate.name,
                        migration_type="rename",
                    )
                )
                used_new.add((best_candidate.name, best_candidate.module_path))
                logger.debug(
                    "rename detected: %s -> %s in %s",
                    old_sym.name,
                    best_candidate.name,
                    module_path,
                )

    return entries


# ---------------------------------------------------------------------------
# Phase 3: split and merge detection
# ---------------------------------------------------------------------------


def _detect_splits_and_merges(
    old: SymbolInventory, new: SymbolInventory, already_matched: set[tuple[str, str]]
) -> list[MigrationEntry]:
    """Detect one-to-many (split) and many-to-one (merge) migrations.

    A split is when symbols from one old file now appear across multiple
    new files. A merge is the reverse — symbols from multiple old files
    now appear in one new file.

    Strategy:
    - For each symbol name in both old and new (not already matched), record
      old_file -> new_file mappings.
    - Group by old file: if one old file maps to multiple new files, those are
      splits.
    - Group by new file: if one new file receives symbols from multiple old
      files, those are merges.

    Args:
        old: Old inventory.
        new: New inventory.
        already_matched: Already-explained migrations to skip.

    Returns:
        List of split/merge MigrationEntry records.
    """
    # Build mapping of (symbol_name) -> (old_info, new_info) for symbols that
    # moved file but kept their name, and are not yet explained.
    file_migrations: list[tuple[SymbolInfo, SymbolInfo]] = []

    common_names = set(old) & set(new)
    for name in common_names:
        old_infos = old[name]
        new_infos = new[name]

        for old_si in old_infos:
            if (old_si.name, old_si.module_path) in already_matched:
                continue
            # Check if this symbol moved to a different file.
            for new_si in new_infos:
                if (new_si.name, new_si.module_path) in already_matched:
                    continue
                if old_si.file_path != new_si.file_path and old_si.name == new_si.name:
                    file_migrations.append((old_si, new_si))

    # Group by old file to detect splits (one old file -> many new files).
    old_file_to_new_files: dict[str, dict[str, list[tuple[SymbolInfo, SymbolInfo]]]] = (
        defaultdict(lambda: defaultdict(list))
    )
    for old_si, new_si in file_migrations:
        old_file_to_new_files[old_si.file_path][new_si.file_path].append(
            (old_si, new_si)
        )

    # Group by new file to detect merges (many old files -> one new file).
    new_file_to_old_files: dict[str, dict[str, list[tuple[SymbolInfo, SymbolInfo]]]] = (
        defaultdict(lambda: defaultdict(list))
    )
    for old_si, new_si in file_migrations:
        new_file_to_old_files[new_si.file_path][old_si.file_path].append(
            (old_si, new_si)
        )

    entries: list[MigrationEntry] = []
    emitted: set[tuple[str, str, str, str]] = set()  # dedup key

    # Splits: one old file dispersed across 2+ new files.
    for old_file, new_files_map in old_file_to_new_files.items():
        if len(new_files_map) < 2:
            continue
        for _new_file, pairs in new_files_map.items():
            for old_si, new_si in pairs:
                dedup_key = (old_si.module_path, old_si.name, new_si.module_path, new_si.name)
                if dedup_key in emitted:
                    continue
                emitted.add(dedup_key)
                entries.append(
                    MigrationEntry(
                        old_module=old_si.module_path,
                        old_name=old_si.name,
                        new_module=new_si.module_path,
                        new_name=new_si.name,
                        migration_type="split",
                    )
                )
                logger.debug(
                    "split detected: %s from %s -> %s",
                    old_si.name,
                    old_si.module_path,
                    new_si.module_path,
                )

    # Merges: 2+ old files consolidated into one new file.
    for new_file, old_files_map in new_file_to_old_files.items():
        if len(old_files_map) < 2:
            continue
        for _old_file, pairs in old_files_map.items():
            for old_si, new_si in pairs:
                dedup_key = (old_si.module_path, old_si.name, new_si.module_path, new_si.name)
                if dedup_key in emitted:
                    continue
                emitted.add(dedup_key)
                entries.append(
                    MigrationEntry(
                        old_module=old_si.module_path,
                        old_name=old_si.name,
                        new_module=new_si.module_path,
                        new_name=new_si.name,
                        migration_type="merge",
                    )
                )
                logger.debug(
                    "merge detected: %s from %s -> %s",
                    old_si.name,
                    old_si.module_path,
                    new_si.module_path,
                )

    return entries


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _symbol_exists_at(
    inventory: SymbolInventory, name: str, module_path: str
) -> bool:
    """Check whether a symbol with the given name exists at the given module."""
    infos = inventory.get(name)
    if infos is None:
        return False
    return any(si.module_path == module_path for si in infos)
