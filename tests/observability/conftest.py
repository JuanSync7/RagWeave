"""Observability test fixtures.

Resets the module-level singleton AND config.settings.OBSERVABILITY_PROVIDER before
and after each test. This prevents cross-suite contamination where another test file
leaves OBSERVABILITY_PROVIDER="langfuse", causing get_tracer() to return LangfuseBackend
instead of NoopBackend in tests that expect the noop path.

Using direct attribute assignment (not monkeypatch) so that cleanup always sets the
value to "noop" regardless of what a previous test left behind. Monkeypatch-based cleanup
would restore the contaminated value if it was the "original" when the fixture ran.
"""
import pytest
import src.platform.observability as _obs_module


@pytest.fixture(autouse=True)
def reset_observability_singleton():
    """Reset backend singleton and force OBSERVABILITY_PROVIDER=noop around every test."""
    import config.settings as _settings

    # Force noop before test, regardless of whatever upstream tests left
    _settings.OBSERVABILITY_PROVIDER = "noop"
    _obs_module._backend = None

    yield

    # Force noop after test too, so the next test also starts clean
    _settings.OBSERVABILITY_PROVIDER = "noop"
    _obs_module._backend = None
