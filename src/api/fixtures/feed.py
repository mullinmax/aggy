import pytest
import uuid

from db.feed import Feed


@pytest.fixture(scope="function")
def unique_feed(unique_category):
    """Generates unique category data for each test, assuming a Redis connection fixture."""
    feed = Feed(
        user_hash=uuid.uuid4().hex,
        category_hash=unique_category.name_hash,
        name=f"Feed Name {uuid.uuid4()}",
        url="http://example.com",
    )

    yield feed

    if feed.exists():
        feed.delete()
