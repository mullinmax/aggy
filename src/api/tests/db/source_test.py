import pytest

from db.source import Source


def test_create_source(unique_source):
    unique_source.create()
    assert unique_source.exists()

    unique_source.delete()
    assert not unique_source.exists()


def test_duplicate_source_creation(unique_source):
    unique_source.create()

    with pytest.raises(Exception) as e:
        unique_source.create()  # Attempt to create duplicate source
    assert "Cannot create duplicate source" in str(
        e.value
    ), "Should not allow duplicate sources"


def test_read_source(unique_source):
    unique_source.create()
    read_source = Source.read(
        user_hash=unique_source.user_hash,
        feed_hash=unique_source.feed_hash,
        source_hash=unique_source.name_hash,
    )
    assert read_source, "Source should be readable"
    assert read_source.name == unique_source.name, "Source name should match"
    assert read_source.url == unique_source.url, "Source url should match"
    assert (
        read_source.user_hash == unique_source.user_hash
    ), "Source user_hash should match"
    assert (
        read_source.feed_hash == unique_source.feed_hash
    ), "Source feed_hash should match"


def test_source_ingest_interval_roundtrip(unique_source):
    unique_source.ingest_interval_minutes = 120
    unique_source.create()

    read_source = Source.read(
        user_hash=unique_source.user_hash,
        feed_hash=unique_source.feed_hash,
        source_hash=unique_source.name_hash,
    )
    assert read_source.ingest_interval_minutes == 120


def test_source_update_ingest_interval(unique_source):
    unique_source.create()

    def read_back():
        return Source.read(
            user_hash=unique_source.user_hash,
            feed_hash=unique_source.feed_hash,
            source_hash=unique_source.name_hash,
        )

    assert read_back().ingest_interval_minutes is None

    unique_source.update(
        name=unique_source.name, url=str(unique_source.url), ingest_interval=45
    )
    assert read_back().ingest_interval_minutes == 45

    # leaving the interval out of an update keeps the current value
    unique_source.update(name=unique_source.name, url=str(unique_source.url))
    assert read_back().ingest_interval_minutes == 45

    # an explicit None resets to the server default
    unique_source.update(
        name=unique_source.name, url=str(unique_source.url), ingest_interval=None
    )
    assert read_back().ingest_interval_minutes is None


def test_reddit_source_defaults_to_reddit_interval(unique_source):
    from constants import REDDIT_SOURCE_READ_INTERVAL_MINUTES

    unique_source.url = "https://www.reddit.com/r/pics/top.rss?t=day"
    unique_source.create()

    read_source = Source.read(
        user_hash=unique_source.user_hash,
        feed_hash=unique_source.feed_hash,
        source_hash=unique_source.name_hash,
    )
    assert (
        read_source.ingest_interval_minutes == REDDIT_SOURCE_READ_INTERVAL_MINUTES
    )


def test_reddit_source_keeps_explicit_interval(unique_source):
    unique_source.url = "https://www.reddit.com/r/pics/top.rss?t=day"
    unique_source.ingest_interval_minutes = 30
    unique_source.create()

    read_source = Source.read(
        user_hash=unique_source.user_hash,
        feed_hash=unique_source.feed_hash,
        source_hash=unique_source.name_hash,
    )
    assert read_source.ingest_interval_minutes == 30


def test_source_add_items(unique_source, unique_item_strict):
    unique_source.create()
    unique_item_strict.create()
    unique_source.add_items(items=[unique_item_strict])
    assert (
        unique_item_strict in unique_source.query_items()
    ), "Item should be in source items"


def test_count_items(unique_source, unique_item_strict):
    unique_source.create()
    unique_item_strict.create()
    assert unique_source.count_items() == 0, "Should not count items in source"
    unique_source.add_items(unique_item_strict)
    assert unique_source.count_items() == 1, "Should count items in source"
