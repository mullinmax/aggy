"""A process-global circuit breaker keyed on the site a source fetches from.

Sources fail in groups. When YouTube's feed endpoint breaks, it doesn't break
for one channel -- it breaks for every channel source at once, and with the
ingest job popping one due source every fifteen seconds, forty dead YouTube
sources means forty scheduling slots per cycle spent re-learning the same fact.
That starves every healthy source behind them, which is the actual damage: the
outage isn't ours to fix, but the queue it clogs is.

So consecutive failures are counted per *site* rather than per source. After
``threshold`` of them the site's circuit opens and its sources are skipped
outright for a cooldown that doubles on each re-trip, up to a ceiling. A skip
costs nothing -- no request, no scheduling slot held open -- so the rest of the
queue moves at full speed while the site is down.

The count is per registrable domain (``base_domain``), not per hostname, so
sources spread across ``www.youtube.com`` and ``youtube.com`` share one verdict
about whether YouTube is answering.

When the cooldown expires the next due source for that site is allowed through
as a probe. If it succeeds the circuit closes and the escalation resets; if it
fails the circuit re-opens immediately at twice the wait. Recovery therefore
needs no intervention and costs one request per cooldown period.

This sits *above* the reddit throttle in ``ingest.reddit_rate_limit``, which
paces individual HTTP requests within a fetch. This breaker doesn't pace
anything -- it decides whether a whole source is worth attempting at all.
"""

import logging
import threading
import time
from typing import Optional
from urllib.parse import urlparse

from config import config
from db.stats import base_domain

# Each re-trip of a site's circuit doubles its cooldown.
_COOLDOWN_FACTOR = 2.0


class HostUnavailable(Exception):
    """Raised instead of attempting a source whose site is in cooldown.

    Carries the seconds remaining so the caller can say when the site will be
    tried again rather than just that it was skipped.
    """

    def __init__(self, host: str, remaining: float):
        self.host = host
        self.remaining = remaining
        super().__init__(
            f"Skipped: {host} has been failing every request; "
            f"not retrying it for another {remaining / 60:.0f} min"
        )


def source_host(url: Optional[str]) -> str:
    """The registrable domain a source fetches from, e.g. ``youtube.com``."""
    if not url:
        return "unknown"
    try:
        return base_domain(urlparse(str(url)).hostname)
    except ValueError:
        return "unknown"


class HostCircuit:
    """Consecutive-failure breaker for one site.

    ``threshold`` consecutive failures open the circuit for ``cooldown``
    seconds, doubling on each re-trip up to ``max_cooldown``. A success closes
    it and resets the escalation.

    The consecutive count deliberately survives the cooldown expiring, so the
    first attempt afterwards acts as a probe: one more failure re-opens the
    circuit at twice the wait instead of letting the site spend another full
    ``threshold`` attempts proving it is still down.
    """

    def __init__(
        self, host: str, threshold: int, cooldown: float, max_cooldown: float
    ):
        self.host = host
        self._threshold = max(1, int(threshold))
        self._base_cooldown = max(0.0, float(cooldown))
        self._max_cooldown = max(self._base_cooldown, float(max_cooldown))
        self._cooldown = self._base_cooldown
        self._consecutive = 0
        self._open_until: Optional[float] = None
        self._lock = threading.Lock()

    def remaining(self) -> Optional[float]:
        """Seconds until this site may be attempted again, or None if it may be
        attempted now (which closes an expired circuit)."""
        with self._lock:
            if self._open_until is None:
                return None
            left = self._open_until - time.monotonic()
            if left <= 0:
                self._open_until = None
                return None
            return left

    @property
    def is_open(self) -> bool:
        return self.remaining() is not None

    def record_success(self) -> None:
        with self._lock:
            recovered = self._consecutive >= self._threshold
            self._consecutive = 0
            self._cooldown = self._base_cooldown
            self._open_until = None
        if recovered:
            logging.info(f"{self.host} is answering again; resuming its sources")

    def record_failure(self) -> None:
        with self._lock:
            self._consecutive += 1
            if self._consecutive < self._threshold:
                return
            cooldown = self._cooldown
            self._open_until = time.monotonic() + cooldown
            self._cooldown = min(self._max_cooldown, self._cooldown * _COOLDOWN_FACTOR)
        logging.warning(
            f"{self.host} has failed {self._threshold} consecutive ingests; "
            f"skipping its sources for {cooldown / 60:.0f} min"
        )


_circuits: dict = {}
_circuits_lock = threading.Lock()


def get_circuit(host: str) -> HostCircuit:
    circuit = _circuits.get(host)
    if circuit is None:
        with _circuits_lock:
            circuit = _circuits.get(host)
            if circuit is None:
                circuit = HostCircuit(
                    host=host,
                    threshold=config.get_int("HOST_FAILURE_THRESHOLD"),
                    cooldown=config.get_float("HOST_COOLDOWN_SECONDS"),
                    max_cooldown=config.get_float("HOST_MAX_COOLDOWN_SECONDS"),
                )
                _circuits[host] = circuit
    return circuit


def check(url: str) -> None:
    """Raise ``HostUnavailable`` if this URL's site is in its failure cooldown."""
    host = source_host(url)
    circuit = get_circuit(host)
    remaining = circuit.remaining()
    if remaining is not None:
        raise HostUnavailable(host, remaining)


def record_success(url: str) -> None:
    get_circuit(source_host(url)).record_success()


def record_failure(url: str) -> None:
    get_circuit(source_host(url)).record_failure()


def open_hosts() -> dict:
    """Sites currently in cooldown, mapped to the seconds left on it.

    Read by the stats page so a site being skipped is visible as a state rather
    than inferred from a gap in the attempt history.
    """
    with _circuits_lock:
        circuits = list(_circuits.values())

    open_now = {}
    for circuit in circuits:
        remaining = circuit.remaining()
        if remaining is not None:
            open_now[circuit.host] = remaining
    return open_now


def reset() -> None:
    """Forget every circuit. For tests."""
    with _circuits_lock:
        _circuits.clear()
