"""The stored experiment queue: fire-and-forget, one at a time, restart-safe,
and a result that says nothing about any particular article."""

import json
import uuid

import pytest
from pydantic import HttpUrl

from db.base import get_db_con
from db.item import ItemLoose
from db.item_open import engagement_summary, record_open, record_seconds
from db.item_state import ItemState
from ranking.engine import chosen_model_name
from ranking.experiments import replay, runner
from tests.testing_utils import build_api_request_args

SECRET_TITLE = "A headline that must never leave the server"
SECRET_AUTHOR = "Private Author"


def _voted_feed(user, feed, n=24):
    """A feed with a taste in it: even articles upvoted, odd ones downvoted,
    and the two kinds far apart in embedding space."""
    items = []
    for index in range(n):
        item = ItemLoose(
            url=HttpUrl(f"http://private-site.example/{uuid.uuid4()}/"),
            title=f"{SECRET_TITLE} {index}",
            author=SECRET_AUTHOR,
            domain="private-site.example",
            excerpt="words",
            content="<p>words</p>",
            embeddings={"test-model": [5.0 if index % 2 == 0 else -5.0, 0.1 * index]},
        )
        item.create()
        feed.add_items(item)
        ItemState.set_state(
            user_hash=user.name_hash,
            feed_hash=feed.name_hash,
            item_url_hash=item.url_hash,
            score=1 if index % 2 == 0 else -1,
            is_read=True,
        )
        items.append(item)
    return items


@pytest.fixture
def fast(monkeypatch):
    """No idling between fits, and no lowered thread priority under test."""
    original = replay.ReplayConfig

    def config(**kwargs):
        kwargs.setdefault("rest_fraction", 0.0)
        return original(**kwargs)

    monkeypatch.setattr(replay, "ReplayConfig", config)
    monkeypatch.setattr(runner, "_lower_priority", lambda: None)


def test_an_experiment_runs_from_the_queue_and_stores_its_result(
    existing_user, existing_feed, fast
):
    _voted_feed(existing_user, existing_feed)
    experiment_id = runner.enqueue(existing_user.name_hash)
    assert (
        runner.get_experiment(existing_user.name_hash, experiment_id)["status"]
        == "queued"
    )

    runner.experiment_job()

    row = runner.get_experiment(existing_user.name_hash, experiment_id)
    assert row["status"] == "done"
    assert row["finished_at"] is not None
    result = row["result"]
    assert result["mode"] == "quick" and result["scope"] == "all feeds"
    methods = {m["method"]: m for m in result["methods"]}
    assert methods["knn_embedding"]["auc"] > 0.9
    assert "taste_profile" in methods and "live_picker" in methods
    assert result["feeds"][0]["feed"] == "Feed 1"
    assert result["feeds"][0]["labels"] == 24


def test_a_result_names_no_article_source_or_feed(existing_user, existing_feed, fast):
    """The result is built to be copied out of the app. Whatever else it
    holds, it must not hold anything that identifies what was read."""
    items = _voted_feed(existing_user, existing_feed)
    experiment_id = runner.enqueue(existing_user.name_hash)
    runner.experiment_job()
    text = json.dumps(
        runner.get_experiment(existing_user.name_hash, experiment_id)["result"]
    )
    assert SECRET_TITLE not in text
    assert SECRET_AUTHOR not in text
    assert "private-site" not in text
    assert existing_feed.name not in text
    assert existing_feed.name_hash not in text
    assert existing_user.name_hash not in text
    assert not any(item.url_hash in text for item in items)


def test_an_experiment_leaves_the_live_ranking_alone(
    existing_user, existing_feed, fast
):
    _voted_feed(existing_user, existing_feed)
    runner.enqueue(existing_user.name_hash)
    runner.experiment_job()
    assert chosen_model_name(existing_feed) is None
    with get_db_con() as cur:
        cur.execute(
            "SELECT COUNT(*) AS n FROM feed_items WHERE predicted_at IS NOT NULL"
        )
        assert cur.fetchone()["n"] == 0


def test_queued_experiments_run_in_the_order_they_were_asked_for(
    existing_user, existing_feed, fast, monkeypatch
):
    _voted_feed(existing_user, existing_feed)
    first = runner.enqueue(existing_user.name_hash)
    second = runner.enqueue(existing_user.name_hash, existing_feed.name_hash)
    order = []
    real = runner.run_experiment

    def spy(experiment_id, *args, **kwargs):
        # while one runs, nothing else may be claimed
        assert runner._claim_next() is None
        order.append(experiment_id)
        return real(experiment_id, *args, **kwargs)

    monkeypatch.setattr(runner, "run_experiment", spy)
    runner.experiment_job()
    assert order == [first, second]
    listed = runner.list_experiments(existing_user.name_hash)
    assert [r["status"] for r in listed] == ["done", "done"]
    assert (
        runner.get_experiment(existing_user.name_hash, second)["result"]["scope"]
        == "one feed"
    )


