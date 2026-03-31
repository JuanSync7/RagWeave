"""Tests for import_check/differ.py -- Inventory Differ.

Tests cover:
- diff_inventories: returns empty list when no changes
- _detect_moves: same name different module = move
- _detect_renames: symbol disappeared + new symbol appeared in same module = rename
- _detect_splits_and_merges: one file symbols scattered to multiple = split, multiple to one = merge
- Edge cases: symbol in multiple modules, no false positives for pure additions/deletions
"""

from __future__ import annotations

from import_check.differ import (
    _detect_moves,
    _detect_renames,
    _detect_splits_and_merges,
    diff_inventories,
)
from import_check.schemas import SymbolInfo, SymbolInventory


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _si(
    name: str = "foo",
    module_path: str = "src.mod",
    file_path: str = "src/mod.py",
    lineno: int = 1,
    symbol_type: str = "function",
) -> SymbolInfo:
    """Factory for creating SymbolInfo with sensible defaults."""
    return SymbolInfo(
        name=name,
        module_path=module_path,
        file_path=file_path,
        lineno=lineno,
        symbol_type=symbol_type,
    )


def _inv(*symbols: SymbolInfo) -> SymbolInventory:
    """Build a SymbolInventory from a flat list of SymbolInfo."""
    inventory: SymbolInventory = {}
    for si in symbols:
        inventory.setdefault(si.name, []).append(si)
    return inventory


# ===================================================================
# diff_inventories -- orchestrator
# ===================================================================


class TestDiffInventories:
    """Tests for the top-level diff_inventories orchestrator."""

    def test_no_changes_returns_empty(self) -> None:
        """Identical inventories produce no migrations."""
        old = _inv(
            _si(name="foo", module_path="src.a", file_path="src/a.py"),
            _si(name="bar", module_path="src.b", file_path="src/b.py"),
        )
        new = _inv(
            _si(name="foo", module_path="src.a", file_path="src/a.py"),
            _si(name="bar", module_path="src.b", file_path="src/b.py"),
        )
        result = diff_inventories(old, new)
        assert result == []

    def test_both_empty_inventories(self) -> None:
        result = diff_inventories({}, {})
        assert result == []

    def test_old_empty_new_nonempty(self) -> None:
        """All symbols are pure additions -- not migrations."""
        new = _inv(_si(name="bar", module_path="src.new"))
        result = diff_inventories({}, new)
        assert result == []

    def test_old_nonempty_new_empty(self) -> None:
        """All symbols are pure deletions -- not migrations."""
        old = _inv(_si(name="bar", module_path="src.old"))
        result = diff_inventories(old, {})
        assert result == []

    def test_pure_addition_not_migration(self) -> None:
        """Symbol only in new is an addition, not a migration."""
        old = _inv(_si(name="existing", module_path="src.a"))
        new = _inv(
            _si(name="existing", module_path="src.a"),
            _si(name="brand_new", module_path="src.b"),
        )
        result = diff_inventories(old, new)
        assert result == []

    def test_pure_deletion_not_migration(self) -> None:
        """Symbol only in old is a deletion, not a migration."""
        old = _inv(
            _si(name="existing", module_path="src.a"),
            _si(name="removed", module_path="src.b"),
        )
        new = _inv(_si(name="existing", module_path="src.a"))
        result = diff_inventories(old, new)
        assert result == []

    def test_simple_move_detected(self) -> None:
        old = _inv(_si(name="foo", module_path="src.old", file_path="src/old.py"))
        new = _inv(_si(name="foo", module_path="src.new", file_path="src/new.py"))

        result = diff_inventories(old, new)
        assert len(result) == 1
        entry = result[0]
        assert entry.migration_type == "move"
        assert entry.old_module == "src.old"
        assert entry.new_module == "src.new"
        assert entry.old_name == "foo"
        assert entry.new_name == "foo"

    def test_move_and_rename_in_same_diff(self) -> None:
        """Move and rename are detected independently without interference."""
        old = _inv(
            # This will move
            _si(name="mover", module_path="src.a", file_path="src/a.py"),
            # This will be renamed
            _si(name="old_name", module_path="src.c", file_path="src/c.py",
                lineno=5, symbol_type="function"),
        )
        new = _inv(
            # Moved
            _si(name="mover", module_path="src.b", file_path="src/b.py"),
            # Renamed
            _si(name="new_name", module_path="src.c", file_path="src/c.py",
                lineno=5, symbol_type="function"),
        )

        result = diff_inventories(old, new)
        types = {e.migration_type for e in result}
        assert "move" in types
        assert "rename" in types
        assert len(result) == 2


