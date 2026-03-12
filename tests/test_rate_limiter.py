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

