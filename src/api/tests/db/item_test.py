from unittest.mock import MagicMock

import pytest

from config import config
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


def test_media_roundtrip(unique_item_strict):
    """Media entries survive a write/read cycle through the JSONB column."""
    media = [
        {"type": "gif", "url": "https://i.redd.it/example.mp4"},
        {"type": "image", "url": "https://i.redd.it/example.jpg"},
    ]
    unique_item_strict.media = media
    unique_item_strict.create()

    item = ItemLoose.read(unique_item_strict.url_hash)
    assert item.media == media


def test_merge_items_prefers_media(unique_item_strict):
    """Merging keeps the first non-null media list."""
    item1 = unique_item_strict.model_copy()
    item2 = unique_item_strict.model_copy()
    item2.media = [{"type": "video", "url": "https://v.redd.it/example/DASH_720.mp4"}]

    merged_item = ItemLoose.merge_instances([item1, item2])
    assert merged_item.media == item2.media


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
    """Tests parsing of a bad date_published string at write time.

    The Postgres TIMESTAMPTZ column rejects unparseable values, so the
    error surfaces on ``.create()`` rather than on ``.read()`` (which is
    where it surfaced under the previous JSON-blob storage).
    """
    unique_item_strict.date_published = "bad date"
    with pytest.raises(Exception):
        unique_item_strict.create()


def test_create_read_item(unique_item_strict):
    """Tests creating and reading an item."""
    unique_item_strict.create()
    item = ItemLoose.read(unique_item_strict.url_hash)
    assert item.title == unique_item_strict.title
    assert item.domain == unique_item_strict.domain
    assert item.excerpt == unique_item_strict.excerpt
    assert item.content == unique_item_strict.content


def test_update_item(existing_item_strict):
    """Tests updating an item."""
    item = ItemLoose.read(existing_item_strict.url_hash)
    item.title = "Updated title"
    item.update()

    updated_item = ItemLoose.read(existing_item_strict.url_hash)
    assert updated_item.title == "Updated title"


def test_delete_item(existing_item_strict):
    """Tests deleting an item."""
    assert existing_item_strict.exists()
    existing_item_strict.delete()
    assert not existing_item_strict.exists()


def test_overwrite_error(existing_item_strict):
    """Tests that overwriting an existing item raises an error."""
    with pytest.raises(Exception) as e:
        existing_item_strict.create(overwrite=False)
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


def test_embedding_prompt_truncates_to_context_window(unique_item_strict):
    """Long items are capped by characters so they can't exceed the model's
    token context window (which would make Ollama 500 on the embed call)."""
    unique_item_strict.content = "x" * 100_000
    num_ctx = 8192
    prompt = unique_item_strict.embedding_prompt(num_ctx)
    assert len(prompt) == num_ctx * ItemStrict._CHARS_PER_TOKEN


def test_embedding_prompt_leaves_short_items_untouched(unique_item_strict):
    """Items that already fit are embedded verbatim."""
    prompt = unique_item_strict.embedding_prompt(8192)
    assert prompt == str(unique_item_strict)


def test_add_embedding_expands_context_and_batch(unique_item_strict, monkeypatch):
    """add_embedding requests a context window and physical batch large enough
    for the whole prompt, so long items don't get rejected."""
    config.set("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text")
    config.set("OLLAMA_EMBEDDING_NUM_CTX", 8192)

    fake_client = MagicMock()
    fake_client.embeddings.return_value = {"embedding": [0.1, 0.2, 0.3]}
    monkeypatch.setattr("db.item.get_ollama_connection", lambda: fake_client)

    unique_item_strict.add_embedding("nomic-embed-text")

    fake_client.embeddings.assert_called_once()
    kwargs = fake_client.embeddings.call_args.kwargs
    assert kwargs["model"] == "nomic-embed-text"
    assert kwargs["options"] == {"num_ctx": 8192, "num_batch": 8192}
    assert unique_item_strict.embeddings["nomic-embed-text"] == [0.1, 0.2, 0.3]


def test_add_embedding_skips_when_already_present(unique_item_strict, monkeypatch):
    """An existing embedding for the model is not recomputed unless forced."""
    fake_client = MagicMock()
    monkeypatch.setattr("db.item.get_ollama_connection", lambda: fake_client)

    unique_item_strict.embeddings = {"nomic-embed-text": [0.0]}
    unique_item_strict.add_embedding("nomic-embed-text")

    fake_client.embeddings.assert_not_called()
