"""What the ingest job writes to the log when a source fails.

Ingest talks to the open web every fifteen seconds, so the difference between
"a site was down" and "we have a bug" has to be visible at a glance. An
expected failure is one line; anything else keeps its traceback.
"""

import logging

from ingest import jobs
from ingest.errors import IngestError


def _run_ingest(monkeypatch, source, failure):
    """Run one pass of the ingest job against a source that fails."""

    def boom(source):
        raise failure

    monkeypatch.setattr(jobs, "ingest_source", boom)
    jobs.source_ingestion_job()


def test_expected_failure_is_one_line_without_a_traceback(
    monkeypatch, caplog, existing_source
):
    existing_source.trigger_ingest(now=True)
    with caplog.at_level(logging.INFO):
        _run_ingest(
            monkeypatch, existing_source, IngestError("Feed returned no entries")
        )

    failures = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(failures) == 1
    record = failures[0]
    assert record.levelno == logging.WARNING
    assert record.exc_info is None  # no stack trace
    # named by what a person recognises, not by its hash
    assert existing_source.name in record.message
    assert "Feed returned no entries" in record.message


def test_unexpected_failure_keeps_its_traceback(monkeypatch, caplog, existing_source):
    existing_source.trigger_ingest(now=True)
    with caplog.at_level(logging.INFO):
        _run_ingest(monkeypatch, existing_source, KeyError("title"))

    failures = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(failures) == 1
    assert failures[0].exc_info is not None


def test_the_failure_reason_is_stored_on_the_source(
    monkeypatch, caplog, existing_source
):
    """Whichever way it failed, the source carries the reason so the UI can
    show it beside the source."""
    existing_source.trigger_ingest(now=True)
    with caplog.at_level(logging.INFO):
        _run_ingest(
            monkeypatch, existing_source, IngestError("Feed returned no entries")
        )

    from db.base import get_db_con

    with get_db_con() as cur:
        cur.execute(
            "SELECT last_ingest_error FROM sources "
            "WHERE user_hash = %s AND feed_hash = %s AND name_hash = %s",
            (
                existing_source.user_hash,
                existing_source.feed_hash,
                existing_source.name_hash,
            ),
        )
        assert cur.fetchone()["last_ingest_error"] == "Feed returned no entries"
