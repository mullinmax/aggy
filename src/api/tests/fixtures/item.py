import pytest
from datetime import datetime, timezone

from db.item import ItemStrict


@pytest.fixture(scope="function")
def unique_item_strict():
    item = ItemStrict(
        url="http://example.com/",
        author="Example author",
        # tz-aware on purpose: date_published is a TIMESTAMPTZ, so a naive
        # value comes back from the database carrying UTC and no longer
        # compares equal to the item that was stored.
        date_published=datetime.now(timezone.utc),
        image_url="http://example.com/image.jpg",
        title="Example title",
        domain="example.com",
        excerpt="Example excerpt",
        content="Example content",
    )

    yield item


@pytest.fixture(scope="function")
def existing_item_strict(existing_source, existing_feed, unique_item_strict):
    if not unique_item_strict.exists():
        unique_item_strict.create()
    existing_source.add_items(unique_item_strict)
    existing_feed.add_items(unique_item_strict)
    yield unique_item_strict
