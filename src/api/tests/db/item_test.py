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


def test_add_embedding_shrinks_prompt_when_ollama_rejects_it(
    unique_item_strict, monkeypatch
):
    """The character budget is only an estimate of the token count, so a dense
    item can still overflow the window. Halve and retry rather than leave the
    item permanently unembedded."""
    config.set("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text")
    config.set("OLLAMA_EMBEDDING_NUM_CTX", 8192)

    prompts = []

    def embeddings(model, prompt, options):
        prompts.append(prompt)
        if len(prompts) < 3:
            raise RuntimeError(
                "the input length exceeds the context length (status code: 500)"
            )
        return {"embedding": [0.4]}

    fake_client = MagicMock()
    fake_client.embeddings.side_effect = embeddings
    monkeypatch.setattr("db.item.get_ollama_connection", lambda: fake_client)

    unique_item_strict.add_embedding("nomic-embed-text")

    assert len(prompts[1]) == len(prompts[0]) // 2
    assert len(prompts[2]) == len(prompts[1]) // 2
    assert unique_item_strict.embeddings["nomic-embed-text"] == [0.4]


def test_add_embedding_does_not_retry_unrelated_errors(unique_item_strict, monkeypatch):
    """Only an over-long prompt is worth shrinking; a model that isn't pulled
    or a service that's down should surface immediately."""
    config.set("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text")
    config.set("OLLAMA_EMBEDDING_NUM_CTX", 8192)

    fake_client = MagicMock()
    fake_client.embeddings.side_effect = RuntimeError("model not found")
    monkeypatch.setattr("db.item.get_ollama_connection", lambda: fake_client)

    with pytest.raises(RuntimeError, match="model not found"):
        unique_item_strict.add_embedding("nomic-embed-text")

    fake_client.embeddings.assert_called_once()


def test_add_embedding_gives_up_after_shrinking(unique_item_strict, monkeypatch):
    """An item that never fits raises rather than looping forever."""
    config.set("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text")
    config.set("OLLAMA_EMBEDDING_NUM_CTX", 8192)

    fake_client = MagicMock()
    fake_client.embeddings.side_effect = RuntimeError(
        "the input length exceeds the context length"
    )
    monkeypatch.setattr("db.item.get_ollama_connection", lambda: fake_client)

    with pytest.raises(RuntimeError):
        unique_item_strict.add_embedding("nomic-embed-text")

    assert (
        fake_client.embeddings.call_count == ItemStrict._EMBEDDING_SHRINK_ATTEMPTS + 1
    )


def test_add_embedding_skips_when_already_present(unique_item_strict, monkeypatch):
    """An existing embedding for the model is not recomputed unless forced."""
    fake_client = MagicMock()
    monkeypatch.setattr("db.item.get_ollama_connection", lambda: fake_client)

    unique_item_strict.embeddings = {"nomic-embed-text": [0.0]}
    unique_item_strict.add_embedding("nomic-embed-text")

    fake_client.embeddings.assert_not_called()


@pytest.fixture
def image_embed_configured():
    """Point the image embedder at a (fake) service for the duration of a test."""
    config.set("IMAGE_EMBED_HOST", "image-embed")
    config.set("IMAGE_EMBED_PORT", 8000)
    config.set("IMAGE_EMBED_MODEL", "clip-model")
    config.set("IMAGE_EMBED_TIMEOUT_SECONDS", 30)
    yield
    for key in (
        "IMAGE_EMBED_HOST",
        "IMAGE_EMBED_PORT",
        "IMAGE_EMBED_MODEL",
        "IMAGE_EMBED_TIMEOUT_SECONDS",
    ):
        config.config.pop(key, None)


def _fake_post(embedding):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"model": "clip-model", "embedding": embedding}
    return MagicMock(return_value=resp)


def test_add_image_embedding_fetches_and_embeds(
    unique_item_strict, image_embed_configured, monkeypatch
):
    """The preview image is downloaded, sent to the CLIP service, and stored in
    image_embeddings (kept separate from the text embeddings)."""
    monkeypatch.setattr(
        "db.item.ItemBase._fetch_image_base64", staticmethod(lambda url: "aGVsbG8=")
    )
    post = _fake_post([0.4, 0.5, 0.6])
    monkeypatch.setattr("db.item.httpx.post", post)

    unique_item_strict.add_image_embedding("clip-model")

    post.assert_called_once()
    args, kwargs = post.call_args
    assert args[0] == "http://image-embed:8000/embed"
    assert kwargs["json"] == {"image_base64": "aGVsbG8="}
    assert unique_item_strict.image_embeddings["clip-model"] == [0.4, 0.5, 0.6]
    # text embeddings are untouched by the image embedder
    assert not unique_item_strict.embeddings


def test_add_image_embedding_noop_without_service(unique_item_strict, monkeypatch):
    """With no service configured, nothing is fetched or embedded."""
    config.config.pop("IMAGE_EMBED_HOST", None)
    post = MagicMock()
    monkeypatch.setattr("db.item.httpx.post", post)

    unique_item_strict.add_image_embedding("clip-model")

    post.assert_not_called()
    assert unique_item_strict.image_embeddings is None


def test_add_image_embedding_noop_without_image(
    unique_item_strict, image_embed_configured, monkeypatch
):
    """No image URL means nothing is fetched or embedded."""
    post = MagicMock()
    monkeypatch.setattr("db.item.httpx.post", post)

    unique_item_strict.image_url = None
    unique_item_strict.add_image_embedding("clip-model")

    post.assert_not_called()
    assert unique_item_strict.image_embeddings is None


