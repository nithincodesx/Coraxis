"""Unit tests for the sliding-window rate limiter."""

from __future__ import annotations

import asyncio

import pytest

from coraxis.core import ratelimit
from coraxis.core.errors import RateLimitError
from coraxis.core.ratelimit import SlidingWindowLimiter


async def test_allows_up_to_the_limit_then_blocks() -> None:
    limiter = SlidingWindowLimiter()

    for index in range(3):
        result = await limiter.hit("client", limit=3, window_seconds=60)
        assert result.allowed, f"request {index + 1} should have been allowed"
        assert result.remaining == 2 - index

    blocked = await limiter.hit("client", limit=3, window_seconds=60)
    assert not blocked.allowed
    assert blocked.remaining == 0
    assert blocked.reset_after > 0


async def test_keys_are_independent() -> None:
    limiter = SlidingWindowLimiter()
    await limiter.hit("alice", limit=1, window_seconds=60)

    assert not (await limiter.hit("alice", limit=1, window_seconds=60)).allowed
    assert (await limiter.hit("bob", limit=1, window_seconds=60)).allowed


async def test_window_slides() -> None:
    """A true sliding window, so a client cannot burst across a boundary."""
    limiter = SlidingWindowLimiter()
    await limiter.hit("client", limit=1, window_seconds=0.15)

    assert not (await limiter.hit("client", limit=1, window_seconds=0.15)).allowed
    await asyncio.sleep(0.2)
    assert (await limiter.hit("client", limit=1, window_seconds=0.15)).allowed


async def test_zero_limit_disables_the_check() -> None:
    limiter = SlidingWindowLimiter()
    for _ in range(10):
        assert (await limiter.hit("client", limit=0, window_seconds=60)).allowed


async def test_reset_clears_a_key() -> None:
    limiter = SlidingWindowLimiter()
    await limiter.hit("client", limit=1, window_seconds=60)
    await limiter.reset("client")
    assert (await limiter.hit("client", limit=1, window_seconds=60)).allowed


async def test_enforce_raises_with_a_retry_hint() -> None:
    # `enforce` drives the process-wide limiter, so reset that one rather than
    # constructing a local instance the function will never consult.
    await ratelimit.limiter.clear()
    await ratelimit.limiter.hit("key", limit=1, window_seconds=60)

    with pytest.raises(RateLimitError) as excinfo:
        await ratelimit.enforce("key", limit=1, window_seconds=60)

    assert excinfo.value.retry_after >= 1
    assert excinfo.value.status_code == 429


async def test_concurrent_hits_do_not_exceed_the_limit() -> None:
    """The limiter must be safe under concurrent access."""
    limiter = SlidingWindowLimiter()
    results = await asyncio.gather(
        *(limiter.hit("shared", limit=10, window_seconds=60) for _ in range(50))
    )
    assert sum(1 for result in results if result.allowed) == 10


async def test_key_count_is_bounded() -> None:
    """A client rotating identities must not grow the map without limit.

    Evicting only *stale* buckets is not sufficient: rotating faster than the
    window expires keeps every bucket alive, so the ceiling has to be enforced
    by dropping the least recently active keys.
    """
    limiter = SlidingWindowLimiter(max_keys=50)
    for index in range(500):
        await limiter.hit(f"key-{index}", limit=5, window_seconds=0.01)

    assert limiter.key_count <= limiter.max_keys


async def test_headers_are_renderable() -> None:
    limiter = SlidingWindowLimiter()
    result = await limiter.hit("client", limit=10, window_seconds=60)
    headers = result.as_headers()

    assert headers["X-RateLimit-Limit"] == "10"
    assert headers["X-RateLimit-Remaining"] == "9"
    assert int(headers["X-RateLimit-Reset"]) >= 0
