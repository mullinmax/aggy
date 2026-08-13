"""The breaker and the attempt log as the ingest job actually drives them."""

import pytest

from config import config
from db.base import get_db_con
from db.source_attempt import source_stats
from ingest import host_circuit, jobs
from ingest.host_circuit import HostUnavailable


@pytest.fixture(autouse=True)
def clean_state(existing_user):
    with get_db_con() as cur:
        cur.execute(
            "DELETE FROM source_ingest_attempts WHERE user_hash = %s",
            (existing_user.name_hash,),
        )
    host_circuit.reset()
    yield
    host_circuit.reset()


@pytest.fixture
def tight_breaker():
    previous = config.get("HOST_FAILURE_THRESHOLD", None)
    config.set("HOST_FAILURE_THRESHOLD", 2)
    yield
    if previous is None:
        config.config.pop("HOST_FAILURE_THRESHOLD", None)
    else:
        config.set("HOST_FAILURE_THRESHOLD", previous)


def _attempts(user_hash):
    with get_db_con() as cur:
        cur.execute(
            "SELECT host, outcome, error FROM source_ingest_attempts "
            "WHERE user_hash = %s ORDER BY id",
            (user_hash,),
        )
        return [dict(row) for row in cur.fetchall()]


def test_a_successful_ingest_is_logged_as_ok(monkeypatch, existing_source):
    monkeypatch.setattr(jobs, "ingest_source", lambda source: None)

    jobs._ingest_with_circuit(existing_source)

    logged = _attempts(existing_source.user_hash)
    assert [row["outcome"] for row in logged] == ["ok"]
    assert logged[0]["host"] == "example.com"


def test_a_failed_ingest_is_logged_with_its_reason(monkeypatch, existing_source):
    def boom(source):
        raise Exception("Feed request returned HTTP 404")

    monkeypatch.setattr(jobs, "ingest_source", boom)

    with pytest.raises(Exception, match="HTTP 404"):
        jobs._ingest_with_circuit(existing_source)

    logged = _attempts(existing_source.user_hash)
    assert logged[0]["outcome"] == "error"
    assert "HTTP 404" in logged[0]["error"]


def test_repeated_failures_stop_the_site_being_fetched(
    monkeypatch, existing_source, tight_breaker
):
    """The regression this is all for: a dead site stops consuming a scheduling
    slot per source per cycle, so the healthy sources behind it keep moving."""
    calls = []

    def boom(source):
        calls.append(source.name_hash)
        raise Exception("Feed request returned HTTP 404")

    monkeypatch.setattr(jobs, "ingest_source", boom)

    for _ in range(2):
        with pytest.raises(Exception, match="HTTP 404"):
            jobs._ingest_with_circuit(existing_source)

    assert len(calls) == 2

    # the site is now in cooldown: the next pass never reaches the network
    with pytest.raises(HostUnavailable):
        jobs._ingest_with_circuit(existing_source)

    assert len(calls) == 2

    outcomes = [row["outcome"] for row in _attempts(existing_source.user_hash)]
    assert outcomes == ["error", "error", "skipped"]


def test_a_skip_does_not_deepen_the_backoff(
    monkeypatch, existing_source, tight_breaker
):
    """Skips must not feed back into the breaker, or a site with many sources
    would escalate its own cooldown to the ceiling without a single request."""
    monkeypatch.setattr(
        jobs, "ingest_source", lambda source: (_ for _ in ()).throw(Exception("boom"))
    )

    for _ in range(2):
        with pytest.raises(Exception, match="boom"):
            jobs._ingest_with_circuit(existing_source)

    first = host_circuit.open_hosts()["example.com"]

    for _ in range(10):
        with pytest.raises(HostUnavailable):
            jobs._ingest_with_circuit(existing_source)

    assert host_circuit.open_hosts()["example.com"] <= first


def test_a_success_reopens_the_site(monkeypatch, existing_source, tight_breaker):
    monkeypatch.setattr(
        jobs, "ingest_source", lambda source: (_ for _ in ()).throw(Exception("boom"))
    )
    with pytest.raises(Exception):
        jobs._ingest_with_circuit(existing_source)

    monkeypatch.setattr(jobs, "ingest_source", lambda source: None)
    jobs._ingest_with_circuit(existing_source)

    # the run of failures is broken, so the next one doesn't trip the breaker
    monkeypatch.setattr(
        jobs, "ingest_source", lambda source: (_ for _ in ()).throw(Exception("boom"))
    )
    with pytest.raises(Exception):
        jobs._ingest_with_circuit(existing_source)

    assert "example.com" not in host_circuit.open_hosts()


def test_feed_sources_are_exempt(monkeypatch, existing_feed, existing_user):
    """A feed source reads our own database rather than a site, so it has no
    host whose reliability it could speak to -- and must never be able to pause
    one by failing."""
    from db.source import Source, feed_source_url

    source = Source(
        user_hash=existing_user.name_hash,
        feed_hash=existing_feed.name_hash,
        name="A feed source",
        url=feed_source_url(existing_feed.name_hash),
        source_feed_hash=existing_feed.name_hash,
    )
    existing_feed.add_source(source)

    monkeypatch.setattr(jobs, "ingest_source", lambda source: None)

    jobs._ingest_with_circuit(source)

    assert _attempts(existing_user.name_hash) == []


def test_the_stats_page_sees_what_the_job_recorded(
    monkeypatch, existing_source, tight_breaker
):
    monkeypatch.setattr(
        jobs,
        "ingest_source",
        lambda source: (_ for _ in ()).throw(Exception("Feed request returned HTTP 404")),
    )

    for _ in range(2):
        with pytest.raises(Exception):
            jobs._ingest_with_circuit(existing_source)

    row = next(
        r
        for r in source_stats(existing_source.user_hash, days=7)["hosts"]
        if r["host"] == "example.com"
    )

    assert row["failures"] == 2
    assert row["error_rate"] == pytest.approx(1.0)
    assert row["in_cooldown"] is True
    assert "HTTP 404" in row["last_error"]
