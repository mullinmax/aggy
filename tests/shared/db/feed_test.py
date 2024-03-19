import pytest

from src.shared.db.feed import Feed


def test_create_feed(unique_feed):
    unique_feed.create()
    assert unique_feed.exists()

    unique_feed.delete()
    assert not unique_feed.exists()


def test_duplicate_feed_creation(unique_feed):
    unique_feed.create()

    with pytest.raises(Exception) as e:
        unique_feed.create()  # Attempt to create duplicate feed
    assert "Cannot create duplicate feed" in str(
        e.value
    ), "Should not allow duplicate feeds"


def test_read_feed(unique_feed):
    unique_feed.create()
    read_feed = Feed.read(
        user_hash=unique_feed.user_hash,
        category_hash=unique_feed.category_hash,
        feed_hash=unique_feed.name_hash,
    )
    assert read_feed, "Feed should be readable"
    assert read_feed.name == unique_feed.name, "Feed name should match"
    assert read_feed.url == unique_feed.url, "Feed url should match"
    assert read_feed.user_hash == unique_feed.user_hash, "Feed user_hash should match"
    assert (
        read_feed.category_hash == unique_feed.category_hash
    ), "Feed category_hash should match"
