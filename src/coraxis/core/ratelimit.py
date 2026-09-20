"""Async sliding-window rate limiting.

Deliberately dependency-free and in-process. That is correct for a single
worker and honest about its limits: with ``--workers N`` each worker keeps its
own window, so the effective limit is ``N * limit``. Swapping in a Redis-backed
implementation only requires replacing :class:`SlidingWindowLimiter` — every
call site goes through :func:`enforce`.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass
from typing import Final

from coraxis.core.errors import RateLimitError
from coraxis.core.logging import get_logger

logger = get_logger("ratelimit")

#: Hard ceiling on tracked keys. Prevents an attacker rotating identities from
#: growing the map without bound.
_MAX_KEYS: Final[int] = 50_000

#: When the ceiling is hit, evict down to this fraction of it rather than
#: freeing exactly one slot. Overshooting amortises the cost of the O(n log n)
#: sort so it does not run on every subsequent request.
_EVICTION_TARGET_RATIO: Final[float] = 0.9


@dataclass(frozen=True, slots=True)
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    reset_after: float

    def as_headers(self) -> dict[str, str]:
        return {
            "X-RateLimit-Limit": str(self.limit),
            "X-RateLimit-Remaining": str(max(0, self.remaining)),
            "X-RateLimit-Reset": str(int(self.reset_after)),
        }


class SlidingWindowLimiter:
    """Counts events per key over a rolling time window.

    A true sliding window (rather than a fixed bucket) means a client cannot
    burst twice the limit by straddling a boundary.
    """

    def __init__(self, *, max_keys: int = _MAX_KEYS) -> None:
        self._hits: dict[str, deque[float]] = {}
        self._lock = asyncio.Lock()
        self._max_keys = max_keys

    async def hit(self, key: str, limit: int, window_seconds: float) -> RateLimitResult:
        """Record one event and report whether the caller is still within budget."""
        if limit <= 0:
            # A limit of zero disables the check entirely.
            return RateLimitResult(True, limit, limit, 0.0)

        now = time.monotonic()
        cutoff = now - window_seconds

        async with self._lock:
            bucket = self._hits.get(key)
            if bucket is None:
                if len(self._hits) >= self._max_keys:
                    self._evict_locked(now, window_seconds)
                bucket = deque()
                self._hits[key] = bucket

            while bucket and bucket[0] <= cutoff:
                bucket.popleft()

            if len(bucket) >= limit:
                oldest = bucket[0]
                return RateLimitResult(
                    allowed=False,
                    limit=limit,
                    remaining=0,
                    reset_after=max(0.0, (oldest + window_seconds) - now),
                )

            bucket.append(now)
            return RateLimitResult(
                allowed=True,
                limit=limit,
                remaining=limit - len(bucket),
                reset_after=window_seconds,
            )

    async def reset(self, key: str) -> None:
        """Forget a key's history. Used by tests and admin actions."""
        async with self._lock:
            self._hits.pop(key, None)

    @property
    def key_count(self) -> int:
        """Number of keys currently tracked. Exposed for metrics and tests."""
        return len(self._hits)

    @property
    def max_keys(self) -> int:
        return self._max_keys

    async def clear(self) -> None:
        async with self._lock:
            self._hits.clear()

    def _evict_locked(self, now: float, window_seconds: float) -> None:
        """Free capacity in the key map. Must be called with the lock held.

        Two passes. The first drops buckets whose history has aged out
        entirely — those can no longer deny anyone, so discarding them is free.
        The second, reached only when the map is still saturated, evicts the
        least recently active buckets.

        That second pass is what makes the ceiling actually hard. Evicting
        stale buckets alone is not enough: a client rotating identities faster
        than the window expires keeps every bucket alive, so nothing is ever
        stale and the map grows without bound regardless of ``max_keys``.
        """
        cutoff = now - window_seconds
        stale = [key for key, bucket in self._hits.items() if not bucket or bucket[-1] <= cutoff]
        for key in stale:
            self._hits.pop(key, None)

        if len(self._hits) < self._max_keys:
            if stale:
                logger.debug("evicted %d stale rate-limit buckets", len(stale))
            return

        target = int(self._max_keys * _EVICTION_TARGET_RATIO)
        overflow = len(self._hits) - target
        # ``sorted`` on last-hit time is a good least-recently-used proxy and
        # runs rarely enough to be worth the clarity.
        ordered = sorted(self._hits.items(), key=lambda item: item[1][-1] if item[1] else 0.0)
        for key, _bucket in ordered[:overflow]:
            self._hits.pop(key, None)
        logger.debug(
            "rate-limit key map saturated: evicted %d stale and %d least-recently-active buckets",
            len(stale),
            overflow,
        )


#: Process-wide limiter. The API and the job runner share one budget.
limiter = SlidingWindowLimiter()


async def enforce(
    key: str,
    *,
    limit: int,
    window_seconds: float,
    message: str = "Rate limit exceeded. Slow down and retry shortly.",
) -> RateLimitResult:
    """Check a budget, raising :class:`RateLimitError` when it is exhausted."""
    result = await limiter.hit(key, limit, window_seconds)
    if not result.allowed:
        raise RateLimitError(message, retry_after=max(1, int(result.reset_after)))
    return result
