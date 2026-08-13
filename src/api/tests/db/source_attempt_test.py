import pytest

from db.base import get_db_con
from db.source_attempt import (
    OUTCOME_ERROR,
    OUTCOME_OK,
    OUTCOME_SKIPPED,
    prune_attempts,
    record_attempt,
    source_stats,
)
from ingest import host_circuit


@pytest.fixture(autouse=True)
def clean_attempts_and_circuits(existing_user):
    """Each test starts with an empty history and no open circuits."""
    with get_db_con() as cur:
        cur.execute(
            "DELETE FROM source_ingest_attempts WHERE user_hash = %s",
            (existing_user.name_hash,),
        )
    host_circuit.reset()
    yield
    host_circuit.reset()


def _log(source, host, outcome, error=None):
    record_attempt(
        user_hash=source.user_hash,
        feed_hash=source.feed_hash,
        source_hash=source.name_hash,
        host=host,
        outcome=outcome,
        error=error,
    )


def _age_attempts(user_hash, days):
    with get_db_con() as cur:
        cur.execute(
            "UPDATE source_ingest_attempts "
            "SET attempted_at = NOW() - make_interval(days => %s) "
            "WHERE user_hash = %s",
            (days, user_hash),
        )


def test_error_rate_is_failures_over_contacted_attempts(existing_source):
    for _ in range(3):
        _log(existing_source, "youtube.com", OUTCOME_ERROR, "HTTP 404")
    _log(existing_source, "youtube.com", OUTCOME_OK)

    stats = source_stats(existing_source.user_hash, days=7)
    row = next(r for r in stats["hosts"] if r["host"] == "youtube.com")

    assert row["attempts"] == 4
    assert row["failures"] == 3
    assert row["successes"] == 1
    assert row["error_rate"] == pytest.approx(0.75)


def test_skips_are_excluded_from_the_error_rate(existing_source):
    """A skip is the breaker working, not a fresh failure. Counting skips as
    attempts would make a site look worse the better we were at avoiding it —
    and counting them as successes would hide the outage entirely."""
    _log(existing_source, "youtube.com", OUTCOME_ERROR, "HTTP 404")
    _log(existing_source, "youtube.com", OUTCOME_OK)
    for _ in range(50):
        _log(existing_source, "youtube.com", OUTCOME_SKIPPED)

    row = next(
        r
        for r in source_stats(existing_source.user_hash, days=7)["hosts"]
        if r["host"] == "youtube.com"
    )

    assert row["attempts"] == 2
    assert row["skipped"] == 50
    assert row["error_rate"] == pytest.approx(0.5)


def test_a_host_that_was_only_skipped_has_no_error_rate(existing_source):
    """Reporting 0% would read as healthy, which is the opposite of the truth
    when the only reason nothing failed is that nothing was attempted."""
    for _ in range(5):
        _log(existing_source, "youtube.com", OUTCOME_SKIPPED)

    row = next(
        r
        for r in source_stats(existing_source.user_hash, days=7)["hosts"]
        if r["host"] == "youtube.com"
    )

    assert row["attempts"] == 0
    assert row["error_rate"] is None


def test_the_most_recent_error_is_kept(existing_source):
    _log(existing_source, "youtube.com", OUTCOME_ERROR, "older failure")
    _log(existing_source, "youtube.com", OUTCOME_ERROR, "newest failure")

    row = next(
        r
        for r in source_stats(existing_source.user_hash, days=7)["hosts"]
        if r["host"] == "youtube.com"
    )

    assert row["last_error"] == "newest failure"
    assert row["last_failure_at"] is not None
    assert row["last_success_at"] is None


def test_hosts_are_sorted_worst_first(existing_source):
    _log(existing_source, "healthy.com", OUTCOME_OK)
    _log(existing_source, "healthy.com", OUTCOME_OK)
    _log(existing_source, "broken.com", OUTCOME_ERROR, "boom")
    _log(existing_source, "broken.com", OUTCOME_ERROR, "boom")

    hosts = [r["host"] for r in source_stats(existing_source.user_hash, days=7)["hosts"]]

    assert hosts.index("broken.com") < hosts.index("healthy.com")