# ===================================================================
# _detect_moves
# ===================================================================


class TestDetectMoves:
    """Tests for move detection (same name, different module)."""

    def test_simple_move(self) -> None:
        old = _inv(_si(name="foo", module_path="src.old"))
        new = _inv(_si(name="foo", module_path="src.new"))

        entries = _detect_moves(old, new)
        assert len(entries) == 1
        assert entries[0].migration_type == "move"
        assert entries[0].old_module == "src.old"
        assert entries[0].new_module == "src.new"
        assert entries[0].old_name == "foo"
        assert entries[0].new_name == "foo"

    def test_no_move_when_same_location(self) -> None:
        old = _inv(_si(name="foo", module_path="src.a"))
        new = _inv(_si(name="foo", module_path="src.a"))

        entries = _detect_moves(old, new)
        assert entries == []

    def test_no_common_names(self) -> None:
        old = _inv(_si(name="alpha", module_path="src.a"))
        new = _inv(_si(name="beta", module_path="src.b"))

        entries = _detect_moves(old, new)
        assert entries == []

    def test_ambiguous_multiple_departures_skipped(self) -> None:
        """Symbol in multiple old modules with single arrival -- ambiguous, skipped."""
        old = _inv(
            _si(name="foo", module_path="src.a", file_path="src/a.py"),
            _si(name="foo", module_path="src.b", file_path="src/b.py"),
        )
        new = _inv(
            _si(name="foo", module_path="src.c", file_path="src/c.py"),
        )

        entries = _detect_moves(old, new)
        assert entries == []

    def test_ambiguous_multiple_arrivals_skipped(self) -> None:
        """Single departure but multiple arrivals -- ambiguous, skipped."""
        old = _inv(
            _si(name="foo", module_path="src.a", file_path="src/a.py"),
        )
        new = _inv(
            _si(name="foo", module_path="src.b", file_path="src/b.py"),
            _si(name="foo", module_path="src.c", file_path="src/c.py"),
        )

        entries = _detect_moves(old, new)
        assert entries == []

    def test_symbol_still_at_old_location_no_move(self) -> None:
        """Symbol added to a new location but still exists at old -- no departed."""
        old = _inv(_si(name="foo", module_path="src.a"))
        new = _inv(
            _si(name="foo", module_path="src.a"),
            _si(name="foo", module_path="src.b"),
        )

        entries = _detect_moves(old, new)
        assert entries == []

    def test_multiple_independent_moves(self) -> None:
        old = _inv(
            _si(name="alpha", module_path="src.old_a", file_path="src/old_a.py"),
            _si(name="beta", module_path="src.old_b", file_path="src/old_b.py"),
        )
        new = _inv(
            _si(name="alpha", module_path="src.new_a", file_path="src/new_a.py"),
            _si(name="beta", module_path="src.new_b", file_path="src/new_b.py"),
        )

        entries = _detect_moves(old, new)
        assert len(entries) == 2
        moved_names = {e.old_name for e in entries}
        assert moved_names == {"alpha", "beta"}


# ===================================================================
# _detect_renames
# ===================================================================


