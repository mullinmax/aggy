"""A process-global, adaptive throttle for all requests to reddit.com.

Reddit rate-limits anonymous requests aggressively and answers with HTTP 429
when we push too hard. Every reddit request Aggy makes -- fetching a
subreddit/user RSS feed and fetching each post's JSON for media -- goes through
a single shared limiter so the whole process stays under one budget rather than
each ingest job hammering reddit independently.

The limiter spaces requests by a delay that adapts using AIMD (additive
increase, multiplicative decrease) in *rate* space:

* on success the request rate creeps up by a small fixed step, so throughput
  very cautiously climbs back toward reddit's real limit;
* on HTTP 429 the rate is halved (the delay doubles) for an exponential
  backoff, honoring any ``Retry-After`` the server sends.

Over time this converges to just under whatever reddit is currently allowing.
"""

import logging
import threading
import time
from typing import Optional
from urllib.parse import urlparse

import requests

from config import config

# Rate is halved on each 429 (delay doubles): a sharp exponential backoff.
_BACKOFF_FACTOR = 2.0
# Rate gained per successful request, in requests/second. Deliberately tiny so
# recovery is slow and we don't immediately walk back into a 429.
_RECOVERY_RATE_STEP = 0.01


def is_reddit_url(url: Optional[str]) -> bool:
    """True if ``url`` points at reddit.com (any subdomain)."""
    if not url:
        return False
    try:
        host = (urlparse(str(url)).hostname or "").lower()
    except ValueError:
        return False
    return host == "reddit.com" or host.endswith(".reddit.com")


def _parse_retry_after(response: requests.Response) -> Optional[float]:
    value = response.headers.get("Retry-After")
    if not value:
        return None
    try:
        # reddit sends Retry-After as an integer number of seconds
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return None


class RedditRateLimiter:
    """Thread-safe adaptive delay gate shared across all reddit requests."""

    def __init__(
        self,
        min_interval: float,
        max_interval: float,
        initial_interval: float,
    ):
        self._min = max(0.0, float(min_interval))
        self._max = max(self._min, float(max_interval))
        self._interval = min(self._max, max(self._min, float(initial_interval)))
        self._lock = threading.Lock()
        # monotonic timestamp before which the next request must not fire
        self._next_allowed = 0.0

    @property
    def interval(self) -> float:
        with self._lock:
            return self._interval

    def acquire(self) -> None:
        """Block until the next request is allowed, reserving its slot.

        The slot is reserved under the lock (so concurrent callers queue up
        behind one another spaced by the current delay) but the actual sleep
        happens outside the lock so waiting threads don't serialize the CPU.
        """
        with self._lock:
            start = max(time.monotonic(), self._next_allowed)
            self._next_allowed = start + self._interval
        wait = start - time.monotonic()
        if wait > 0:
            time.sleep(wait)

    def record_success(self) -> None:
        """Cautiously speed up: nudge the request rate up by a fixed step."""
        with self._lock:
            rate = 1.0 / self._interval if self._interval > 0 else float("inf")
            rate += _RECOVERY_RATE_STEP
            new_interval = 1.0 / rate if rate > 0 else self._max
            self._interval = min(self._max, max(self._min, new_interval))

    def record_rate_limited(self, retry_after: Optional[float] = None) -> None:
        """Back off hard: double the delay and respect any Retry-After."""
        with self._lock:
            self._interval = min(self._max, self._interval * _BACKOFF_FACTOR)
            penalty = self._interval
            if retry_after is not None:
                penalty = max(penalty, retry_after)
            self._next_allowed = max(
                self._next_allowed, time.monotonic() + penalty
            )
            logging.warning(
                "Reddit rate limited (HTTP 429); backing off to "
                f"{self._interval:.1f}s between requests"
                + (f", retry after {retry_after:.0f}s" if retry_after else "")
            )


_limiter: Optional[RedditRateLimiter] = None
_limiter_lock = threading.Lock()


def get_limiter() -> RedditRateLimiter:
    global _limiter
    if _limiter is None:
        with _limiter_lock:
            if _limiter is None:
                _limiter = RedditRateLimiter(
                    min_interval=config.get_float(
                        "REDDIT_MIN_REQUEST_INTERVAL_SECONDS"
                    ),
                    max_interval=config.get_float(
                        "REDDIT_MAX_REQUEST_INTERVAL_SECONDS"
                    ),
                    initial_interval=config.get_float(
                        "REDDIT_INITIAL_REQUEST_INTERVAL_SECONDS"
                    ),
                )
    return _limiter


def reddit_get(url: str, **kwargs) -> requests.Response:
    """``requests.get`` for a reddit URL, gated by the global adaptive throttle.

    Waits for the shared limiter before firing, then feeds the response back
    into it so a 429 backs the whole process off and a success lets it creep
    faster. The response (including a 429) is returned to the caller unchanged;
    network errors propagate as usual and leave the throttle untouched.
    """
    limiter = get_limiter()
    limiter.acquire()
    response = requests.get(url, **kwargs)
    if response.status_code == 429:
        limiter.record_rate_limited(_parse_retry_after(response))
    elif response.ok:
        limiter.record_success()
    return response