def test_the_queue_is_capped_per_account(existing_user):
    for _ in range(runner.MAX_OPEN_PER_USER):
        assert runner.enqueue(existing_user.name_hash) is not None
    assert runner.enqueue(existing_user.name_hash) is None


def test_a_restart_puts_a_running_experiment_back_in_the_queue(existing_user):
    experiment_id = runner.enqueue(existing_user.name_hash)
    assert runner._claim_next()["id"] == experiment_id
    assert (
        runner.get_experiment(existing_user.name_hash, experiment_id)["status"]
        == "running"
    )
    assert runner.requeue_interrupted() == 1
    row = runner.get_experiment(existing_user.name_hash, experiment_id)
    assert row["status"] == "queued" and row["started_at"] is None


def test_a_cancelled_experiment_is_never_run(existing_user, existing_feed, fast):
    _voted_feed(existing_user, existing_feed)
    experiment_id = runner.enqueue(existing_user.name_hash)
    assert runner.cancel(existing_user.name_hash, experiment_id)
    runner.experiment_job()
    row = runner.get_experiment(existing_user.name_hash, experiment_id)
    assert row["status"] == "cancelled" and row["result"] is None


def test_cancelling_a_running_experiment_stops_it(
    existing_user, existing_feed, fast, monkeypatch
):
    _voted_feed(existing_user, existing_feed)
    experiment_id = runner.enqueue(existing_user.name_hash)
    monkeypatch.setattr(runner, "_CANCEL_CHECK_SECONDS", 0.0)
    real = replay.replay_feed

    def cancel_then_replay(*args, **kwargs):
        runner.cancel(existing_user.name_hash, experiment_id)
        return real(*args, **kwargs)

    monkeypatch.setattr(replay, "replay_feed", cancel_then_replay)
    runner.experiment_job()
    row = runner.get_experiment(existing_user.name_hash, experiment_id)
    assert row["status"] == "cancelled" and row["result"] is None


def test_a_failing_experiment_is_recorded_and_the_queue_moves_on(
    existing_user, existing_feed, fast, monkeypatch
):
    _voted_feed(existing_user, existing_feed)
    broken = runner.enqueue(existing_user.name_hash)
    fine = runner.enqueue(existing_user.name_hash)
    real = runner.run_experiment

    def sometimes(experiment_id, *args, **kwargs):
        if experiment_id == broken:
            raise RuntimeError("boom")
        return real(experiment_id, *args, **kwargs)

    monkeypatch.setattr(runner, "run_experiment", sometimes)
    runner.experiment_job()
    row = runner.get_experiment(existing_user.name_hash, broken)
    assert row["status"] == "error" and "boom" in row["error"]
    assert runner.get_experiment(existing_user.name_hash, fine)["status"] == "done"


def test_only_a_finished_experiment_can_be_deleted(existing_user):
    experiment_id = runner.enqueue(existing_user.name_hash)
    assert not runner.delete(existing_user.name_hash, experiment_id)
    runner.cancel(existing_user.name_hash, experiment_id)
    assert runner.delete(existing_user.name_hash, experiment_id)
    assert runner.get_experiment(existing_user.name_hash, experiment_id) is None


def test_a_feed_with_few_votes_is_reported_as_skipped(
    existing_user, existing_feed, fast
):
    _voted_feed(existing_user, existing_feed, n=6)
    experiment_id = runner.enqueue(existing_user.name_hash)
    runner.experiment_job()
    result = runner.get_experiment(existing_user.name_hash, experiment_id)["result"]
    assert result["methods"] == []
    assert result["feeds"][0]["skipped"]


# --- opens -----------------------------------------------------------------


def test_engagement_relates_opens_to_votes_without_naming_anything(
    existing_user, existing_feed
):
    items = _voted_feed(existing_user, existing_feed, n=4)
    user, feed = existing_user.name_hash, existing_feed.name_hash
    long_read = record_open(user, feed, items[0].url_hash, "reader")  # upvoted
    record_seconds(user, long_read, 200)
    glance = record_open(user, feed, items[1].url_hash, "reader")  # downvoted
    record_seconds(user, glance, 2)
    record_open(user, feed, items[2].url_hash, "link")  # upvoted

    summary = engagement_summary(user)
    assert summary["opens_recorded"] == 3
    assert summary["by_surface"]["reader"]["opens"] == 2
    assert summary["by_surface"]["link"]["upvoted"] == 1
    assert summary["by_reading_time"]["over_2m"]["upvoted"] == 1
    assert summary["by_reading_time"]["under_5s"]["downvoted"] == 1
    assert SECRET_TITLE not in json.dumps(summary)


