import pytest

from db.item import ItemLoose
from db.source import Source
from ingest import source as ingest_source_module
from ingest.backends import UNSCHEDULED_KINDS, get_backend
from ingest.backends import html as html_backend
from ingest.backends import rss as rss_backend
from ingest.backends import ytdlp as ytdlp_backend


def test_get_backend_rejects_unknown_kind():
    with pytest.raises(Exception, match="Unknown source kind"):
        get_backend("carrier-pigeon")


def test_rss_stays_the_default_backend():
    assert get_backend("rss").enrich is True


def test_manual_sources_are_never_polled():
    """A saved-links source has no URL to fetch; queueing it would only mark
    it failed for returning no entries."""
    assert get_backend("manual").scheduled is False
    assert "manual" in UNSCHEDULED_KINDS
    assert get_backend("rss").scheduled is True
    assert UNSCHEDULED_KINDS == ["manual"]


def test_video_backend_skips_per_item_scraping():
    """Its listings already carry title/thumbnail/uploader, and the sites it
    reaches refuse the anonymous fetches the scrapers would make."""
    assert get_backend("ytdlp").enrich is False


# ---------- video listings ----------


SIDECAR_ENTRY = {
    "url": "https://videos.example.com/watch/abc123",
    "title": "An example upload",
    "uploader": "Example Channel",
    "thumbnail": "https://videos.example.com/thumbs/abc123.jpg",
    "duration": 615,
    "timestamp": 1767225600,
    "view_count": 4096,
}


def test_entry_to_item_maps_listing_metadata():
    item = ytdlp_backend.entry_to_item(SIDECAR_ENTRY)

    assert str(item.url) == SIDECAR_ENTRY["url"]
    assert item.title == "An example upload"
    assert item.author == "Example Channel"
    assert item.image_url == SIDECAR_ENTRY["thumbnail"]
    assert item.domain == "videos.example.com"
    assert item.date_published.year == 2026
    # a listing pass has no description, so the title stands in for the body
    # that ItemStrict requires
    assert item.excerpt == "An example upload"


def test_entry_to_item_stores_a_resolvable_stream_not_a_url():
    """A stored media URL would be a signed URL that expires within hours, so
    the item keeps its page URL and is resolved per playback instead."""
    item = ytdlp_backend.entry_to_item(SIDECAR_ENTRY)

    assert item.media == [
        {
            "type": "stream",
            "url": SIDECAR_ENTRY["url"],
            "poster": SIDECAR_ENTRY["thumbnail"],
        }
    ]


def test_entry_to_item_falls_back_to_upload_date():
    item = ytdlp_backend.entry_to_item(
        {**SIDECAR_ENTRY, "timestamp": None, "upload_date": "20260114"}
    )

    assert (item.date_published.year, item.date_published.month) == (2026, 1)


def test_entry_to_item_drops_entries_without_a_url():
    assert ytdlp_backend.entry_to_item({"title": "no link"}) is None


class _FakeResponse:
    def __init__(self, payload, status_code=200, text=""):
        self._payload = payload
        self.status_code = status_code
        self.text = text

    def json(self):
        return self._payload


def _video_source(**kwargs) -> Source:
    return Source(
        user_hash="user",
        feed_hash="feed",
        name="Example listing",
        url="https://videos.example.com/channel/example",
        kind="ytdlp",
        **kwargs,
    )


def test_video_backend_asks_the_sidecar_for_the_listing(monkeypatch):
    monkeypatch.setattr(ytdlp_backend, "is_configured", lambda: True)
    monkeypatch.setattr(ytdlp_backend.config, "get", lambda key, default=None: "svc")

    captured = {}

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        return _FakeResponse({"entries": [SIDECAR_ENTRY]})

    monkeypatch.setattr(ytdlp_backend.requests, "post", fake_post)

    items = ytdlp_backend.fetch_items(_video_source(config={"limit": 5}))

    assert captured["url"].endswith("/extract")
    assert captured["json"]["url"] == "https://videos.example.com/channel/example"
    assert captured["json"]["limit"] == 5
    assert [item.title for item in items] == ["An example upload"]


