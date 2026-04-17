import time
from unittest.mock import patch

from src.platform.limits.provider import InMemoryRateLimiter


def test_rate_limiter_allows_until_limit():
    limiter = InMemoryRateLimiter(limit=2, window_seconds=60)
    first = limiter.check("tenant:user")
    second = limiter.check("tenant:user")
    third = limiter.check("tenant:user")

    assert first.allowed is True
    assert second.allowed is True
    assert third.allowed is False
    assert third.retry_after_seconds > 0


def test_n_requests_within_window_all_pass():
    """Exactly N requests within the window are all allowed."""
    n = 5
    limiter = InMemoryRateLimiter(limit=n, window_seconds=60)
    for i in range(n):
        result = limiter.check("key-n")
        assert result.allowed is True, f"Request {i + 1} should have been allowed"


def test_n_plus_one_request_rejected():
    """The (N+1)th request within the window returns 429."""
    n = 3
    limiter = InMemoryRateLimiter(limit=n, window_seconds=60)
    for _ in range(n):
        limiter.check("key-429")
    rejected = limiter.check("key-429")
    assert rejected.allowed is False
    assert rejected.retry_after_seconds >= 1


def test_window_reset_allows_requests_again():
    """After the window expires the counter resets and requests pass again."""
    limiter = InMemoryRateLimiter(limit=1, window_seconds=1)
    first = limiter.check("key-reset")
    assert first.allowed is True

    rejected = limiter.check("key-reset")
    assert rejected.allowed is False

    # Advance time past the window using a mock so the test stays fast.
    future_time = time.time() + 2
    with patch("src.platform.limits.provider.time") as mock_time:
        mock_time.time.return_value = future_time
        after_reset = limiter.check("key-reset")

    assert after_reset.allowed is True


def test_per_principal_isolation():
    """One principal hitting the limit does not affect another principal."""
    limiter = InMemoryRateLimiter(limit=1, window_seconds=60)

    # Exhaust the limit for principal A
    limiter.check("principal-a")
    rejected_a = limiter.check("principal-a")
    assert rejected_a.allowed is False

    # Principal B should still be allowed
    result_b = limiter.check("principal-b")
    assert result_b.allowed is True

