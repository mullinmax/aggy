"""Feed-as-source: one feed can mirror another feed's items."""

import uuid

import pytest

from db.feed import Feed
from db.item import ItemStrict
from db.propagation import propagate_items
from db.source import Source


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
def feed_a(existing_user):
    feed = Feed(user_hash=existing_user.name_hash, name=f"Feed A {uuid.uuid4()}")
    feed.create()
    return feed


@pytest.fixture
def feed_b(existing_user):
    feed = Feed(user_hash=existing_user.name_hash, name=f"Feed B {uuid.uuid4()}")
    feed.create()
    return feed


def _source_in(feed: Feed) -> Source:
    src = Source(
        user_hash=feed.user_hash,
        feed_hash=feed.name_hash,
        name=f"RSS {uuid.uuid4()}",
        url="http://example.com/rss",
    )
    feed.add_source(src)
    return src


def test_add_feed_source_backfills_existing_items(feed_a, feed_b):
    src_b = _source_in(feed_b)
    item = _make_item("http://example.com/1")
    src_b.add_items(item)
    feed_b.add_items(item)

    feed_a.add_feed_source(feed_b)

    # the backfilled item now lives in feed A too
    assert item.url_hash in feed_a.item_url_hashes()


def test_feed_source_appears_in_stats_not_in_ingest_sources(feed_a, feed_b):
    feed_a.add_feed_source(feed_b)

    # feed sources show in the management list...
    stats = feed_a.sources_with_stats()
    feed_sources = [s for s in stats if s["source_feed_hash"] is not None]
    assert len(feed_sources) == 1
    assert feed_sources[0]["source_feed_name"] == feed_b.name

    # ...but never in the RSS ingest iteration
    assert feed_a.sources == []


def test_new_item_fans_out_to_subscriber(feed_a, feed_b):
    src_b = _source_in(feed_b)
    feed_a.add_feed_source(feed_b)

    # a later item added to B (as ingest would) must appear in A
    item = _make_item("http://example.com/late")
    src_b.add_items(item)
    feed_b.add_items(item)
    propagate_items(feed_b.user_hash, feed_b.name_hash, [item.url_hash])

    assert item.url_hash in feed_a.item_url_hashes()


def test_chained_feed_sources_propagate(feed_a, feed_b, existing_user):
    feed_c = Feed(user_hash=existing_user.name_hash, name=f"Feed C {uuid.uuid4()}")
    feed_c.create()

    src_c = _source_in(feed_c)
    feed_b.add_feed_source(feed_c)  # B mirrors C
    feed_a.add_feed_source(feed_b)  # A mirrors B

    item = _make_item("http://example.com/chain")
    src_c.add_items(item)
    feed_c.add_items(item)
    propagate_items(feed_c.user_hash, feed_c.name_hash, [item.url_hash])

    assert item.url_hash in feed_b.item_url_hashes()
    assert item.url_hash in feed_a.item_url_hashes()


def test_cannot_add_feed_as_source_of_itself(feed_a):
    with pytest.raises(ValueError):
        feed_a.add_feed_source(feed_a)


def test_cycle_is_rejected(feed_a, feed_b):
    feed_a.add_feed_source(feed_b)  # items flow B -> A
    # adding A as a source of B would close the loop
    with pytest.raises(ValueError):
        feed_b.add_feed_source(feed_a)


def test_duplicate_feed_source_is_rejected(feed_a, feed_b):
    feed_a.add_feed_source(feed_b)
    with pytest.raises(ValueError):
        feed_a.add_feed_source(feed_b)


def test_deleting_origin_feed_removes_mirror_source(feed_a, feed_b):
    feed_a.add_feed_source(feed_b)
    assert any(s["source_feed_hash"] for s in feed_a.sources_with_stats())

    feed_b.delete()

    # the mirror source row cascades away with the origin feed
    assert not any(s["source_feed_hash"] for s in feed_a.sources_with_stats())
