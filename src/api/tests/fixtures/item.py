import pytest
from datetime import datetime
import uuid

from db.item import ItemStrict


@pytest.fixture(scope="function")
def unique_item_strict(unique_category):
    item = ItemStrict(
        url="http://example.com/" + str(uuid.uuid4()),
        author="Example author",
        date_published=datetime.now(),
        image_url="http://example.com/image.jpg",
        title="Example title",
        domain="example.com",
        excerpt="Example excerpt",
        content="Example content",
    )

    yield item

    if item.exists():
        item.delete()


@pytest.fixture(scope="function")
def existing_item_strict(existing_feed, existing_category, unique_item_strict):
    unique_item_strict.create()
    existing_feed.add_items(unique_item_strict)
    existing_category.add_items(unique_item_strict)
    yield unique_item_strict
