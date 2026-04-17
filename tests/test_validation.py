from pathlib import Path

import pytest

from src.platform.validation import (
    validate_alpha,
    validate_filter_value,
    validate_positive_int,
    validate_documents_dir,
)


def test_validate_alpha_bounds():
    assert validate_alpha(0.0) == 0.0
    assert validate_alpha(1.0) == 1.0
    with pytest.raises(ValueError):
        validate_alpha(1.1)


def test_validate_positive_int():
    assert validate_positive_int("x", 1) == 1
    with pytest.raises(ValueError):
        validate_positive_int("x", 0)


def test_validate_filter_value():
    assert validate_filter_value("source_filter", "a-b/c.txt") == "a-b/c.txt"
    with pytest.raises(ValueError):
        validate_filter_value("source_filter", "bad;value")


def test_validate_documents_dir(tmp_path: Path):
    root = tmp_path / "proj"
    docs = root / "documents"
    docs.mkdir(parents=True)
    assert validate_documents_dir(docs, root) == docs.resolve()


# ---------------------------------------------------------------------------
# Additional coverage
# ---------------------------------------------------------------------------

def test_validate_alpha_negative_raises():
    with pytest.raises(ValueError):
        validate_alpha(-0.1)


def test_validate_alpha_midpoint():
    assert validate_alpha(0.5) == 0.5


def test_validate_positive_int_negative_raises():
    with pytest.raises(ValueError):
        validate_positive_int("count", -5)


def test_validate_positive_int_large_value():
    assert validate_positive_int("n", 1_000_000) == 1_000_000


def test_validate_filter_value_none_returns_none():
    assert validate_filter_value("f", None) is None


def test_validate_filter_value_empty_returns_none():
    assert validate_filter_value("f", "   ") is None


def test_validate_filter_value_whitespace_stripped():
    # Leading/trailing whitespace is stripped; the stripped value must pass the regex
    result = validate_filter_value("f", "  valid.txt  ")
    assert result == "valid.txt"


def test_validate_filter_value_semicolon_raises():
    with pytest.raises(ValueError):
        validate_filter_value("f", "path;rm -rf")


def test_validate_filter_value_pipe_raises():
    with pytest.raises(ValueError):
        validate_filter_value("f", "data|bad")


def test_validate_documents_dir_outside_root_raises(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    outside = tmp_path / "other"
    outside.mkdir()
    with pytest.raises(ValueError):
        validate_documents_dir(outside, root)


def test_validate_documents_dir_symlink_raises(tmp_path: Path):
    root = tmp_path / "proj"
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    root.mkdir()
    link = root / "link_docs"
    link.symlink_to(real_dir)
    with pytest.raises(ValueError):
        validate_documents_dir(link, root)