def test_add_image_embedding_skips_when_already_present(
    unique_item_strict, image_embed_configured, monkeypatch
):
    """An existing image embedding for the model is not recomputed unless forced."""
    post = MagicMock()
    monkeypatch.setattr("db.item.httpx.post", post)

    unique_item_strict.image_embeddings = {"clip-model": [0.0]}
    unique_item_strict.add_image_embedding("clip-model")

    post.assert_not_called()


def test_add_image_embedding_falls_back_to_content_image(
    unique_item_strict, image_embed_configured, monkeypatch
):
    """An item with no image_url still gets embedded from the first image in its
    content — the same picture the UI shows on the card. Reddit RSS entries only
    carry their thumbnail there when the post JSON couldn't be fetched."""
    fetched = []
    monkeypatch.setattr(
        "db.item.ItemBase._fetch_image_base64",
        staticmethod(lambda url: fetched.append(url) or "aGVsbG8="),
    )
    monkeypatch.setattr("db.item.httpx.post", _fake_post([0.7]))

    unique_item_strict.image_url = None
    unique_item_strict.content = '<p>hi</p><img src="https://preview.redd.it/a.jpg">'
    unique_item_strict.add_image_embedding("clip-model")

    assert fetched == ["https://preview.redd.it/a.jpg"]
    assert unique_item_strict.image_embeddings["clip-model"] == [0.7]
    # the fallback is for embedding only; the column the reader uses to decide
    # whether to promote a content image into the hero slot stays untouched
    assert unique_item_strict.image_url is None


def test_add_image_embedding_retries_unsigned_reddit_url(
    unique_item_strict, image_embed_configured, monkeypatch
):
    """When reddit's signed preview host refuses the download, the same asset is
    retried on the unsigned i.redd.it path."""
    attempted = []

    def fake_fetch(url):
        attempted.append(url)
        if "preview.redd.it" in url:
            raise ValueError("403")
        return "aGVsbG8="

    monkeypatch.setattr(
        "db.item.ItemBase._fetch_image_base64", staticmethod(fake_fetch)
    )
    monkeypatch.setattr("db.item.httpx.post", _fake_post([0.8]))

    unique_item_strict.image_url = "https://preview.redd.it/a.jpg?width=640&s=sig"
    unique_item_strict.add_image_embedding("clip-model")

    assert attempted == [
        "https://preview.redd.it/a.jpg?width=640&s=sig",
        "https://i.redd.it/a.jpg",
    ]
    assert unique_item_strict.image_embeddings["clip-model"] == [0.8]


def test_add_image_embedding_retries_html_escaped_url(
    unique_item_strict, image_embed_configured, monkeypatch
):
    """A stored URL that still carries &amp; entities is retried unescaped —
    reddit signs its preview URLs over the query string, so the escaped form is
    rejected."""
    attempted = []

    def fake_fetch(url):
        attempted.append(url)
        if "&amp;" in url:
            raise ValueError("403")
        return "aGVsbG8="

    monkeypatch.setattr(
        "db.item.ItemBase._fetch_image_base64", staticmethod(fake_fetch)
    )
    monkeypatch.setattr("db.item.httpx.post", _fake_post([0.9]))

    unique_item_strict.image_url = "https://example.com/a.jpg?w=1&amp;s=sig"
    unique_item_strict.add_image_embedding("clip-model")

    assert attempted == [
        "https://example.com/a.jpg?w=1&amp;s=sig",
        "https://example.com/a.jpg?w=1&s=sig",
    ]
    assert unique_item_strict.image_embeddings["clip-model"] == [0.9]


def test_add_image_embedding_gives_up_after_all_candidates(
    unique_item_strict, image_embed_configured, monkeypatch
):
    """When every candidate URL fails, nothing is sent to the embedding service
    and no embedding is recorded."""
    monkeypatch.setattr(
        "db.item.ItemBase._fetch_image_base64",
        staticmethod(lambda url: (_ for _ in ()).throw(ValueError("403"))),
    )
    post = MagicMock()
    monkeypatch.setattr("db.item.httpx.post", post)

    unique_item_strict.image_url = "https://preview.redd.it/a.jpg?s=sig"
    unique_item_strict.add_image_embedding("clip-model")

    post.assert_not_called()
    assert unique_item_strict.image_embeddings == {}


def test_fetch_image_sends_browser_user_agent(
    unique_item_strict, image_embed_configured, monkeypatch
):
    """Preview images are downloaded with a browser user agent: reddit's image
    CDN answers httpx's default agent with a 403, which is why the picture
    rendered in the page but never reached the embedding service."""
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.headers = {"content-type": "image/jpeg"}
    resp.content = b"hello"
    get = MagicMock(return_value=resp)
    monkeypatch.setattr("db.item.httpx.get", get)

    assert ItemStrict._fetch_image_base64("https://preview.redd.it/a.jpg") == "aGVsbG8="

    headers = get.call_args.kwargs["headers"]
    assert "Mozilla/5.0" in headers["User-Agent"]
    assert "python-httpx" not in headers["User-Agent"]


def test_fetch_image_rejects_non_image_response(
    unique_item_strict, image_embed_configured, monkeypatch
):
    """A host that refuses the request with a 200 HTML notice is treated as a
    failed fetch rather than fed to the embedding service as garbage."""
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.headers = {"content-type": "text/html; charset=utf-8"}
    resp.content = b"<html>Forbidden</html>"
    monkeypatch.setattr("db.item.httpx.get", MagicMock(return_value=resp))

    with pytest.raises(ValueError, match="text/html"):
        ItemStrict._fetch_image_base64("https://preview.redd.it/a.jpg")
