import pytest

from db.feed import Feed


def test_key(unique_feed):
    """Tests the key property."""
    assert (
        unique_feed.key == f"USER:{unique_feed.user_hash}:FEED:{unique_feed.name_hash}"
    )


def test_items_key(unique_feed):
    """Tests the items_key property."""
    assert (
        unique_feed.items_key
        == f"USER:{unique_feed.user_hash}:FEED:{unique_feed.name_hash}:ITEMS"
    )


def test_sources_key(unique_feed):
    """Tests the sources_key property."""
    assert (
        unique_feed.sources_key
        == f"USER:{unique_feed.user_hash}:FEED:{unique_feed.name_hash}:SOURCES"
    )


def test_feed_creation(existing_user, existing_feed):
    """Tests creation of a feed."""
    assert existing_feed.exists()

    assert existing_feed in existing_user.feeds

    existing_feed.delete()
    assert not existing_feed.exists()


def test_feed_duplicate_creation(unique_feed):
    """Tests that creating a duplicate feed raises an exception."""
    unique_feed.create()

    with pytest.raises(Exception) as e:
        unique_feed.create()  # Attempt to create duplicate feed
    assert "already exists" in str(e.value), "Should not allow duplicate feeds"


def test_feed_read(unique_feed):
    """Tests reading a feed back from the database."""
    unique_feed.create()
    read_feed = Feed.read(
        user_hash=unique_feed.user_hash, name_hash=unique_feed.name_hash
    )
    assert read_feed is not None, "Feed should be readable"
    assert read_feed.name == unique_feed.name, "Feed name should match"


def test_feed_read_all(unique_feed):
    """Tests reading all feeds for a user."""
    # Create multiple feeds for testing
    for i in range(3):
        unique_feed.name += f" {i}"
        unique_feed.create()

    feeds = Feed.read_all(unique_feed.user_hash)
    assert len(feeds) == 3, "Should read all feeds for a user"

    for feed in feeds:
        assert (
            feed.user_hash == unique_feed.user_hash
        ), "Feed should be for the correct user"


@pytest.mark.filterwarnings("ignore::UserWarning")
def test_get_items(unique_feed, unique_item_strict):
    """Tests getting all items for a feed."""
    unique_feed.create()

    items = [unique_item_strict.model_copy() for i in range(3)]

    with unique_feed.db_con() as r:
        for i, item in enumerate(items):
            item.url = f"http://example.com/{i}"
            item.create()
            r.zadd(unique_feed.items_key, {item.url_hash: i})

    act_items = unique_feed.query_items()
    assert len(act_items) == 3, "Should get all items for a feed"
    for item in act_items:
        assert item.url_hash in [
            i.url_hash for i in items
        ], "Should get the correct items"

    unique_feed.delete()

    assert not unique_feed.exists()


def test_sources(unique_feed, unique_source):
    """Tests adding and removing sources from a feed."""
    unique_feed.create()

    unique_feed.add_source(unique_source)
    assert unique_source.name_hash in unique_feed.source_hashes
    assert len(unique_feed.source_hashes) == 1
    assert unique_source in unique_feed.sources
    assert unique_source.exists()

    unique_feed.delete_source(unique_source)
    assert unique_source.name_hash not in unique_feed.source_hashes
    assert not unique_source.exists()


def test_delete_feed_removes_sources(unique_feed, unique_source):
    """Tests that deleting a feed removes its sources."""
    unique_feed.create()
    unique_feed.add_source(unique_source)

    with unique_feed.db_con() as r:
        assert r.exists(unique_feed.sources_key)
        assert not r.exists(unique_feed.items_key)
        assert r.exists(unique_feed.key)
        assert r.exists(unique_source.key)

    unique_feed.delete()
    assert not unique_source.exists()
    assert not unique_feed.exists()
    with unique_feed.db_con() as r:
        assert not r.exists(unique_feed.sources_key)
        assert not r.exists(unique_feed.items_key)
        assert not r.exists(unique_feed.key)
        assert not r.exists(unique_source.key)


def test_remove_items(unique_feed, unique_item_strict):
    """Tests removing items from a feed."""
    unique_feed.create()
    unique_item_strict.create()
    unique_feed.add_items(unique_item_strict)

    assert unique_item_strict in unique_feed.query_items()

    unique_feed.remove_items(unique_item_strict)
    assert unique_item_strict not in unique_feed.query_items()
    assert unique_item_strict.exists()

    unique_feed.delete()
    assert not unique_feed.exists()
    assert unique_item_strict.exists()
