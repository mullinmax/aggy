import pytest
import uuid

from db.feed import Feed
from db.user import User


@pytest.fixture(scope="function")
def unique_feed(existing_user: User) -> Feed:
    """Generates unique feed data for each test.

    The owning user is created so the foreign key constraint to ``users``
    is satisfied if the feed itself is later persisted.
    """
    feed = Feed(
        user_hash=existing_user.name_hash,
        name=f"Feed Name {uuid.uuid4()}",
    )

    yield feed


@pytest.fixture(scope="function")
def existing_feed(unique_feed: Feed, existing_user: User) -> Feed:
    if not unique_feed.exists():
        existing_user.add_feed(unique_feed)
    yield unique_feed
