import pytest
import uuid

from db.feed import Feed


@pytest.fixture(scope="function")
def unique_feed(unique_category, unique_user) -> Feed:
    """Generates unique category data for each test"""
    feed = Feed(
        user_hash=unique_user.name_hash,
        category_hash=unique_category.name_hash,
        name=f"Feed Name {uuid.uuid4()}",
        url="http://example.com",
    )

    yield feed

    if feed.exists():
        feed.delete()


@pytest.fixture(scope="function")
def existing_feed(unique_feed: Feed) -> Feed:
    """Generates existing category data for each test"""
    unique_feed.create()
    yield unique_feed
