"""Tests for src.platform.observability.providers — deprecated backward-compat shim.

Covers:
- Module-level DeprecationWarning emitted on import
- Warning message content (mentions "providers" and "deprecated")
- Warning category (DeprecationWarning, not subclass)
- get_tracer re-export availability and identity
- __all__ contents
- Module cache handling (reload for fresh warning emission)
"""
from __future__ import annotations

import importlib
import sys
import warnings
from typing import Generator

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reload_providers() -> Generator[None, None, None]:
    """Remove providers module from sys.modules before and after each test.

    This ensures the module-level DeprecationWarning is emitted fresh on each
    import. Python's module cache prevents the warning from firing on subsequent
    imports within the same process.
    """
    sys.modules.pop("src.platform.observability.providers", None)
    yield
    sys.modules.pop("src.platform.observability.providers", None)


# ---------------------------------------------------------------------------
# Happy path tests
# ---------------------------------------------------------------------------


def test_import_emits_deprecation_warning() -> None:
    """Test that importing providers module emits a DeprecationWarning."""
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        import src.platform.observability.providers  # noqa: F401
        assert len(w) >= 1, "Expected at least one warning"
        deprecation_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
        assert len(deprecation_warnings) >= 1, "Expected at least one DeprecationWarning"


def test_deprecation_warning_category() -> None:
    """Test that the warning is exactly DeprecationWarning, not a subclass."""
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        import src.platform.observability.providers  # noqa: F401
        deprecation_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
        assert len(deprecation_warnings) >= 1
        # Check that the category is DeprecationWarning (exact match)
        assert any(x.category is DeprecationWarning for x in deprecation_warnings)


def test_deprecation_warning_message_mentions_providers() -> None:
    """Test that the warning message mentions 'providers' or 'deprecated'."""
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        import src.platform.observability.providers  # noqa: F401
        deprecation_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
        assert len(deprecation_warnings) >= 1
        message = str(deprecation_warnings[0].message).lower()
        assert "providers" in message or "deprecated" in message, (
            f"Warning message should mention 'providers' or 'deprecated'. "
            f"Got: {deprecation_warnings[0].message}"
        )


def test_get_tracer_importable() -> None:
    """Test that get_tracer can be imported from providers module."""
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        from src.platform.observability.providers import get_tracer  # noqa: F401
        # If we got here without an ImportError, import succeeded
        assert get_tracer is not None


def test_get_tracer_is_callable() -> None:
    """Test that get_tracer from providers is callable."""
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        from src.platform.observability.providers import get_tracer
        assert callable(get_tracer), "get_tracer should be callable"


def test_get_tracer_identity_matches_public_api() -> None:
    """Test that providers.get_tracer is the same object as public API get_tracer.

    This verifies the re-export points to the same function object.
    """
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        from src.platform.observability.providers import get_tracer as providers_get_tracer
        from src.platform.observability import get_tracer as public_get_tracer
        assert (
            providers_get_tracer is public_get_tracer
        ), "providers.get_tracer should be the same object as public API get_tracer"


def test_all_contains_get_tracer() -> None:
    """Test that __all__ in providers contains 'get_tracer'."""
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        import src.platform.observability.providers
        assert (
            "get_tracer" in src.platform.observability.providers.__all__
        ), "__all__ should contain 'get_tracer'"


# ---------------------------------------------------------------------------
# Boundary condition tests
# ---------------------------------------------------------------------------


def test_warning_stacklevel_points_to_caller() -> None:
    """Test that warning stacklevel is set appropriately (stacklevel=2).

    This ensures the warning points to the import statement, not the
    warnings.warn() call inside providers.py.
    """
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        import src.platform.observability.providers  # noqa: F401
        deprecation_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
        assert len(deprecation_warnings) >= 1
        # Check that filename is this test file or test runner, not providers.py
        warning = deprecation_warnings[0]
        # The filename should not be providers.py itself (stacklevel=2 points caller)
        assert "providers.py" not in warning.filename or "test_providers" in warning.filename


def test_no_exception_on_import() -> None:
    """Test that importing providers does not raise an exception.

    Only a warning should be emitted; no runtime error.
    """
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        # This should not raise
        import src.platform.observability.providers  # noqa: F401


def test_all_is_list() -> None:
    """Test that __all__ is a proper list/sequence."""
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        import src.platform.observability.providers
        assert isinstance(
            src.platform.observability.providers.__all__, (list, tuple)
        ), "__all__ should be a list or tuple"


def test_all_length() -> None:
    """Test that __all__ has exactly one item (get_tracer)."""
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        import src.platform.observability.providers
        assert (
            len(src.platform.observability.providers.__all__) == 1
        ), "__all__ should contain exactly one item"


# ---------------------------------------------------------------------------
# Known gaps and integration points
# ---------------------------------------------------------------------------


def test_from_import_also_emits_warning() -> None:
    """Test that 'from providers import get_tracer' also emits the warning.

    This verifies that the warning fires at module import time, regardless
    of whether the import statement is 'import' or 'from X import Y'.
    """
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        # Using __import__ to ensure fresh import with from syntax
        providers_mod = __import__(
            "src.platform.observability.providers", fromlist=["get_tracer"]
        )
        deprecation_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
        assert len(deprecation_warnings) >= 1, (
            "DeprecationWarning should be emitted on 'from' import as well"
        )


def test_multiple_imports_within_same_process() -> None:
    """Test that warning fires on first fresh import; subsequent imports cached.

    This documents the expected behavior with module caching. The fixture
    resets sys.modules between tests to enable fresh imports per test.
    """
    # First import (fresh)
    with warnings.catch_warnings(record=True) as w1:
        warnings.simplefilter("always")
        import src.platform.observability.providers as providers1  # noqa: F401
        w1_deprecated = [x for x in w1 if issubclass(x.category, DeprecationWarning)]
        assert len(w1_deprecated) >= 1, "First import should emit warning"

    # Second import within same test (module cached, no fresh warning)
    with warnings.catch_warnings(record=True) as w2:
        warnings.simplefilter("always")
        import src.platform.observability.providers as providers2  # noqa: F401
        w2_deprecated = [x for x in w2 if issubclass(x.category, DeprecationWarning)]
        # Note: module is cached, so second import doesn't re-execute module code
        # This is expected Python behavior; fixture ensures fresh import per test
        assert (
            len(w2_deprecated) == 0
        ), "Second import (cached) should not emit fresh warning"


def test_warning_message_suggests_public_api() -> None:
    """Test that the warning message suggests using the public API."""
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        import src.platform.observability.providers  # noqa: F401
        deprecation_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
        assert len(deprecation_warnings) >= 1
        message = str(deprecation_warnings[0].message)
        # Check for guidance to use public API
        assert (
            "src.platform.observability" in message
        ), "Warning should suggest using the public API path"