def test_video_backend_explains_an_unconfigured_service(monkeypatch):
    monkeypatch.setattr(ytdlp_backend, "is_configured", lambda: False)

    with pytest.raises(Exception, match="aggy-ytdlp"):
        ytdlp_backend.fetch_items(_video_source())


def test_video_backend_rejects_a_page_with_no_entries(monkeypatch):
    monkeypatch.setattr(ytdlp_backend, "is_configured", lambda: True)
    monkeypatch.setattr(ytdlp_backend.config, "get", lambda key, default=None: "svc")
    monkeypatch.setattr(
        ytdlp_backend.requests, "post", lambda *a, **kw: _FakeResponse({"entries": []})
    )

    with pytest.raises(Exception, match="No entries found"):
        ytdlp_backend.fetch_items(_video_source())


def test_is_supported_says_no_without_the_service(monkeypatch):
    monkeypatch.setattr(ytdlp_backend, "is_configured", lambda: False)

    assert ytdlp_backend.is_supported("https://videos.example.com/x") == {
        "supported": False,
        "extractor": None,
    }


# ---------- scraped pages ----------


LISTING_HTML = """
<html><body>
  <div class="feed">
    <article class="card">
      <a class="link" href="/posts/one"><h3>First post</h3></a>
      <img data-src="/thumbs/one.jpg" src="data:image/gif;base64,placeholder">
      <span class="by">Alice</span>
    </article>
    <article class="card">
      <a class="link" href="/posts/two"><h3>Second post</h3></a>
      <img src="https://cdn.example.com/two.jpg">
      <span class="by">Bob</span>
    </article>
  </div>
</body></html>
"""

SELECTORS = {
    "entry_element_selector": "article.card",
    "title_selector": "h3",
    "url_selector": "a.link",
    "author_selector": "span.by",
}


def _scraped_source(config) -> Source:
    return Source(
        user_hash="user",
        feed_hash="feed",
        name="Example page",
        url="https://example.com/blog/",
        kind="html",
        config=config,
    )


def test_scraped_backend_renders_when_the_source_says_so(monkeypatch):
    rendered_for = []

    def fake_render(url, cookie=""):
        rendered_for.append((url, cookie))
        return LISTING_HTML

    monkeypatch.setattr(html_backend, "render_page", fake_render)

    items = html_backend.fetch_items(
        _scraped_source({**SELECTORS, "render": True, "cookie": "age=1"})
    )

    assert rendered_for == [("https://example.com/blog/", "age=1")]
    assert [item.title for item in items] == ["First post", "Second post"]
    # relative hrefs are resolved against the page
    assert str(items[0].url) == "https://example.com/posts/one"
    assert items[0].author == "Alice"


def test_scraped_backend_fetches_plainly_when_rendering_is_off(monkeypatch):
    monkeypatch.setattr(html_backend, "fetch_page", lambda url, cookie="": LISTING_HTML)
    monkeypatch.setattr(
        html_backend,
        "render_page",
        lambda *a, **kw: pytest.fail("should not have rendered"),
    )

    items = html_backend.fetch_items(_scraped_source(SELECTORS))

    assert len(items) == 2


def test_scraped_backend_reports_selectors_that_stopped_matching(monkeypatch):
    monkeypatch.setattr(
        html_backend, "fetch_page", lambda url, cookie="": "<html><body></body></html>"
    )

    with pytest.raises(Exception, match="no entries matching"):
        html_backend.fetch_items(_scraped_source(SELECTORS))


# ---------- the shared pipeline ----------


def test_ingest_source_uses_the_backend_named_by_the_source(
    monkeypatch, existing_source
):
    """The pipeline dispatches on the source's kind rather than assuming RSS."""
    existing_source.kind = "ytdlp"
    called = []

    def fake_fetch(source):
        called.append(source.name)
        return [
            ItemLoose(
                url="https://videos.example.com/watch/xyz",
                title="Fetched by the video backend",
                domain="videos.example.com",
                excerpt="x",
                content="x",
            )
        ]

    monkeypatch.setattr(ytdlp_backend, "fetch_items", fake_fetch)
    # no embedding services configured in this test run
    monkeypatch.setattr(
        ingest_source_module.config, "get", lambda key, default=None: default
    )

    ingest_source_module.ingest_source(existing_source)

    assert called == [existing_source.name]
    assert [item.title for item in existing_source.query_items()] == [
        "Fetched by the video backend"
    ]


