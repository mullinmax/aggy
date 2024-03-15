import pytest
import uuid

from src.shared.db.item import ItemLoose


@pytest.fixture(scope="function")
def unique_item_data():
    """Generates unique item data for each test."""
    unique_id = str(uuid.uuid4())
    return {
        "url": f"https://example.com/{unique_id}",
        "title": f"Example Title {unique_id}",
        "content": f"<p>Example Content {unique_id}</p>",
        "author": f"Author Name {unique_id}",
        "image_url": f"https://example.com/image{unique_id}.jpg",
        "domain": f"example{unique_id}.com",
        "excerpt": f"Example excerpt {unique_id}",
        "date_published": "2021-01-01T00:00:00",
    }


@pytest.mark.parametrize(
    "html_input,expected_output",
    [
        ("<script>alert('xss');</script>", ""),
        ("<p>Valid content</p>", "<p>Valid content</p>"),
        (
            '<a href="http://example.com">Example</a>',
            '<a href="http://example.com">Example</a>',
        ),
        (
            '<img src="http://example.com/image.jpg">',
            '<img src="http://example.com/image.jpg">',
        ),
    ],
)
def test_content_sanitization(html_input, expected_output, unique_item_data):
    """Tests that only safe HTML content is retained."""
    unique_item_data["content"] = html_input
    item = ItemLoose(**unique_item_data)
    assert item.content == expected_output


def test_merge_items(unique_item_data):
    """Tests merging of multiple loose items."""
    item1 = ItemLoose(**unique_item_data)
    item2_data = unique_item_data.copy()
    item2_data["title"] = "A different title"
    item2 = ItemLoose(**item2_data)

    merged_item = ItemLoose.merge_instances([item1, item2])
    assert merged_item.title in [
        "A different title",
        unique_item_data["title"],
    ], "Title should be one of the original titles"
    assert (
        str(merged_item.url) == unique_item_data["url"]
    ), "URL should remain unchanged"


def test_date_published_parsing(unique_item_data):
    """Tests parsing of various date_published string formats."""
    date_str = "2022-12-25"
    unique_item_data["date_published"] = date_str
    item = ItemLoose(**unique_item_data)
    assert item.date_published.isoformat().startswith(
        date_str
    ), "The date_published should be correctly parsed"


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
    item.update(**update_data)

    updated_item = ItemLoose.read(item.url_hash)
    assert updated_item.title == update_data["title"]


def test_delete_item():
    item_data = {
        "url": "https://example.com",
        "title": "Example Title",
    }
    item = ItemLoose(**item_data)
    ItemLoose.create(item)

    non_deleted_item = ItemLoose.read(item.url_hash)
    assert non_deleted_item.exists()
    assert item.exists()
    assert non_deleted_item

    item.delete()

    deleted_item = ItemLoose.read(item.url_hash)
    assert not item.exists()
    assert not non_deleted_item.exists()
    assert deleted_item is None
