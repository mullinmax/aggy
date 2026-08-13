import pytest

from config import config
from ingest import host_circuit
from ingest.host_circuit import HostCircuit, HostUnavailable


@pytest.fixture(autouse=True)
def clean_circuits():
    """Circuits are process-global, so each test starts from nothing."""
    host_circuit.reset()
    yield
    host_circuit.reset()


@pytest.fixture
def tight_breaker():
    """A breaker that trips after two failures, with a short cooldown."""
    settings = {
        "HOST_FAILURE_THRESHOLD": 2,
        "HOST_COOLDOWN_SECONDS": 600.0,
        "HOST_MAX_COOLDOWN_SECONDS": 2400.0,
    }
    previous = {key: config.get(key, None) for key in settings}
    for key, value in settings.items():
        config.set(key, value)
    yield
    for key, value in previous.items():
        if value is None:
            config.config.pop(key, None)
        else:
            config.set(key, value)


YT = "https://www.youtube.com/feeds/videos.xml?channel_id=UC123"


def test_source_host_folds_to_the_registrable_domain():
    """Sources spread across subdomains have to share one verdict, or a site
    that fails on www and m looks like two half-broken sites."""
    assert host_circuit.source_host(YT) == "youtube.com"
    assert host_circuit.source_host("https://m.youtube.com/x") == "youtube.com"
    assert host_circuit.source_host("https://news.bbc.co.uk/rss") == "bbc.co.uk"
    assert host_circuit.source_host(None) == "unknown"


def test_a_healthy_host_is_never_gated(tight_breaker):
    host_circuit.check(YT)  # does not raise
    host_circuit.record_success(YT)
    host_circuit.check(YT)


def test_failures_below_the_threshold_do_not_trip_it(tight_breaker):
    """One flaky fetch must not pause a working site."""
    host_circuit.record_failure(YT)

    host_circuit.check(YT)


def test_consecutive_failures_open_the_circuit(tight_breaker):
    for _ in range(2):
        host_circuit.record_failure(YT)

    with pytest.raises(HostUnavailable) as excinfo:
        host_circuit.check(YT)

    assert excinfo.value.host == "youtube.com"
    assert excinfo.value.remaining > 0


def test_a_success_between_failures_resets_the_run(tight_breaker):
    """The threshold counts *consecutive* failures: a site answering every
    other request is degraded, not down, and pausing it loses real articles."""
    host_circuit.record_failure(YT)
    host_circuit.record_success(YT)
    host_circuit.record_failure(YT)

    host_circuit.check(YT)


def test_one_hosts_failures_do_not_gate_another(tight_breaker):
    for _ in range(2):
        host_circuit.record_failure(YT)

    host_circuit.check("https://example.com/feed.xml")


def test_the_cooldown_expiring_lets_one_probe_through(tight_breaker, monkeypatch):
    circuit = HostCircuit(
        host="youtube.com", threshold=2, cooldown=600.0, max_cooldown=2400.0
    )
    clock = {"now": 1000.0}
    monkeypatch.setattr(host_circuit.time, "monotonic", lambda: clock["now"])

    circuit.record_failure()
    circuit.record_failure()
    assert circuit.remaining() == 600.0

    clock["now"] += 601
    assert circuit.remaining() is None


def test_a_re_trip_doubles_the_wait(tight_breaker, monkeypatch):
    """A site that is still down after the first cooldown gets asked half as
    often, so a long outage costs a handful of requests rather than hundreds."""
    circuit = HostCircuit(
        host="youtube.com", threshold=2, cooldown=600.0, max_cooldown=2400.0
    )
    clock = {"now": 1000.0}
    monkeypatch.setattr(host_circuit.time, "monotonic", lambda: clock["now"])

    circuit.record_failure()
    circuit.record_failure()
    assert circuit.remaining() == 600.0

    # cooldown lapses, the probe fails: one failure is enough to re-open,
    # because the consecutive count survives the cooldown
    clock["now"] += 601
    circuit.record_failure()
    assert circuit.remaining() == 1200.0

    clock["now"] += 1201
    circuit.record_failure()
    assert circuit.remaining() == 2400.0

    # and it stops doubling at the ceiling
    clock["now"] += 2401
    circuit.record_failure()
    assert circuit.remaining() == 2400.0


def test_a_successful_probe_closes_the_circuit_and_resets_escalation(
    tight_breaker, monkeypatch
):
    circuit = HostCircuit(
        host="youtube.com", threshold=2, cooldown=600.0, max_cooldown=2400.0
    )
    clock = {"now": 1000.0}
    monkeypatch.setattr(host_circuit.time, "monotonic", lambda: clock["now"])

    circuit.record_failure()
    circuit.record_failure()
    clock["now"] += 601
    circuit.record_failure()
    assert circuit.remaining() == 1200.0

    clock["now"] += 1201
    circuit.record_success()
    assert circuit.remaining() is None

    # back to the base cooldown, not the escalated one
    circuit.record_failure()
    circuit.record_failure()
    assert circuit.remaining() == 600.0


def test_open_hosts_reports_what_is_paused(tight_breaker):
    for _ in range(2):
        host_circuit.record_failure(YT)
    host_circuit.record_failure("https://example.com/feed.xml")

    paused = host_circuit.open_hosts()

    assert set(paused) == {"youtube.com"}
    assert paused["youtube.com"] > 0


def test_the_error_says_when_the_site_will_be_tried_again(tight_breaker):
    for _ in range(2):
        host_circuit.record_failure(YT)

    with pytest.raises(HostUnavailable, match="youtube.com"):
        host_circuit.check(YT)
