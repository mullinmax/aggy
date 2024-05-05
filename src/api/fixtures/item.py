import pytest
from datetime import datetime

from db.item import ItemStrict


@pytest.fixture(scope="function")
def unique_item_strict(unique_category):
    item = ItemStrict(
        url="http://example.com",
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