def test_an_open_circuit_shows_as_a_cooldown_on_the_row(existing_source):
    """The page has to distinguish "failing" from "currently paused", because
    a paused site stops producing failures and would otherwise look recovered."""
    _log(existing_source, "youtube.com", OUTCOME_ERROR, "HTTP 404")
    for _ in range(config_threshold()):
        host_circuit.record_failure("https://www.youtube.com/feeds/videos.xml")

    row = next(
        r
        for r in source_stats(existing_source.user_hash, days=7)["hosts"]
        if r["host"] == "youtube.com"
    )

    assert row["in_cooldown"] is True
    assert row["cooldown_seconds_remaining"] > 0


def config_threshold():
    from config import config

    return config.get_int("HOST_FAILURE_THRESHOLD")


def test_summary_aggregates_across_hosts(existing_source):
    _log(existing_source, "a.com", OUTCOME_ERROR, "boom")
    _log(existing_source, "a.com", OUTCOME_OK)
    _log(existing_source, "b.com", OUTCOME_OK)
    _log(existing_source, "b.com", OUTCOME_SKIPPED)

    summary = source_stats(existing_source.user_hash, days=7)["summary"]

    assert summary["host_count"] == 2
    assert summary["attempts"] == 3
    assert summary["failures"] == 1
    assert summary["skipped"] == 1
    assert summary["error_rate"] == pytest.approx(1 / 3)


def test_timeline_is_zero_filled_across_the_window(existing_source):
    _log(existing_source, "youtube.com", OUTCOME_ERROR, "boom")

    timeline = source_stats(existing_source.user_hash, days=7)["timeline"]

    assert len(timeline) == 8  # the window plus today
    assert timeline[-1]["failures"] == 1
    # quiet days report no rate rather than a spurious 0%
    assert timeline[0]["attempts"] == 0
    assert timeline[0]["error_rate"] is None


def test_attempts_outside_the_window_are_excluded(existing_source):
    _log(existing_source, "youtube.com", OUTCOME_ERROR, "boom")
    _age_attempts(existing_source.user_hash, 30)

    assert source_stats(existing_source.user_hash, days=7)["hosts"] == []


def test_another_users_attempts_are_never_counted(existing_source, existing_user):
    record_attempt(
        user_hash="some-other-user",
        feed_hash=existing_source.feed_hash,
        source_hash=existing_source.name_hash,
        host="youtube.com",
        outcome=OUTCOME_ERROR,
        error="boom",
    )

    assert source_stats(existing_user.name_hash, days=7)["hosts"] == []


def test_pruning_drops_only_aged_out_attempts(existing_source):
    _log(existing_source, "old.com", OUTCOME_OK)
    _age_attempts(existing_source.user_hash, 60)
    _log(existing_source, "fresh.com", OUTCOME_OK)

    prune_attempts(days=30)

    hosts = [r["host"] for r in source_stats(existing_source.user_hash, days=90)["hosts"]]
    assert hosts == ["fresh.com"]


def test_a_long_error_is_truncated_rather_than_stored_whole(existing_source):
    _log(existing_source, "youtube.com", OUTCOME_ERROR, "x" * 5000)

    row = next(
        r
        for r in source_stats(existing_source.user_hash, days=7)["hosts"]
        if r["host"] == "youtube.com"
    )

    assert len(row["last_error"]) <= 500
    assert row["last_error"].endswith("…")


def test_recording_never_raises_on_a_bad_write(existing_source, monkeypatch):
    """Bookkeeping must not be able to turn a good ingest into a failed one."""

    def boom(*args, **kwargs):
        raise RuntimeError("db is down")

    monkeypatch.setattr("db.source_attempt.get_db_con", boom)

    _log(existing_source, "youtube.com", OUTCOME_OK)  # does not raise
