import pytest
import uuid

from db.source import Source
from db.feed import Feed
from db.user import User


@pytest.fixture(scope="function")
def unique_source(existing_feed: Feed, existing_user: User) -> Source:
    """Generates unique source data for each test.

    Depends on ``existing_feed`` so the (user_hash, feed_hash) foreign key
    can be satisfied if the source is persisted.
    """
    source = Source(
        user_hash=existing_user.name_hash,
        feed_hash=existing_feed.name_hash,
        name=f"Source Name {uuid.uuid4()}",
        url="http://example.com",
    )

    yield source


@pytest.fixture(scope="function")
def existing_source(unique_source: Source, existing_feed: Feed) -> Source:
    if not unique_source.exists():
        existing_feed.add_source(unique_source)
    yield unique_source
