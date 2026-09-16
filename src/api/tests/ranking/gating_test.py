"""The training gate: a full retrain costs the whole model bake-off, so it
only happens when the votes it learns from actually changed.

Ingesting an article used to make a feed eligible for that run, which meant a
feed whose sources pulled anything paid for cross-validating every model to
learn from exactly the votes it had already learned from. New articles now take
the cheap path instead: the already-chosen model is re-fit and applied to the
rows that have never been scored.
"""

import uuid

from pydantic import HttpUrl

from db.item import ItemLoose
from db.item_state import ItemState
from ranking import engine, progress
from ranking.engine import (
    MIN_LABELS_TO_RANK,
    chosen_model_name,
    feed_ranking_job,
    feeds_needing_scoring,
    feeds_needing_training,
    score_feed,
)
from tests.testing_utils import build_api_request_args


def _add_item(feed, url, embedding=None):
    item = ItemLoose(
        url=HttpUrl(url),
        title="Title",
        author="Someone",
        domain="example.com",
        excerpt="words",
        content="<p>words</p>",
        embeddings={"test-model": embedding} if embedding else None,
    )
    item.create()
    feed.add_items(item)
    return item


def _vote(user, feed, item, score):
    ItemState.set_state(
        user_hash=user.name_hash,
        feed_hash=feed.name_hash,
        item_url_hash=item.url_hash,
        score=score,
        is_read=True,
    )


def _trained_feed(user, feed, n_labels=4):
    """A feed that has been through a full training run, so it carries model
    stats, a chosen model and a prediction on every article."""
    items = [
        _add_item(
            feed,
            f"http://example.com/{uuid.uuid4()}/",
            embedding=[5.0 if i % 2 == 0 else -5.0, 0.1 * i],
        )
        for i in range(n_labels)
    ]
    for i, item in enumerate(items):
        _vote(user, feed, item, 1.0 if i % 2 == 0 else -1.0)
    engine.rank_feed(feed)
    progress.reset()
    return items


def _stats_computed_at(feed):
    with engine.get_db_con() as cur:
        cur.execute(
            "SELECT MAX(computed_at) AS at FROM ranking_model_stats "
            "WHERE user_hash = %s AND feed_hash = %s",
            (feed.user_hash, feed.name_hash),
        )
        return cur.fetchone()["at"]


def _prediction(feed, item):
    with engine.get_db_con() as cur:
        cur.execute(
            "SELECT predicted_score, predicted_at FROM feed_items "
            "WHERE user_hash = %s AND feed_hash = %s AND item_url_hash = %s",
            (feed.user_hash, feed.name_hash, item.url_hash),
        )
        return cur.fetchone()


def test_new_articles_are_scored_without_retraining(existing_user, existing_feed):
    """The core of the gate: an ingest tick that adds articles to a feed with
    no new votes must not rebuild the models, and the new articles must still
    come back ranked."""
    _trained_feed(existing_user, existing_feed)
    trained_at = _stats_computed_at(existing_feed)
    assert trained_at is not None

    fresh = _add_item(
        existing_feed, f"http://example.com/{uuid.uuid4()}/", embedding=[1.0, 0.5]
    )
    assert _prediction(existing_feed, fresh)["predicted_score"] is None

    # no new votes, so the feed is not due for training -- only for scoring
    assert existing_feed.name not in {f.name for f in feeds_needing_training()}
    assert existing_feed.name in {f.name for f in feeds_needing_scoring()}

    feed_ranking_job()

    assert _stats_computed_at(existing_feed) == trained_at
    assert _prediction(existing_feed, fresh)["predicted_score"] is not None


def test_ingesting_articles_never_cross_validates(
    existing_user, existing_feed, monkeypatch
):
    """The acceptance criterion, asserted directly: the expensive part of a
    retrain is `evaluate_models`, and a feed with no new votes must not reach
    it however many articles arrive."""
    _trained_feed(existing_user, existing_feed)
    for _ in range(3):
        _add_item(
            existing_feed, f"http://example.com/{uuid.uuid4()}/", embedding=[1.0, 0.5]
        )

    def fail(*args, **kwargs):
        raise AssertionError("evaluate_models ran for a feed with no new votes")

    monkeypatch.setattr(engine, "evaluate_models", fail)
    feed_ranking_job()