def test_ingest_source_skips_scraping_for_backends_that_dont_want_it(
    monkeypatch, existing_source
):
    existing_source.kind = "ytdlp"
    monkeypatch.setattr(
        ytdlp_backend,
        "fetch_items",
        lambda source: [
            ItemLoose(
                url="https://videos.example.com/watch/xyz",
                title="Already complete",
                domain="videos.example.com",
                excerpt="x",
                content="x",
            )
        ],
    )
    monkeypatch.setattr(
        ingest_source_module.config, "get", lambda key, default=None: default
    )
    for scraper in ("ingest_open_graph_item", "ingest_mercury_item"):
        monkeypatch.setattr(
            ingest_source_module,
            scraper,
            lambda item: pytest.fail("enrichment should be skipped"),
        )

    ingest_source_module.ingest_source(existing_source)

    assert len(existing_source.query_items()) == 1


def test_ingest_source_attaches_an_item_another_source_already_stored(
    monkeypatch, existing_source, unique_item_strict
):
    """Items are shared across sources, so one already in the table still has
    to be attached here — it used to be dropped as a failed insert, leaving
    the second source's feed empty."""
    unique_item_strict.create()
    assert existing_source.query_items() == []

    monkeypatch.setattr(
        rss_backend,
        "fetch_items",
        lambda source: [ItemLoose(url=str(unique_item_strict.url))],
    )
    monkeypatch.setattr(
        ingest_source_module.config, "get", lambda key, default=None: default
    )
    for scraper in ("ingest_open_graph_item", "ingest_mercury_item"):
        monkeypatch.setattr(ingest_source_module, scraper, lambda item: None)

    ingest_source_module.ingest_source(existing_source)

    assert [str(i.url) for i in existing_source.query_items()] == [
        str(unique_item_strict.url)
    ]


# ---------- surfacing why a feed failed ----------


class _ErrorResponse:
    def __init__(self, status_code, text, content_type="text/html"):
        self.status_code = status_code
        self.text = text
        self.content = text.encode()
        self.headers = {"Content-Type": content_type}


def test_a_failed_feed_quotes_what_the_server_said(monkeypatch):
    """ "HTTP 503" alone tells a user nothing; bridges put the actual reason
    in the body."""
    monkeypatch.setattr(
        rss_backend.requests,
        "get",
        lambda *a, **kw: _ErrorResponse(
            503, "<html><body><p>this route is empty</p></body></html>"
        ),
    )

    with pytest.raises(Exception, match="this route is empty"):
        rss_backend.fetch_items(
            Source(
                user_hash="user",
                feed_hash="feed",
                name="Example",
                url="http://bridge.local/some/route",
            )
        )


def test_a_failed_feed_with_an_empty_body_still_reports_its_status(monkeypatch):
    monkeypatch.setattr(
        rss_backend.requests, "get", lambda *a, **kw: _ErrorResponse(502, "   ")
    )

    with pytest.raises(Exception, match="HTTP 502"):
        rss_backend.fetch_items(
            Source(
                user_hash="user",
                feed_hash="feed",
                name="Example",
                url="http://bridge.local/some/route",
            )
        )


def test_a_bridge_error_page_is_reduced_to_its_error_line(monkeypatch):
    """Bridges answer with a whole error page — greeting, apology, node
    version, git hash. Only the labelled line is worth showing."""
    monkeypatch.setattr(
        rss_backend.requests,
        "get",
        lambda *a, **kw: _ErrorResponse(
            503,
            "<html><body>"
            "<h1>Welcome to the bridge!</h1><p>Looks like something went wrong</p>"
            "<p>Helpful Information</p>"
            "<p>Error Message: TypeError: Cannot read properties of undefined</p>"
            "<p>Route: /example/category/:cat</p>"
            "<p>Node Version: v24.18.0</p>"
            "<p>Git Hash: c0825f01</p>"
            "</body></html>",
        ),
    )

    with pytest.raises(Exception) as failure:
        rss_backend.fetch_items(
            Source(
                user_hash="user",
                feed_hash="feed",
                name="Example",
                url="http://bridge.local/example/category/public",
            )
        )

    message = str(failure.value)
    assert "TypeError: Cannot read properties of undefined" in message
    assert "Welcome to the bridge" not in message
    assert "Node Version" not in message


