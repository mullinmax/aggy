"""The tasks endpoint: what the page gets, and what it must never get."""

import pytest

from db.task_run import (
    KIND_DUPLICATE_DETECTION,
    KIND_FEED_TRAINING,
    KIND_SOURCE_INGEST,
    start_run,
    task_run,
)
from db.user import User
from tests.testing_utils import build_api_request_args


def _get(client, token, **params):
    args = build_api_request_args(path="/tasks/runs", params=params, token=token)
    return client.get(**args)


def test_runs_are_returned_with_durations(client, existing_user, token):
    with task_run(KIND_FEED_TRAINING, existing_user.name_hash, "My Feed") as run:
        run.detail = "chose knn"

    body = _get(client, token).json()

    assert body["total_runs"] == 1
    assert body["total_errors"] == 0
    run_row = body["runs"][0]
    assert run_row["kind"] == KIND_FEED_TRAINING
    assert run_row["target"] == "My Feed"
    assert run_row["status"] == "ok"
    assert run_row["detail"] == "chose knn"
    assert run_row["duration_seconds"] >= 0
    assert run_row["system_wide"] is False
    # the window is echoed back so the timeline can scale its axis without
    # guessing from whichever rows it happened to receive
    assert body["hours"] == 24
    assert body["window_start"] < body["window_end"]


def test_a_system_run_is_labelled_rather_than_claimed(client, existing_user, token):
    with task_run(KIND_DUPLICATE_DETECTION) as run:
        run.detail = "500 examined"

    body = _get(client, token).json()

    assert body["runs"][0]["system_wide"] is True
    assert body["runs"][0]["target"] is None
    assert body["kinds"][0]["system_wide"] is True


def test_another_account_s_runs_are_never_returned(client, existing_user, token):
    other = User(name="somebody-else")
    other.set_password("password")
    other.create()
    with task_run(KIND_FEED_TRAINING, other.name_hash, "Their Feed"):
        pass

    body = _get(client, token).json()

    assert body["runs"] == []
    assert body["total_runs"] == 0


def test_a_running_pass_is_reported_as_running(client, existing_user, token):
    start_run(KIND_SOURCE_INGEST, existing_user.name_hash, "A source")

    body = _get(client, token).json()

    assert body["total_running"] == 1
    assert body["runs"][0]["status"] == "running"
    assert body["runs"][0]["finished_at"] is None


def test_filters_narrow_the_rows(client, existing_user, token):
    with task_run(KIND_FEED_TRAINING, existing_user.name_hash, "My Feed"):
        pass
    with pytest.raises(ValueError):
        with task_run(KIND_SOURCE_INGEST, existing_user.name_hash, "A source"):
            raise ValueError("boom")

    by_kind = _get(client, token, kinds=KIND_FEED_TRAINING).json()
    assert [r["kind"] for r in by_kind["runs"]] == [KIND_FEED_TRAINING]

    by_status = _get(client, token, statuses="error").json()
    assert [r["kind"] for r in by_status["runs"]] == [KIND_SOURCE_INGEST]

    # the summary is computed over the whole window regardless of the filter,
    # so the counts stay true when the timeline is narrowed
    assert by_kind["total_runs"] == 2


def test_an_unknown_filter_is_rejected_rather_than_silently_empty(
    client, existing_user, token
):
    """A typo'd filter returning nothing looks exactly like a quiet period,
    which is the one thing this page must not get wrong."""
    assert _get(client, token, kinds="not_a_task").status_code == 422
    assert _get(client, token, statuses="not_a_status").status_code == 422


def test_the_window_is_bounded(client, existing_user, token):
    assert _get(client, token, hours=0).status_code == 422
    assert _get(client, token, hours=24 * 365).status_code == 422
    assert _get(client, token, hours=1).status_code == 200


def test_runs_outside_the_window_are_excluded(client, existing_user, token):
    from db.base import get_db_con

    with task_run(KIND_FEED_TRAINING, existing_user.name_hash, "Old"):
        pass
    with get_db_con() as cur:
        cur.execute("UPDATE task_runs SET started_at = NOW() - INTERVAL '5 days'")

    assert _get(client, token, hours=1).json()["runs"] == []
    assert len(_get(client, token, hours=24 * 7).json()["runs"]) == 1


def test_the_endpoint_needs_a_token(client, existing_user):
    args = build_api_request_args(path="/tasks/runs", params={})
    assert client.get(**args).status_code == 401
