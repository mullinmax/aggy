"""The tasks endpoint: what the page gets, and what it must never get."""

import pytest

from db.task_run import (
    KIND_DUPLICATE_DETECTION,
    KIND_FEED_TRAINING,
    KIND_IMAGE_EMBED_BACKFILL,
    KIND_SOURCE_INGEST,
    KIND_SOURCE_RESCRAPE,
    start_run,
    task_run,
)
from ingest.jobs import ALL_SOURCES_TARGET
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


# ---------- running a task on request ----------


def _run(client, token, task):
    args = build_api_request_args(path=f"/tasks/run/{task}", token=token)
    return client.post(**args)


@pytest.fixture
def no_real_jobs(monkeypatch):
    """Record what a trigger queued instead of running it.

    The test client runs background tasks for real once the response is sent,
    and these are the jobs that talk to every image host and source site the
    account has.
    """
    queued = []
    for name in (
        "backfill_image_embeddings_job",
        "duplicate_detection_job",
        "ingest_user_sources",
        "rescrape_user_sources",
    ):
        monkeypatch.setattr(
            f"routers.task.{name}",
            lambda *args, _name=name: queued.append(_name),
        )
    yield queued


def _failed_image_item(feed, url):
    from db.base import get_db_con
    from db.item import ItemLoose

    item = ItemLoose(
        url=url,
        title="Title",
        domain="example.com",
        excerpt="Excerpt",
        content="<p>Body</p>",
        image_url="//cdn.example.com/a.jpg",
    )
    item.create(overwrite=True)
    feed.add_items(item)
    with get_db_con() as cur:
        cur.execute(
            "UPDATE items SET image_embed_attempts = 5, image_embed_failed_at = NOW(), "
            "image_embed_error = 'UnsupportedProtocol' WHERE url_hash = %s",
            (item.url_hash,),
        )
    return item


@pytest.fixture
def image_embed_service_configured():
    from config import config

    config.config["IMAGE_EMBED_HOST"] = "image-embed"
    yield
    config.config.pop("IMAGE_EMBED_HOST", None)


def test_retrying_images_clears_the_failures_and_queues_the_pass(
    client,
    existing_user,
    existing_feed,
    token,
    no_real_jobs,
    image_embed_service_configured,
):
    """The point of the button: an item that burned through its attempts is
    stuck for good until something clears them, however fixable its picture."""
    from db.base import get_db_con

    item = _failed_image_item(existing_feed, "https://example.com/stuck")

    body = _run(client, token, "image_embed_retry").json()

    assert body["started"] is True
    assert "1 item" in body["detail"]
    assert no_real_jobs == ["backfill_image_embeddings_job"]
    with get_db_con() as cur:
        cur.execute(
            "SELECT image_embed_attempts, image_embed_error FROM items "
            "WHERE url_hash = %s",
            (item.url_hash,),
        )
        row = cur.fetchone()
    assert row["image_embed_attempts"] == 0
    assert row["image_embed_error"] is None


def test_retrying_images_leaves_pictures_the_host_says_are_gone(
    client,
    existing_user,
    existing_feed,
    token,
    no_real_jobs,
    image_embed_service_configured,
):
    """Re-queueing those is a request made to be told the same thing, several
    thousand times over -- and the answer says so rather than silently
    skipping them."""
    from db.base import get_db_con

    item = _failed_image_item(existing_feed, "https://example.com/gone")
    with get_db_con() as cur:
        cur.execute(
            "UPDATE items SET image_gone_at = NOW() WHERE url_hash = %s",
            (item.url_hash,),
        )

    body = _run(client, token, "image_embed_retry").json()

    assert body["started"] is True
    assert "1 more will not be retried" in body["detail"]
    with get_db_con() as cur:
        cur.execute(
            "SELECT image_embed_attempts FROM items WHERE url_hash = %s",
            (item.url_hash,),
        )
        assert cur.fetchone()["image_embed_attempts"] == 5


def test_a_pass_already_running_is_not_started_twice(
    client,
    existing_user,
    existing_feed,
    token,
    no_real_jobs,
    image_embed_service_configured,
):
    """Two passes over one queue is duplicated work, and a button that claimed
    to have started one anyway would have you pressing it again."""
    from db.base import get_db_con

    item = _failed_image_item(existing_feed, "https://example.com/stuck")
    start_run(KIND_IMAGE_EMBED_BACKFILL)

    body = _run(client, token, "image_embed_retry").json()

    assert body["started"] is False
    assert "already running" in body["detail"]
    assert no_real_jobs == []
    # and the failures it would have cleared are left alone
    with get_db_con() as cur:
        cur.execute(
            "SELECT image_embed_attempts FROM items WHERE url_hash = %s",
            (item.url_hash,),
        )
        assert cur.fetchone()["image_embed_attempts"] == 5


def test_a_scheduled_source_ingest_does_not_block_a_manual_sweep(
    client, existing_user, token, no_real_jobs
):
    """The scheduler is ingesting a source somewhere almost all the time; only
    another sweep of the whole account is a reason to refuse this one."""
    start_run(KIND_SOURCE_INGEST, existing_user.name_hash, "Some source")

    assert _run(client, token, "ingest_sources").json()["started"] is True
    assert no_real_jobs == ["ingest_user_sources"]


def test_a_manual_sweep_already_running_is_refused(
    client, existing_user, token, no_real_jobs
):
    start_run(KIND_SOURCE_INGEST, existing_user.name_hash, ALL_SOURCES_TARGET)

    assert _run(client, token, "ingest_sources").json()["started"] is False
    assert no_real_jobs == []


def test_another_account_s_sweep_does_not_block_yours(
    client, existing_user, token, no_real_jobs
):
    other = User(name="somebody-else")
    other.set_password("password")
    other.create()
    start_run(KIND_SOURCE_INGEST, other.name_hash, ALL_SOURCES_TARGET)

    assert _run(client, token, "ingest_sources").json()["started"] is True


def test_retrying_images_says_so_when_there_is_no_embedder(
    client, existing_user, existing_feed, token, no_real_jobs
):
    """Without the service the backfill does nothing at all, so queueing it
    would be a button reporting work it knows will not happen."""
    _failed_image_item(existing_feed, "https://example.com/stuck")

    body = _run(client, token, "image_embed_retry").json()

    assert body["started"] is False
    assert "not configured" in body["detail"]
    assert no_real_jobs == []


def test_each_trigger_reports_the_kind_it_produces(
    client, existing_user, token, no_real_jobs, image_embed_service_configured
):
    """The page filters its timeline by kind, so a trigger that named the wrong
    one would send you looking for a bar that is in another lane."""
    expected = {
        "image_embed_retry": KIND_IMAGE_EMBED_BACKFILL,
        "duplicate_detection": KIND_DUPLICATE_DETECTION,
        "ingest_sources": KIND_SOURCE_INGEST,
        "rescrape_sources": KIND_SOURCE_RESCRAPE,
    }
    for task, kind in expected.items():
        body = _run(client, token, task).json()
        assert body["task"] == task
        assert body["kind"] == kind
        assert body["started"] is True

    assert sorted(no_real_jobs) == sorted(
        [
            "backfill_image_embeddings_job",
            "duplicate_detection_job",
            "ingest_user_sources",
            "rescrape_user_sources",
        ]
    )


def test_an_unknown_task_is_rejected(client, existing_user, token):
    assert _run(client, token, "rm_rf_slash").status_code == 404


def test_running_a_task_needs_a_token(client, existing_user):
    args = build_api_request_args(path="/tasks/run/image_embed_retry")
    assert client.post(**args).status_code == 401
