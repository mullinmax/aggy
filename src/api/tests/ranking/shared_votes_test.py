"""Votes are shared across feeds: a vote cast in one feed trains the ranking
models of every feed the item appears in."""

import uuid

import pytest

from db.feed import Feed
from db.item import ItemStrict
from db.item_state import ItemState
from ranking.engine import (
    feeds_needing_rank,
    label_counts,
    load_feed_features,
    rank_feed,
)


def _make_item(url: str) -> ItemStrict:
    item = ItemStrict(
        url=url,
        title=f"Title {url}",
        domain="example.com",
        excerpt="excerpt",
        content="content",
    )
    item.create()
    return item


@pytest.fixture
def two_feeds_sharing_item(existing_user):
    """Two feeds that both contain the same item (as a feed source would)."""
    feed_a = Feed(user_hash=existing_user.name_hash, name=f"A {uuid.uuid4()}")
    feed_b = Feed(user_hash=existing_user.name_hash, name=f"B {uuid.uuid4()}")
    feed_a.create()
    feed_b.create()
    item = _make_item(f"http://example.com/{uuid.uuid4()}")
    feed_a.add_items(item)
    feed_b.add_items(item)
    return feed_a, feed_b, item


def _vote(user_hash, feed, item, score):
    ItemState.set_state(
        user_hash=user_hash,
        feed_hash=feed.name_hash,
        item_url_hash=item.url_hash,
        score=score,
        is_read=True,
    )


def test_vote_in_one_feed_labels_item_in_other(
    existing_user, two_feeds_sharing_item
):
    feed_a, feed_b, item = two_feeds_sharing_item

    # no vote anywhere yet -> the item is unlabeled in feed A
    features = {f.url_hash: f for f in load_feed_features(feed_a)}
    assert features[item.url_hash].label is None

    # vote in feed B only
    _vote(existing_user.name_hash, feed_b, item, 1.0)

    # feed A's training now sees that vote
    features = {f.url_hash: f for f in load_feed_features(feed_a)}
    assert features[item.url_hash].label == 1.0


def test_latest_vote_wins_across_feeds(existing_user, two_feeds_sharing_item):
    feed_a, feed_b, item = two_feeds_sharing_item

    _vote(existing_user.name_hash, feed_a, item, -1.0)
    _vote(existing_user.name_hash, feed_b, item, 1.0)  # cast later, so wins

    features = {f.url_hash: f for f in load_feed_features(feed_a)}
    assert features[item.url_hash].label == 1.0


def test_label_counts_include_shared_votes(existing_user, two_feeds_sharing_item):
    feed_a, feed_b, item = two_feeds_sharing_item
    _vote(existing_user.name_hash, feed_b, item, 1.0)

    counts = label_counts(feed_a)
    assert counts["up"] == 1
    assert counts["down"] == 0


def test_feeds_needing_rank_sees_shared_vote(
    existing_user, two_feeds_sharing_item
):
    feed_a, feed_b, item = two_feeds_sharing_item
    _vote(existing_user.name_hash, feed_b, item, 1.0)

    names = {f.name for f in feeds_needing_rank()}
    # both feeds contain the item, so both are due for a re-rank
    assert feed_a.name in names
    assert feed_b.name in names


def test_query_items_shows_shared_vote_and_hides_when_read(
    existing_user, two_feeds_sharing_item
):
    feed_a, feed_b, item = two_feeds_sharing_item
    _vote(existing_user.name_hash, feed_b, item, 1.0)

    # feed A's item view reflects the vote cast in feed B
    results = feed_a.query_items_with_sources()
    meta = next(m for it, m in results if it.url_hash == item.url_hash)
    assert meta["user_score"] == 1.0

    # and "hide read" (include_read=False) hides the item everywhere
    hidden = feed_a.query_items_with_sources(include_read=False)
    assert all(it.url_hash != item.url_hash for it, _ in hidden)


def test_shared_votes_train_predictions_in_other_feed(
    existing_user, existing_feed
):
    """End-to-end: enough votes cast in feed B produce predictions in feed A."""
    feed_b = Feed(user_hash=existing_user.name_hash, name=f"B {uuid.uuid4()}")
    feed_b.create()

    items = [_make_item(f"http://example.com/{uuid.uuid4()}") for _ in range(4)]
    for it in items:
        existing_feed.add_items(it)
        feed_b.add_items(it)

    # vote only in feed B
    _vote(existing_user.name_hash, feed_b, items[0], 1.0)
    _vote(existing_user.name_hash, feed_b, items[1], 1.0)
    _vote(existing_user.name_hash, feed_b, items[2], -1.0)

    # ranking feed A (no votes of its own) still trains on the shared votes
    stats = rank_feed(existing_feed)
    assert any(s.n_labels >= 3 for s in stats)
    counts = label_counts(existing_feed)
    assert counts["predicted_items"] > 0