def test_the_longest_reported_reading_time_is_kept(existing_user, existing_feed):
    items = _voted_feed(existing_user, existing_feed, n=1)
    user = existing_user.name_hash
    open_id = record_open(user, existing_feed.name_hash, items[0].url_hash, "reader")
    assert record_seconds(user, open_id, 40)
    assert record_seconds(user, open_id, 12)  # a late, stale report
    with get_db_con() as cur:
        cur.execute("SELECT seconds FROM item_opens WHERE id = %s", (open_id,))
        assert cur.fetchone()["seconds"] == 40
    assert not record_seconds("someone-else", open_id, 99)


# --- endpoints -------------------------------------------------------------


def _call(client, token, method, path, **params):
    args = build_api_request_args(path=path, params=params, token=token)
    return getattr(client, method)(**args)


def test_experiment_endpoints_round_trip(
    client, token, existing_user, existing_feed, fast
):
    _voted_feed(existing_user, existing_feed)
    started = _call(client, token, "post", "/experiments/start", mode="quick")
    assert started.status_code == 200
    body = started.json()
    assert body["status"] == "queued" and body["result"] is None
    experiment_id = body["experiment_id"]

    listed = _call(client, token, "get", "/experiments/list").json()["experiments"]
    assert [e["experiment_id"] for e in listed] == [experiment_id]
    assert listed[0]["has_result"] is False

    runner.experiment_job()

    listed = _call(client, token, "get", "/experiments/list").json()["experiments"]
    assert listed[0]["status"] == "done" and listed[0]["has_result"] is True
    assert listed[0]["result"] is None  # the list stays light

    got = _call(client, token, "get", "/experiments/get", experiment_id=experiment_id)
    assert got.json()["result"]["methods"]

    assert (
        _call(
            client, token, "post", "/experiments/cancel", experiment_id=experiment_id
        ).status_code
        == 404
    )
    assert (
        _call(
            client, token, "post", "/experiments/delete", experiment_id=experiment_id
        ).status_code
        == 200
    )
    assert (
        _call(
            client, token, "get", "/experiments/get", experiment_id=experiment_id
        ).status_code
        == 404
    )


def test_starting_an_experiment_validates_its_arguments(client, token, existing_feed):
    assert (
        _call(client, token, "post", "/experiments/start", mode="thorough").status_code
        == 422
    )
    assert (
        _call(
            client, token, "post", "/experiments/start", feed_name_hash="nope"
        ).status_code
        == 404
    )
    assert _call(client, token, "post", "/experiments/start").status_code == 200
    assert _call(client, None, "post", "/experiments/start").status_code == 401


def test_a_full_queue_is_refused(client, token, existing_user):
    for _ in range(runner.MAX_OPEN_PER_USER):
        runner.enqueue(existing_user.name_hash)
    assert _call(client, token, "post", "/experiments/start").status_code == 429


def test_opens_are_recorded_through_the_api(
    client, token, existing_user, existing_feed
):
    item = _voted_feed(existing_user, existing_feed, n=1)[0]
    feed = existing_feed.name_hash
    opened = _call(
        client,
        token,
        "post",
        "/item/opened",
        feed_hash=feed,
        item_url_hash=item.url_hash,
    )
    assert opened.status_code == 200
    open_id = opened.json()["open_id"]
    assert (
        _call(
            client, token, "post", "/item/open_seconds", open_id=open_id, seconds=31.5
        ).status_code
        == 200
    )
    assert (
        _call(
            client,
            token,
            "post",
            "/item/open_seconds",
            open_id=open_id + 999,
            seconds=1,
        ).status_code
        == 404
    )
    assert (
        _call(
            client, token, "post", "/item/open_seconds", open_id=open_id, seconds=-1
        ).status_code
        == 422
    )
    assert (
        _call(
            client,
            token,
            "post",
            "/item/opened",
            feed_hash=feed,
            item_url_hash=item.url_hash,
            surface="telepathy",
        ).status_code
        == 422
    )
    assert (
        _call(
            client,
            token,
            "post",
            "/item/opened",
            feed_hash="nope",
            item_url_hash=item.url_hash,
        ).status_code
        == 404
    )
    assert (
        _call(
            client, token, "post", "/item/opened", feed_hash=feed, item_url_hash="nope"
        ).status_code
        == 404
    )
    assert engagement_summary(existing_user.name_hash)["opens_recorded"] == 1
