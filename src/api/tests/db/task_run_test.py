"""Recording what the background jobs did, and reading it back.

The page these feed answers two questions a log cannot: how often does a task
run, and how long does it take. That needs both ends of every pass, which is
what these cover -- plus the rule that bookkeeping never breaks the work it is
describing.
"""

import time

import pytest

from db.base import get_db_con
from db.task_run import (
    KIND_DUPLICATE_DETECTION,
    KIND_FEED_TRAINING,
    KIND_SOURCE_INGEST,
    STATUS_ERROR,
    STATUS_OK,
    STATUS_RUNNING,
    abandon_running_runs,
    finish_run,
    prune_runs,
    recent_runs,
    run_summary,
    set_run_target,
    start_run,
    task_run,
)


def _row(run_id):
    with get_db_con() as cur:
        cur.execute("SELECT * FROM task_runs WHERE id = %s", (run_id,))
        return cur.fetchone()


def test_a_run_records_both_ends(existing_user):
    run_id = start_run(KIND_FEED_TRAINING, existing_user.name_hash, "My Feed")
    opened = _row(run_id)
    assert opened["status"] == STATUS_RUNNING
    assert opened["started_at"] is not None
    assert opened["finished_at"] is None  # a bar with no end yet

    finish_run(run_id, STATUS_OK, "4 models, chose knn")
    closed = _row(run_id)
    assert closed["status"] == STATUS_OK
    assert closed["finished_at"] >= closed["started_at"]
    assert closed["detail"] == "4 models, chose knn"


def test_the_context_manager_closes_a_run(existing_user):
    with task_run(KIND_FEED_TRAINING, existing_user.name_hash, "My Feed") as run:
        run.detail = "did the thing"

    rows = recent_runs(existing_user.name_hash)
    assert [r["status"] for r in rows] == [STATUS_OK]
    assert rows[0]["detail"] == "did the thing"


def test_a_failing_block_is_recorded_and_re_raised(existing_user):
    """This observes the work, it does not handle it: the exception still goes
    to whoever was going to deal with it."""
    with pytest.raises(ValueError, match="the site fell over"):
        with task_run(KIND_SOURCE_INGEST, existing_user.name_hash, "A source"):
            raise ValueError("the site fell over")

    rows = recent_runs(existing_user.name_hash)
    assert rows[0]["status"] == STATUS_ERROR
    assert "the site fell over" in rows[0]["detail"]


def test_bookkeeping_never_breaks_the_work(existing_user, monkeypatch):
    """A run that could not be recorded must not stop the pass. start_run
    returns None and everything downstream takes that in its stride."""

    def unavailable(*args, **kwargs):
        raise RuntimeError("database went away")

    monkeypatch.setattr("db.task_run.get_db_con", unavailable)

    assert start_run(KIND_FEED_TRAINING, existing_user.name_hash) is None
    finish_run(None, STATUS_OK, "ignored")  # a no-op, not an error
    set_run_target(None, "ignored")

    did_the_work = []
    with task_run(KIND_FEED_TRAINING, existing_user.name_hash, "My Feed"):
        did_the_work.append(True)
    assert did_the_work == [True]


def test_a_target_can_be_named_after_the_run_starts(existing_user):
    """The ingest job picks its source by hash and learns the name when it
    reads it, so the lane is named while the pass is still running."""
    run_id = start_run(KIND_SOURCE_INGEST, existing_user.name_hash)
    assert _row(run_id)["target"] is None

    set_run_target(run_id, "Hacker News")
    assert _row(run_id)["target"] == "Hacker News"


def test_a_system_run_is_owned_by_nobody_and_seen_by_everybody(existing_user):
    """Duplicate detection works a global queue, so claiming it as one
    account's work would be a lie -- but every account should still see it."""
    from db.user import User

    other = User(name="somebody-else")
    other.set_password("password")
    other.create()

    with task_run(KIND_DUPLICATE_DETECTION) as run:
        run.detail = "500 examined"

    for user in (existing_user, other):
        rows = recent_runs(user.name_hash)
        assert [r["kind"] for r in rows] == [KIND_DUPLICATE_DETECTION]
        assert rows[0]["system_wide"] is True


