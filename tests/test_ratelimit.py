from trendengine.utils.ratelimit import RateLimiter


def test_rate_limiter_blocks_within_interval():
    rl = RateLimiter()
    assert rl.ready("k", 100) is True   # first call passes
    assert rl.ready("k", 100) is False  # immediate second call blocked


def test_rate_limiter_independent_keys():
    rl = RateLimiter()
    assert rl.ready("a", 100) is True
    assert rl.ready("b", 100) is True