class TestDetectRenames:
    """Tests for rename detection within the same module."""

    def test_simple_rename(self) -> None:
        old = _inv(
            _si(name="old_name", module_path="src.mod", file_path="src/mod.py",
                lineno=10, symbol_type="function"),
        )
        new = _inv(
            _si(name="new_name", module_path="src.mod", file_path="src/mod.py",
                lineno=10, symbol_type="function"),
        )

        entries = _detect_renames(old, new, already_matched=set())
        assert len(entries) == 1
        assert entries[0].migration_type == "rename"
        assert entries[0].old_name == "old_name"
        assert entries[0].new_name == "new_name"
        assert entries[0].old_module == "src.mod"
        assert entries[0].new_module == "src.mod"

    def test_no_rename_when_same_name_still_exists(self) -> None:
        """If the old symbol still exists in new, it is not a disappearance."""
        old = _inv(
            _si(name="stable", module_path="src.mod", file_path="src/mod.py",
                lineno=10, symbol_type="function"),
        )
        new = _inv(
            _si(name="stable", module_path="src.mod", file_path="src/mod.py",
                lineno=10, symbol_type="function"),
        )

        entries = _detect_renames(old, new, already_matched=set())
        assert entries == []

    def test_rename_requires_same_symbol_type(self) -> None:
        """Function disappeared, class appeared at same line -- not a rename."""
        old = _inv(
            _si(name="gone", module_path="src.mod", file_path="src/mod.py",
                lineno=10, symbol_type="function"),
        )
        new = _inv(
            _si(name="arrived", module_path="src.mod", file_path="src/mod.py",
                lineno=10, symbol_type="class"),
        )

        entries = _detect_renames(old, new, already_matched=set())
        assert entries == []

    def test_rename_requires_same_file(self) -> None:
        """Symbols in different files are not rename candidates."""
        old = _inv(
            _si(name="gone", module_path="src.mod", file_path="src/mod.py",
                lineno=10, symbol_type="function"),
        )
        new = _inv(
            _si(name="arrived", module_path="src.mod", file_path="src/other.py",
                lineno=10, symbol_type="function"),
        )

        entries = _detect_renames(old, new, already_matched=set())
        assert entries == []

    def test_rename_outside_proximity_threshold(self) -> None:
        """Line numbers differ by more than 30 -- not matched as rename."""
        old = _inv(
            _si(name="gone", module_path="src.mod", file_path="src/mod.py",
                lineno=10, symbol_type="function"),
        )
        new = _inv(
            _si(name="arrived", module_path="src.mod", file_path="src/mod.py",
                lineno=50, symbol_type="function"),
        )

        entries = _detect_renames(old, new, already_matched=set())
        assert entries == []

    def test_rename_within_proximity_threshold(self) -> None:
        """Line numbers differ by exactly 30 -- still matched (< threshold+1)."""
        old = _inv(
            _si(name="gone", module_path="src.mod", file_path="src/mod.py",
                lineno=10, symbol_type="function"),
        )
        new = _inv(
            _si(name="arrived", module_path="src.mod", file_path="src/mod.py",
                lineno=40, symbol_type="function"),
        )

        entries = _detect_renames(old, new, already_matched=set())
        assert len(entries) == 1
        assert entries[0].old_name == "gone"
        assert entries[0].new_name == "arrived"

    def test_already_matched_symbols_skipped(self) -> None:
        """Symbols already matched by move detection are not reconsidered."""
        old = _inv(
            _si(name="moved_fn", module_path="src.old", file_path="src/old.py",
                lineno=10, symbol_type="function"),
        )
        new = _inv(
            _si(name="new_fn", module_path="src.old", file_path="src/old.py",
                lineno=10, symbol_type="function"),
        )

        already = {("moved_fn", "src.old")}
        entries = _detect_renames(old, new, already_matched=already)
        assert entries == []

    def test_best_candidate_closest_line(self) -> None:
        """When multiple new symbols match, pick the one closest in line number."""
        old = _inv(
            _si(name="gone", module_path="src.mod", file_path="src/mod.py",
                lineno=10, symbol_type="function"),
        )
        new = _inv(
            _si(name="far_candidate", module_path="src.mod", file_path="src/mod.py",
                lineno=35, symbol_type="function"),
            _si(name="close_candidate", module_path="src.mod", file_path="src/mod.py",
                lineno=12, symbol_type="function"),
        )

        entries = _detect_renames(old, new, already_matched=set())
        assert len(entries) == 1
        assert entries[0].new_name == "close_candidate"


