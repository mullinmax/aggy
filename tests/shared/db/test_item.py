import pytest
from redislite import Redis

from src.shared.db import BlinderBaseModel, ItemLoose, ItemStrict, ItemBase

@pytest.fixture(scope="session", autouse=True)
def override_redis_connection():
    # Setup the in-memory Redis server
    original_redis = BlinderBaseModel.r
    BlinderBaseModel.r = Redis()

    yield

    # Teardown and revert to the original Redis connection after tests
    BlinderBaseModel.r.shutdown()
    BlinderBaseModel.r = original_redis

def test_create_read_item():
    item_data = {
        "url": "https://example.com/",
        "title": "Example Title",
        "content": "<p>Example Content</p>",
        "author": "Author Name",
        "image_url": "https://example.com/image.jpg",
        "domain": "example.com",
        "excerpt": "Example excerpt",
    }
    item = ItemLoose(**item_data)
    ItemLoose.create(item)

    read_item = ItemLoose.read(item.url_hash)
    assert read_item
    assert str(read_item.url) == item_data["url"]

def test_update_item():
    item_data = {
        "url": "https://example.com",
        "title": "Original Title",
    }
    item = ItemLoose(**item_data)
    ItemLoose.create(item)

    update_data = {"title": "Updated Title"}
    ItemLoose.update(item.url_hash, **update_data)

    updated_item = ItemLoose.read(item.url_hash)
    assert updated_item.title == update_data["title"]

def test_delete_item():
    item_data = {
        "url": "https://example.com",
        "title": "Example Title",
    }
    item = ItemLoose(**item_data)
    ItemLoose.create(item)

    ItemLoose.delete(item.url_hash)
    deleted_item = ItemLoose.read(item.url_hash)
    assert deleted_item is None