def test_an_unlabelled_error_body_is_quoted_as_is(monkeypatch):
    monkeypatch.setattr(
        rss_backend.requests,
        "get",
        lambda *a, **kw: _ErrorResponse(500, "upstream refused the connection"),
    )

    with pytest.raises(Exception, match="upstream refused the connection"):
        rss_backend.fetch_items(
            Source(
                user_hash="user",
                feed_hash="feed",
                name="Example",
                url="http://bridge.local/some/route",
            )
        )


# ---------- filling in what a listing pass didn't carry ----------


def _new_video_item() -> ItemLoose:
    return ItemLoose(
        url="https://videos.example.com/watch/abc123",
        title="An example upload",
        domain="videos.example.com",
        excerpt="An example upload",
        content="An example upload",
        media=[{"type": "stream", "url": "https://videos.example.com/watch/abc123"}],
    )


def test_a_new_item_without_a_thumbnail_is_looked_up(monkeypatch):
    """Flat extraction is cheap because it never visits the items, so on many
    sites an entry arrives with no picture at all."""
    monkeypatch.setattr(ytdlp_backend, "is_configured", lambda: True)
    monkeypatch.setattr(ytdlp_backend.config, "get", lambda key, default=None: "svc")

    captured = {}

    def fake_post(url, json, timeout):
        captured["url"] = url
        return _FakeResponse(
            {
                "thumbnail": "https://videos.example.com/thumbs/abc123.jpg",
                "description": "A much better description",
                "timestamp": 1767225600,
            }
        )

    monkeypatch.setattr(ytdlp_backend.requests, "post", fake_post)

    enriched = ytdlp_backend.enrich_item(_new_video_item())

    assert captured["url"].endswith("/metadata")
    assert enriched.image_url == "https://videos.example.com/thumbs/abc123.jpg"
    # the player's poster is the same picture; without it the frame is blank
    assert enriched.media[0]["poster"] == "https://videos.example.com/thumbs/abc123.jpg"
    assert enriched.excerpt == "A much better description"
    assert enriched.date_published.year == 2026


def test_an_item_that_already_has_a_thumbnail_is_left_alone(monkeypatch):
    monkeypatch.setattr(ytdlp_backend, "is_configured", lambda: True)
    monkeypatch.setattr(
        ytdlp_backend.requests,
        "post",
        lambda *a, **kw: pytest.fail("should not have looked anything up"),
    )

    item = _new_video_item().model_copy(
        update={"image_url": "https://videos.example.com/from-the-listing.jpg"}
    )

    assert ytdlp_backend.enrich_item(item) is None


def test_a_failed_lookup_keeps_the_item_as_it_was(monkeypatch):
    monkeypatch.setattr(ytdlp_backend, "is_configured", lambda: True)
    monkeypatch.setattr(ytdlp_backend.config, "get", lambda key, default=None: "svc")
    monkeypatch.setattr(
        ytdlp_backend.requests,
        "post",
        lambda *a, **kw: _FakeResponse({}, status_code=422, text="no metadata"),
    )

    assert ytdlp_backend.enrich_item(_new_video_item()) is None


def test_the_pipeline_only_enriches_items_it_has_not_seen(
    monkeypatch, existing_source, unique_item_strict
):
    """The visit costs a request per article, so it happens once — not on
    every check of the listing."""
    unique_item_strict.create()
    existing_source.kind = "ytdlp"

    monkeypatch.setattr(
        ytdlp_backend,
        "fetch_items",
        lambda source: [ItemLoose(url=str(unique_item_strict.url))],
    )
    monkeypatch.setattr(
        ytdlp_backend,
        "enrich_item",
        lambda item: pytest.fail("a stored item should not be looked up again"),
    )
    monkeypatch.setattr(
        ingest_source_module.config, "get", lambda key, default=None: default
    )

    ingest_source_module.ingest_source(existing_source)


def test_a_backend_without_the_hook_is_fine(monkeypatch, existing_source):
    """Only some backends have anything to add."""
    assert get_backend("rss").enrich_item(_new_video_item()) is None