# ===================================================================
# _detect_splits_and_merges
# ===================================================================


class TestDetectSplitsAndMerges:
    """Tests for split and merge detection."""

    def test_simple_split(self) -> None:
        """Symbols from one old file scattered to two new files = split."""
        old = _inv(
            _si(name="func_a", module_path="src.big", file_path="src/big.py", lineno=1),
            _si(name="func_b", module_path="src.big", file_path="src/big.py", lineno=10),
        )
        new = _inv(
            _si(name="func_a", module_path="src.part_a", file_path="src/part_a.py", lineno=1),
            _si(name="func_b", module_path="src.part_b", file_path="src/part_b.py", lineno=1),
        )

        entries = _detect_splits_and_merges(old, new, already_matched=set())
        assert len(entries) == 2
        assert all(e.migration_type == "split" for e in entries)
        names = {e.old_name for e in entries}
        assert names == {"func_a", "func_b"}

    def test_simple_merge(self) -> None:
        """Symbols from two old files consolidated into one new file = merge."""
        old = _inv(
            _si(name="func_a", module_path="src.a", file_path="src/a.py", lineno=1),
            _si(name="func_b", module_path="src.b", file_path="src/b.py", lineno=1),
        )
        new = _inv(
            _si(name="func_a", module_path="src.combined", file_path="src/combined.py", lineno=1),
            _si(name="func_b", module_path="src.combined", file_path="src/combined.py", lineno=10),
        )

        entries = _detect_splits_and_merges(old, new, already_matched=set())
        assert len(entries) == 2
        assert all(e.migration_type == "merge" for e in entries)
        assert all(e.new_module == "src.combined" for e in entries)

    def test_no_split_or_merge_when_same_file(self) -> None:
        """Symbol stays in same file -- no split or merge."""
        old = _inv(
            _si(name="foo", module_path="src.mod", file_path="src/mod.py"),
        )
        new = _inv(
            _si(name="foo", module_path="src.mod", file_path="src/mod.py"),
        )

        entries = _detect_splits_and_merges(old, new, already_matched=set())
        assert entries == []

    def test_single_file_to_single_file_not_split(self) -> None:
        """One symbol from one old file to one new file is a move, not a split.
        Only triggers as split when one old file maps to 2+ new files."""
        old = _inv(
            _si(name="foo", module_path="src.old", file_path="src/old.py"),
        )
        new = _inv(
            _si(name="foo", module_path="src.new", file_path="src/new.py"),
        )

        entries = _detect_splits_and_merges(old, new, already_matched=set())
        assert entries == []

    def test_already_matched_skipped(self) -> None:
        """Symbols already matched by earlier phases are not reconsidered."""
        old = _inv(
            _si(name="func_a", module_path="src.big", file_path="src/big.py"),
            _si(name="func_b", module_path="src.big", file_path="src/big.py"),
        )
        new = _inv(
            _si(name="func_a", module_path="src.part_a", file_path="src/part_a.py"),
            _si(name="func_b", module_path="src.part_b", file_path="src/part_b.py"),
        )

        already = {("func_a", "src.big"), ("func_a", "src.part_a")}
        entries = _detect_splits_and_merges(old, new, already_matched=already)
        # func_a is already matched, so only func_b could be considered.
        # But with only one old->new pair for func_b (one old file to one new file),
        # it is not enough to constitute a split (need 2+ new files from same old file).
        # func_a is excluded, so old file src/big.py only maps to src/part_b.py (1 new file).
        assert entries == []

    def test_deduplication(self) -> None:
        """A migration should not appear as both split and merge."""
        # This scenario: two symbols from src/big.py go to src/a.py and src/b.py (split),
        # and src/a.py also receives from src/other.py (merge).
        old = _inv(
            _si(name="func_a", module_path="src.big", file_path="src/big.py", lineno=1),
            _si(name="func_b", module_path="src.big", file_path="src/big.py", lineno=10),
            _si(name="func_c", module_path="src.other", file_path="src/other.py", lineno=1),
        )
        new = _inv(
            _si(name="func_a", module_path="src.a", file_path="src/a.py", lineno=1),
            _si(name="func_b", module_path="src.b", file_path="src/b.py", lineno=1),
            _si(name="func_c", module_path="src.a", file_path="src/a.py", lineno=10),
        )

        entries = _detect_splits_and_merges(old, new, already_matched=set())
        # Check there are no duplicate (old_mod, old_name, new_mod, new_name) tuples
        dedup_keys = [
            (e.old_module, e.old_name, e.new_module, e.new_name)
            for e in entries
        ]
        assert len(dedup_keys) == len(set(dedup_keys))

    def test_symbol_only_in_old_not_split(self) -> None:
        """Symbol deleted entirely is not a split/merge."""
        old = _inv(
            _si(name="gone", module_path="src.old", file_path="src/old.py"),
        )
        new: SymbolInventory = {}

        entries = _detect_splits_and_merges(old, new, already_matched=set())
        assert entries == []

    def test_symbol_only_in_new_not_merge(self) -> None:
        """Brand new symbol is not a split/merge."""
        old: SymbolInventory = {}
        new = _inv(
            _si(name="brand_new", module_path="src.new", file_path="src/new.py"),
        )

        entries = _detect_splits_and_merges(old, new, already_matched=set())
        assert entries == []


