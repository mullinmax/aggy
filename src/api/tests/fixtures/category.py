import pytest
import uuid

from db.feed import Feed
from db.user import User


@pytest.fixture(scope="function")
def unique_feed(unique_user: User) -> Feed:
    """Generates unique feed data for each test, assuming a Redis connection fixture."""
    feed = Feed(
        user_hash=unique_user.name_hash,
        name=f"Feed Name {uuid.uuid4()}",
    )

    yield feed

    if feed.exists():
        feed.delete()


@pytest.fixture(scope="function")
def existing_feed(unique_feed: Feed, existing_user: User) -> Feed:
    """Generates existing feed data for each test, assuming a Redis connection fixture."""
    existing_user.add_feed(unique_feed)
    yield unique_feed
