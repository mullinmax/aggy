"""Database-backed tests for what a training run reads, writes and reports."""

import uuid

from pydantic import HttpUrl

from db.feed import Feed
from db.item import ItemLoose
from db.item_state import ItemState
from ranking import progress
from ranking.engine import (
    _write_predictions,
    load_feed_features,
    rank_feed,
    training_steps,
)


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


def test_training_reads_only_the_labeled_articles(
    existing_user, existing_feed, unique_item_strict
):
    """A feed holds thousands of articles, each carrying a full embedding
    vector; training learns from the handful that were voted on, and reading
    the rest before a model has even been picked is pure cost."""
    voted = _add_item(existing_feed, "http://example.com/voted/")
    _add_item(existing_feed, "http://example.com/unvoted-1/")
    _add_item(existing_feed, "http://example.com/unvoted-2/")

    ItemState.set_state(
        user_hash=existing_user.name_hash,
        feed_hash=existing_feed.name_hash,
        item_url_hash=voted.url_hash,
        score=1,
        is_read=True,
    )

    everything = load_feed_features(existing_feed)
    assert len(everything) == 3

    labeled = load_feed_features(existing_feed, labeled_only=True)
    assert [f.url_hash for f in labeled] == [voted.url_hash]


def test_listed_articles_count_as_labeled(
    existing_user, existing_feed, existing_list, unique_item_strict
):
    """List membership is a label of its own (an implied upvote), so the
    labeled load has to keep listed articles too."""
    listed = _add_item(existing_feed, "http://example.com/listed/")
    _add_item(existing_feed, "http://example.com/plain/")
    existing_list.add_item(listed.url_hash)

    labeled = load_feed_features(existing_feed, labeled_only=True)
    assert [f.url_hash for f in labeled] == [listed.url_hash]


def test_predictions_are_written_per_article(existing_user, existing_feed):
    """The batched write has to land each article's own score, and touch
    nothing outside this feed."""
    items = [
        _add_item(existing_feed, f"http://example.com/batch/{i}/") for i in range(5)
    ]
    other_feed = Feed(user_hash=existing_user.name_hash, name=f"Other {uuid.uuid4()}")
    other_feed.create()
    other_feed.add_items(items[0])

    features = load_feed_features(existing_feed)
    by_hash = {f.url_hash: i for i, f in enumerate(features)}
    scores = [i / 10 for i in range(len(features))]
    confs = [1 - i / 10 for i in range(len(features))]
    _write_predictions(existing_feed, features, scores, confs, "test_model")

    rows = {
        item.url_hash: meta
        for item, meta in existing_feed.query_items_with_sources(sort="newest")
    }
    assert len(rows) == len(items)
    for url_hash, meta in rows.items():
        assert meta["predicted_score"] == scores[by_hash[url_hash]]
        assert meta["predicted_confidence"] == confs[by_hash[url_hash]]

    # the same article in another feed keeps its own (unset) prediction
    other = other_feed.query_items_with_sources(sort="newest")
    assert [meta["predicted_score"] for _, meta in other] == [None]


def test_run_reports_every_phase(existing_user, existing_feed):
    """The progress a run reports has to actually move: reading the votes,
    each model as it is cross-validated, then scoring the feed."""
    progress.reset()
    items = [
        _add_item(
            existing_feed,
            f"http://example.com/phase/{i}/",
            embedding=[5.0 if i % 2 == 0 else -5.0, 0.1 * i],
        )
        for i in range(6)
    ]
    for i, item in enumerate(items[:4]):
        ItemState.set_state(
            user_hash=existing_user.name_hash,
            feed_hash=existing_feed.name_hash,
            item_url_hash=item.url_hash,
            score=1 if i % 2 == 0 else -1,
            is_read=True,
        )

    seen = []
    real_update = progress.update

    def record(user_hash, feed_hash, **kwargs):
        seen.append(kwargs)
        real_update(user_hash, feed_hash, **kwargs)

    progress.update = record
    try:
        progress.start(existing_user.name_hash, existing_feed.name_hash, 1)
        rank_feed(existing_feed)
    finally:
        progress.update = real_update

    phases = [entry.get("phase") for entry in seen]
    assert phases[0] == progress.PHASE_LOADING
    assert progress.PHASE_EVALUATING in phases
    assert progress.PHASE_TRAINING in phases
    assert progress.PHASE_PREDICTING in phases

    # steps only ever move forward, and never past the budget
    steps = [entry["step"] for entry in seen if entry.get("step") is not None]
    assert steps == sorted(steps)
    assert max(steps) <= training_steps()
    # and the run says what it is doing, not just which step it is on
    assert any(entry.get("note") for entry in seen)