# ===================================================================
# Edge cases spanning multiple detection phases
# ===================================================================


class TestEdgeCases:
    """Edge cases for the overall diff pipeline."""

    def test_symbol_in_multiple_modules_no_false_positive(self) -> None:
        """Symbol exists in two modules in both old and new (same locations) -- no migration."""
        old = _inv(
            _si(name="helper", module_path="src.a", file_path="src/a.py"),
            _si(name="helper", module_path="src.b", file_path="src/b.py"),
        )
        new = _inv(
            _si(name="helper", module_path="src.a", file_path="src/a.py"),
            _si(name="helper", module_path="src.b", file_path="src/b.py"),
        )

        result = diff_inventories(old, new)
        assert result == []

    def test_no_double_counting_move_then_rename(self) -> None:
        """A symbol matched as a move is not also matched as rename."""
        old = _inv(
            _si(name="mover", module_path="src.old", file_path="src/old.py",
                lineno=5, symbol_type="function"),
        )
        new = _inv(
            _si(name="mover", module_path="src.new", file_path="src/new.py",
                lineno=5, symbol_type="function"),
        )

        result = diff_inventories(old, new)
        # Should only be a move, not also a rename
        assert len(result) == 1
        assert result[0].migration_type == "move"

    def test_complex_scenario_move_rename_split(self) -> None:
        """Multiple migration types detected in one diff."""
        old = _inv(
            # Will move
            _si(name="mover", module_path="src.old_loc", file_path="src/old_loc.py"),
            # Will be renamed
            _si(name="old_fn", module_path="src.stable", file_path="src/stable.py",
                lineno=5, symbol_type="function"),
            # Will split
            _si(name="split_a", module_path="src.big", file_path="src/big.py", lineno=1),
            _si(name="split_b", module_path="src.big", file_path="src/big.py", lineno=10),
        )
        new = _inv(
            # Moved
            _si(name="mover", module_path="src.new_loc", file_path="src/new_loc.py"),
            # Renamed
            _si(name="new_fn", module_path="src.stable", file_path="src/stable.py",
                lineno=5, symbol_type="function"),
            # Split
            _si(name="split_a", module_path="src.part1", file_path="src/part1.py", lineno=1),
            _si(name="split_b", module_path="src.part2", file_path="src/part2.py", lineno=1),
        )

        result = diff_inventories(old, new)
        types = {e.migration_type for e in result}
        assert "move" in types
        assert "rename" in types
        # split_a and split_b are detected as individual moves (same name,
        # different module) before the split phase runs, so they are moves
        # not splits: 3 moves (mover, split_a, split_b) + 1 rename (old_fn→new_fn)
        assert len(result) == 4
        move_names = {e.old_name for e in result if e.migration_type == "move"}
        assert move_names == {"mover", "split_a", "split_b"}