def test_a_new_vote_retrains(existing_user, existing_feed):
    """A vote is new evidence, so it does rebuild the models."""
    _trained_feed(existing_user, existing_feed)
    trained_at = _stats_computed_at(existing_feed)

    extra = _add_item(
        existing_feed, f"http://example.com/{uuid.uuid4()}/", embedding=[4.0, 0.2]
    )
    _vote(existing_user, existing_feed, extra, 1.0)

    assert existing_feed.name in {f.name for f in feeds_needing_training()}
    feed_ranking_job()

    assert _stats_computed_at(existing_feed) > trained_at


def test_listing_an_article_retrains(existing_user, existing_feed, existing_list):
    """A list add counts as a vote, so it is new evidence too."""
    _trained_feed(existing_user, existing_feed)
    trained_at = _stats_computed_at(existing_feed)

    listed = _add_item(
        existing_feed, f"http://example.com/{uuid.uuid4()}/", embedding=[4.0, 0.2]
    )
    existing_list.add_item(listed.url_hash)

    assert existing_feed.name in {f.name for f in feeds_needing_training()}
    feed_ranking_job()

    assert _stats_computed_at(existing_feed) > trained_at


def test_manual_rerank_retrains_with_no_new_votes(
    client, existing_user, existing_feed, token
):
    """The gate is for the scheduler. Asking for a retrain still gets one --
    that is now the point of the endpoint."""
    _trained_feed(existing_user, existing_feed)
    trained_at = _stats_computed_at(existing_feed)
    assert existing_feed.name not in {f.name for f in feeds_needing_training()}

    args = build_api_request_args(
        path="/feed/rerank",
        params={"feed_name_hash": existing_feed.name_hash},
        token=token,
    )
    response = client.post(**args)

    assert response.status_code == 200
    # the endpoint runs the retrain on a background thread; it reports the
    # "before" picture, so wait for the run it claimed to finish
    _wait_for_training(existing_feed)
    assert _stats_computed_at(existing_feed) > trained_at


def _wait_for_training(feed, timeout=60.0):
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not progress.is_running(feed.user_hash, feed.name_hash):
            return
        time.sleep(0.05)
    raise AssertionError("the training run never finished")


def test_untrained_feed_is_neither_scored_nor_crashed(existing_user, existing_feed):
    """A feed with articles but no stats row has no model to score with. It
    must not be picked up by the scoring pass, and asking anyway is a no-op
    rather than an error."""
    for _ in range(3):
        _add_item(existing_feed, f"http://example.com/{uuid.uuid4()}/")

    assert chosen_model_name(existing_feed) is None
    assert existing_feed.name not in {f.name for f in feeds_needing_scoring()}
    # no labels either, so nothing is due at all
    assert existing_feed.name not in {f.name for f in feeds_needing_training()}

    assert score_feed(existing_feed) == 0
    feed_ranking_job()  # and the job as a whole stays quiet


def test_untrained_feed_waits_for_enough_labels(existing_user, existing_feed):
    """Below MIN_LABELS_TO_RANK there is nothing to fit a model on, so a feed
    that has never been trained waits rather than running the bake-off."""
    items = [
        _add_item(existing_feed, f"http://example.com/{uuid.uuid4()}/")
        for _ in range(MIN_LABELS_TO_RANK)
    ]

    _vote(existing_user, existing_feed, items[0], 1.0)
    assert existing_feed.name not in {f.name for f in feeds_needing_training()}

    for item in items[1:]:
        _vote(existing_user, existing_feed, item, -1.0)
    assert existing_feed.name in {f.name for f in feeds_needing_training()}


def test_scoring_falls_back_to_a_full_run_when_the_model_is_gone(
    existing_user, existing_feed, monkeypatch
):
    """A deploy can drop a model the stats table had chosen. Only a full run
    can pick a new one, so the scoring pass hands the feed over instead of
    raising."""
    _trained_feed(existing_user, existing_feed)
    _add_item(
        existing_feed, f"http://example.com/{uuid.uuid4()}/", embedding=[1.0, 0.5]
    )
    trained_at = _stats_computed_at(existing_feed)

    with engine.get_db_con() as cur:
        cur.execute(
            "UPDATE ranking_model_stats SET model_name = %s "
            "WHERE user_hash = %s AND feed_hash = %s AND chosen",
            (
                "a_model_this_build_does_not_have",
                existing_feed.user_hash,
                existing_feed.name_hash,
            ),
        )

    assert score_feed(existing_feed) == 0  # it trained instead of scoring
    assert _stats_computed_at(existing_feed) > trained_at
    # and the full run left a model this build actually has
    assert chosen_model_name(existing_feed) in {m.name for m in engine.all_models()}