def test_another_account_s_runs_are_not_visible(existing_user):
    from db.user import User

    other = User(name="somebody-else")
    other.set_password("password")
    other.create()
    with task_run(KIND_FEED_TRAINING, other.name_hash, "Their Feed"):
        pass

    assert recent_runs(existing_user.name_hash) == []


def test_a_running_pass_has_a_duration_measured_to_now(existing_user):
    """A live bar has to have a length, or it cannot be drawn."""
    start_run(KIND_FEED_TRAINING, existing_user.name_hash, "My Feed")
    time.sleep(0.05)

    row = recent_runs(existing_user.name_hash)[0]
    assert row["finished_at"] is None
    assert row["duration_seconds"] > 0


def test_filters_are_applied_in_sql(existing_user):
    with task_run(KIND_FEED_TRAINING, existing_user.name_hash, "My Feed"):
        pass
    with pytest.raises(ValueError):
        with task_run(KIND_SOURCE_INGEST, existing_user.name_hash, "A source"):
            raise ValueError("boom")

    by_kind = recent_runs(existing_user.name_hash, kinds=[KIND_FEED_TRAINING])
    assert [r["kind"] for r in by_kind] == [KIND_FEED_TRAINING]

    by_status = recent_runs(existing_user.name_hash, statuses=[STATUS_ERROR])
    assert [r["kind"] for r in by_status] == [KIND_SOURCE_INGEST]


def test_a_restart_closes_the_runs_it_interrupted(existing_user):
    """A row still marked running belongs to a process that is gone. Left
    alone the page would show a pass going since before the restart."""
    run_id = start_run(KIND_FEED_TRAINING, existing_user.name_hash, "My Feed")

    assert abandon_running_runs() == 1

    row = _row(run_id)
    assert row["status"] == STATUS_ERROR
    assert row["finished_at"] is not None
    assert "interrupted" in row["detail"]


def test_abandoning_keeps_a_detail_the_run_already_had(existing_user):
    run_id = start_run(KIND_FEED_TRAINING, existing_user.name_hash, "My Feed")
    with get_db_con() as cur:
        cur.execute(
            "UPDATE task_runs SET detail = %s WHERE id = %s", ("halfway", run_id)
        )

    abandon_running_runs()

    assert _row(run_id)["detail"] == "halfway"


def test_old_runs_are_pruned(existing_user):
    keep = start_run(KIND_FEED_TRAINING, existing_user.name_hash, "Recent")
    drop = start_run(KIND_FEED_TRAINING, existing_user.name_hash, "Ancient")
    with get_db_con() as cur:
        cur.execute(
            "UPDATE task_runs SET started_at = NOW() - INTERVAL '40 days' "
            "WHERE id = %s",
            (drop,),
        )

    assert prune_runs(days=7) == 1
    assert _row(drop) is None
    assert _row(keep) is not None


def test_the_summary_reports_per_kind_totals(existing_user):
    for _ in range(3):
        with task_run(KIND_FEED_TRAINING, existing_user.name_hash, "My Feed"):
            pass
    with pytest.raises(ValueError):
        with task_run(KIND_FEED_TRAINING, existing_user.name_hash, "My Feed"):
            raise ValueError("boom")
    start_run(KIND_SOURCE_INGEST, existing_user.name_hash, "A source")

    summary = run_summary(existing_user.name_hash)
    by_kind = {row["kind"]: row for row in summary["kinds"]}

    assert by_kind[KIND_FEED_TRAINING]["runs"] == 4
    assert by_kind[KIND_FEED_TRAINING]["errors"] == 1
    assert by_kind[KIND_FEED_TRAINING]["median_seconds"] is not None
    assert by_kind[KIND_SOURCE_INGEST]["running"] == 1
    # a pass still in flight has no duration to take a median of
    assert by_kind[KIND_SOURCE_INGEST]["median_seconds"] is None
    assert summary["total_runs"] == 5
    assert summary["total_errors"] == 1
    assert summary["total_running"] == 1


def test_a_long_detail_is_trimmed_to_fit_a_table_cell(existing_user):
    run_id = start_run(KIND_SOURCE_INGEST, existing_user.name_hash, "A source")
    finish_run(run_id, STATUS_ERROR, "x" * 5000)

    detail = _row(run_id)["detail"]
    assert len(detail) < 400
    assert detail.endswith("…")
