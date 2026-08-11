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

Waiting longer is the wrong answer to reddit's *other* refusal, HTTP 403
("Blocked"), which is a policy decision rather than a pace complaint: reddit
serves the public RSS feeds to anyone but refuses the ``.json`` API outright
from many hosts (datacenter IP ranges especially), and it refuses every single
request, forever, no matter how slowly they arrive. Pacing those doomed
requests just means each one burns a full throttle interval before failing --
enough to stretch one subreddit's ingest past its whole scheduling window.

So 403s trip a circuit breaker instead. Endpoint classes get their own circuit
(the feeds staying readable while the JSON API is blocked is the common case),
and after a few consecutive 403s that class stops being requested at all for a
cooldown that doubles each time it re-trips, up to a ceiling. When the cooldown
expires the next request probes reddit again, so access is picked back up on
its own once whatever blocked us lifts.
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
# Reddit refuses requests it won't serve at all with 403 ("Blocked").
_BLOCKED_STATUS = 403
# Each re-trip of a circuit doubles its cooldown.
_COOLDOWN_FACTOR = 2.0


class RedditBlocked(requests.RequestException):
    """Raised in place of a request reddit is currently refusing.

    Subclasses ``RequestException`` so callers that already treat a failed
    fetch as "no data this time" need no special case.
    """


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


class RedditCircuit:
    """Consecutive-403 breaker for one class of reddit endpoint.

    Reddit blocks endpoints, not the host: the public RSS feeds keep serving
    while the ``.json`` API answers 403 to every request. So each class of
    endpoint gets its own circuit and a block on one doesn't stop the other.

    ``threshold`` consecutive 403s open the circuit for ``cooldown`` seconds,
    doubling on each re-trip up to ``max_cooldown``. A successful response
    closes it and resets the escalation; any non-403 response at least breaks
    the consecutive run. The consecutive count deliberately survives the
    cooldown expiring, so the first request after a cooldown acts as a probe:
    one more 403 re-opens the circuit immediately, at twice the wait.
    """

    def __init__(
        self,
        name: str,
        threshold: int,
        cooldown: float,
        max_cooldown: float,
    ):
        self.name = name
        self._threshold = max(1, int(threshold))
        self._base_cooldown = max(0.0, float(cooldown))
        self._max_cooldown = max(self._base_cooldown, float(max_cooldown))
        self._cooldown = self._base_cooldown
        self._consecutive = 0
        self._open_until: Optional[float] = None
        self._lock = threading.Lock()

    def remaining(self) -> Optional[float]:
        """Seconds until this endpoint may be requested again, or None if it
        may be requested now (which closes an expired circuit)."""
        with self._lock:
            if self._open_until is None:
                return None
            left = self._open_until - time.monotonic()
            if left <= 0:
                self._open_until = None
                return None
            return left

    def record_success(self) -> None:
        with self._lock:
            recovered = self._consecutive >= self._threshold
            self._consecutive = 0
            self._cooldown = self._base_cooldown
            self._open_until = None
        if recovered:
            logging.info(f"Reddit {self.name} requests are being served again")

    def record_allowed(self) -> None:
        """A response that wasn't a 403: reddit is answering, so the run of
        consecutive blocks is over even though it wasn't a success."""
        with self._lock:
            self._consecutive = 0

    def record_blocked(self) -> None:
        with self._lock:
            self._consecutive += 1
            if self._consecutive < self._threshold:
                return
            cooldown = self._cooldown
            self._open_until = time.monotonic() + cooldown
            self._cooldown = min(self._max_cooldown, self._cooldown * _COOLDOWN_FACTOR)
        logging.warning(
            f"Reddit is refusing {self.name} requests (HTTP {_BLOCKED_STATUS} "
            f"after {self._threshold} consecutive attempts); pausing them for "
            f"{cooldown / 60:.0f} min"
        )


_limiter: Optional[RedditRateLimiter] = None
_limiter_lock = threading.Lock()
_circuits: dict = {}
_circuits_lock = threading.Lock()


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


def circuit_name(url: str) -> str:
    """Which class of reddit endpoint ``url`` belongs to.

    Only the distinction reddit itself makes matters: it serves the public
    feeds to anyone while refusing the ``.json`` API from blocked hosts, so
    those two have to be able to fail independently.
    """
    path = (urlparse(str(url)).path or "").lower()
    return "post JSON" if path.endswith(".json") else "feed"


def get_circuit(url: str) -> RedditCircuit:
    name = circuit_name(url)
    circuit = _circuits.get(name)
    if circuit is None:
        with _circuits_lock:
            circuit = _circuits.get(name)
            if circuit is None:
                circuit = RedditCircuit(
                    name=name,
                    threshold=config.get_int("REDDIT_BLOCK_THRESHOLD"),
                    cooldown=config.get_float("REDDIT_BLOCK_COOLDOWN_SECONDS"),
                    max_cooldown=config.get_float(
                        "REDDIT_MAX_BLOCK_COOLDOWN_SECONDS"
                    ),
                )
                _circuits[name] = circuit
    return circuit


def reddit_get(url: str, **kwargs) -> requests.Response:
    """``requests.get`` for a reddit URL, gated by the global adaptive throttle.

    Waits for the shared limiter before firing, then feeds the response back
    into it so a 429 backs the whole process off and a success lets it creep
    faster. The response (including a 429) is returned to the caller unchanged;
    network errors propagate as usual and leave the throttle untouched.

    Raises ``RedditBlocked`` without contacting reddit at all while this kind
    of endpoint is in its post-403 cooldown -- the point of the breaker is that
    a blocked request costs nothing instead of a full throttle interval.
    """
    circuit = get_circuit(url)
    remaining = circuit.remaining()
    if remaining is not None:
        raise RedditBlocked(
            f"reddit is refusing {circuit.name} requests "
            f"(HTTP {_BLOCKED_STATUS}); not retrying for another "
            f"{remaining / 60:.0f} min"
        )

    limiter = get_limiter()
    limiter.acquire()
    response = requests.get(url, **kwargs)
    if response.status_code == _BLOCKED_STATUS:
        # A block isn't about pace, so the throttle is left alone: slowing the
        # feed fetches down would punish the requests reddit still serves.
        circuit.record_blocked()
        return response

    circuit.record_allowed()
    if response.status_code == 429:
        limiter.record_rate_limited(_parse_retry_after(response))
    elif response.ok:
        limiter.record_success()
        circuit.record_success()
    return response