def test_scoring_leaves_already_scored_articles_alone(existing_user, existing_feed):
    """The cheap pass writes only the rows that have never been scored; an
    article the last full run already scored keeps its predicted_at."""
    items = _trained_feed(existing_user, existing_feed)
    before = _prediction(existing_feed, items[0])
    assert before["predicted_at"] is not None

    fresh = _add_item(
        existing_feed, f"http://example.com/{uuid.uuid4()}/", embedding=[1.0, 0.5]
    )
    assert score_feed(existing_feed) == 1

    assert (
        _prediction(existing_feed, items[0])["predicted_at"] == before["predicted_at"]
    )
    assert _prediction(existing_feed, fresh)["predicted_at"] is not None


def test_scoring_pass_does_not_register_as_training(existing_user, existing_feed):
    """The UI's training indicator means "the model is being rebuilt". A
    score-only pass deliberately does not light it up."""
    _trained_feed(existing_user, existing_feed)
    _add_item(
        existing_feed, f"http://example.com/{uuid.uuid4()}/", embedding=[1.0, 0.5]
    )
    progress.reset()

    score_feed(existing_feed)

    assert progress.status(existing_feed.user_hash, existing_feed.name_hash) is None


def test_scoring_pass_uses_the_chosen_model(existing_user, existing_feed):
    """The cheap pass is the chosen model re-fit, not a fresh bake-off: the
    prediction it writes is stamped with the model the stats table picked."""
    _trained_feed(existing_user, existing_feed)
    winner = chosen_model_name(existing_feed)
    fresh = _add_item(
        existing_feed, f"http://example.com/{uuid.uuid4()}/", embedding=[1.0, 0.5]
    )

    score_feed(existing_feed)

    with engine.get_db_con() as cur:
        cur.execute(
            "SELECT predicted_model FROM feed_items "
            "WHERE user_hash = %s AND feed_hash = %s AND item_url_hash = %s",
            (existing_feed.user_hash, existing_feed.name_hash, fresh.url_hash),
        )
        assert cur.fetchone()["predicted_model"] == winner


def test_a_vote_is_stamped_on_an_absolute_instant(existing_user, existing_feed):
    """The gate compares a vote's score_date against the database's own NOW(),
    so the two have to be on the same clock.

    The API container runs on a local timezone (its dockerfile sets TZ) while
    Postgres runs on UTC. A naive local timestamp went into the TIMESTAMPTZ
    column verbatim and came back as a vote cast hours ago, so a fresh vote
    read as older than the last training run and the feed quietly never
    retrained. The timezone is forced here rather than inherited so this holds
    wherever the suite runs.
    """
    import os
    import time

    item = _add_item(existing_feed, f"http://example.com/{uuid.uuid4()}/")
    before = os.environ.get("TZ")
    os.environ["TZ"] = "America/New_York"  # what the dockerfile sets
    time.tzset()
    try:
        _vote(existing_user, existing_feed, item, 1.0)
    finally:
        if before is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = before
        time.tzset()

    with engine.get_db_con() as cur:
        cur.execute(
            "SELECT score_date - NOW() AS skew FROM item_states "
            "WHERE user_hash = %s AND feed_hash = %s AND item_url_hash = %s",
            (existing_user.name_hash, existing_feed.name_hash, item.url_hash),
        )
        skew = cur.fetchone()["skew"]

    assert abs(skew.total_seconds()) < 60, (
        f"the vote landed {skew} away from the database's clock, so anything "
        "comparing it against NOW() will misjudge how fresh it is"
    )


def test_a_new_vote_retrains_whatever_the_app_timezone(existing_user, existing_feed):
    """The same thing from the gate's side: the retrain has to be triggered by
    a vote cast in a container whose clock is not the database's."""
    import os
    import time

    _trained_feed(existing_user, existing_feed)
    trained_at = _stats_computed_at(existing_feed)
    extra = _add_item(
        existing_feed, f"http://example.com/{uuid.uuid4()}/", embedding=[4.0, 0.2]
    )

    before = os.environ.get("TZ")
    os.environ["TZ"] = "America/New_York"
    time.tzset()
    try:
        _vote(existing_user, existing_feed, extra, 1.0)
        assert existing_feed.name in {f.name for f in feeds_needing_training()}
        feed_ranking_job()
    finally:
        if before is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = before
        time.tzset()

    assert _stats_computed_at(existing_feed) > trained_at
