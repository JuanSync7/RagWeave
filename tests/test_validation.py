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
