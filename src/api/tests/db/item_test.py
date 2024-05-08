import pytest

from db.item import ItemLoose, ItemStrict


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
def test_content_sanitization(html_input, expected_output, unique_item_strict):
    """Tests that only safe HTML content is retained."""
    unique_item_strict.content = html_input
    unique_item_strict.create()

    item = ItemLoose.read(unique_item_strict.url_hash)
    assert item.content == expected_output


def test_merge_items(unique_item_strict):
    """Tests merging of multiple loose items."""
    item1 = unique_item_strict
    item2 = item1.model_copy()
    item2.title = "A different title"

    merged_item = ItemLoose.merge_instances([item1, item2])
    assert merged_item.title in [
        "A different title",
        item1.title,
    ], "Title should be one of the original titles"
    assert str(merged_item.url) == str(item1.url), "URL should remain unchanged"


@pytest.mark.filterwarnings("ignore::UserWarning")
@pytest.mark.parametrize(
    "raw_date,expected_date",
    [
        ("2021-01-01", "2021-01-01"),
        ("2021/01/01", "2021-01-01"),
        ("2021-01-01T00:00:00", "2021-01-01"),
        ("2021-01-01T00:00:00Z", "2021-01-01"),
        ("May 1, 2021", "2021-05-01"),
        ("MAR 1, 2021", "2021-03-01"),
        ("1st of April, 2021", "2021-04-01"),
    ],
)
def test_date_published_parsing(unique_item_strict, raw_date, expected_date):
    """Tests parsing of various date_published string formats."""
    unique_item_strict.date_published = raw_date
    unique_item_strict.create()

    item = ItemLoose.read(unique_item_strict.url_hash)
    assert item.date_published.strftime("%Y-%m-%d") == expected_date


@pytest.mark.filterwarnings("ignore::UserWarning")
def test_bad_date_published_parsing(unique_item_strict):
    """Tests parsing of a bad date_published string."""
    unique_item_strict.date_published = "bad date"
    unique_item_strict.create()

    with pytest.raises(ValueError) as e:
        _ = ItemStrict.read(unique_item_strict.url_hash)
    assert "Invalid date format" in str(e.value)


def test_create_read_item(unique_item_strict):
    """Tests creating and reading an item."""
    unique_item_strict.create()
    item = ItemLoose.read(unique_item_strict.url_hash)
    assert item.title == unique_item_strict.title
    assert item.domain == unique_item_strict.domain
    assert item.excerpt == unique_item_strict.excerpt
    assert item.content == unique_item_strict.content


def test_update_item(unique_item_strict):
    """Tests updating an item."""
    unique_item_strict.create()
    item = ItemLoose.read(unique_item_strict.url_hash)
    item.title = "Updated title"
    item.update()

    updated_item = ItemLoose.read(unique_item_strict.url_hash)
    assert updated_item.title == "Updated title"


def test_delete_item(unique_item_strict):
    """Tests deleting an item."""
    unique_item_strict.create()
    item = ItemLoose.read(unique_item_strict.url_hash)

    assert item.exists()
    item.delete()
    assert not item.exists()


def test_overwrite_error(unique_item_strict):
    """Tests that overwriting an existing item raises an error."""
    unique_item_strict.create()
    with pytest.raises(Exception) as e:
        unique_item_strict.create(overwrite=False)
    assert "already exists" in str(
        e.value
    ), "Should not allow overwriting existing items"


def test_read_nonexistent_item(unique_item_strict):
    """Tests reading a nonexistent item."""
    item = ItemLoose.read(unique_item_strict.url_hash)
    assert item is None


def test_relative_link_sanitization(unique_item_strict):
    """Tests that relative links are sanitized."""
    unique_item_strict.content = '<a href="/example">Example</a>'
    unique_item_strict.create()

    item = ItemLoose.read(unique_item_strict.url_hash)
    assert item.content == f'<a href="{unique_item_strict.url}example">Example</a>'


def test_abs_link_preservtion(unique_item_strict):
    """Tests that relative links are sanitized."""
    unique_item_strict.content = '<a href="https://google.com">Example</a>'
    unique_item_strict.create()

    item = ItemLoose.read(unique_item_strict.url_hash)
    assert item.content == unique_item_strict.content


def test_relative_img_sanitization(unique_item_strict):
    """Tests that relative image links are sanitized."""
    unique_item_strict.content = '<img src="/example.jpg">'
    unique_item_strict.create()

    item = ItemLoose.read(unique_item_strict.url_hash)
    assert item.content == f'<img src="{unique_item_strict.url}example.jpg">'
