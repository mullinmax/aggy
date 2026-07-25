import pytest

from db.item import ItemStrict
from db.source import Source
from ingest.backends import ytdlp as ytdlp_backend
from routers import source_analyze
from tests.testing_utils import build_api_request_args


@pytest.fixture(autouse=True)
def _no_background_ingest(monkeypatch):
    """Creating a source kicks off its first ingest; nothing here is about
    that, and it would try to reach the network."""
    monkeypatch.setattr("routers.source.ingest_source_now", lambda source: None)


SELECTORS = {
    "home_page": "https://example.com/blog/",
    "entry_element_selector": "article.card",
    "title_selector": "h3",
    "url_selector": "a",
    "limit": "10",
}


def test_create_scraped_source_stores_its_selectors(
    client, existing_user, existing_feed, token
):
    args = build_api_request_args(
        path="/source/create_scraped",
        data={
            "feed_hash": existing_feed.name_hash,
            "source_name": "Example Blog",
            "parameters": SELECTORS,
            "rendered": True,
        },
        token=token,
    )

    response = client.post(**args)

    assert response.status_code == 200
    assert response.json()["source_kind"] == "html"

    stored = Source.read(
        user_hash=existing_user.name_hash,
        feed_hash=existing_feed.name_hash,
        source_hash=response.json()["source_name_hash"],
    )
    assert stored.kind == "html"
    assert stored.config["entry_element_selector"] == "article.card"
    # the page it scrapes is what gets fetched, and it must keep rendering
    assert str(stored.url) == "https://example.com/blog/"
    assert stored.config["render"] is True


def test_create_scraped_source_needs_a_page_url(
    client, existing_user, existing_feed, token
):
    args = build_api_request_args(
        path="/source/create_scraped",
        data={
            "feed_hash": existing_feed.name_hash,
            "source_name": "Example Blog",
            "parameters": {"entry_element_selector": "article.card"},
        },
        token=token,
    )

    response = client.post(**args)

    assert response.status_code == 422


def test_create_scraped_source_rejects_a_duplicate_name(
    client, existing_user, existing_feed, existing_source, token
):
    args = build_api_request_args(
        path="/source/create_scraped",
        data={
            "feed_hash": existing_feed.name_hash,
            "source_name": existing_source.name,
            "parameters": SELECTORS,
        },
        token=token,
    )

    response = client.post(**args)

    assert response.status_code == 409


def test_updating_a_scraped_source_rewrites_its_selectors(
    client, existing_user, existing_feed, token
):
    source = Source(
        user_hash=existing_user.name_hash,
        feed_hash=existing_feed.name_hash,
        name="Example Blog",
        url="https://example.com/blog/",
        kind="html",
        config={**SELECTORS, "render": True},
    )
    source.create()

    args = build_api_request_args(
        path="/source/update",
        data={
            "feed_name_hash": existing_feed.name_hash,
            "source_name_hash": source.name_hash,
            "source_name": "Example Blog",
            "parameters": {**SELECTORS, "entry_element_selector": "li.post"},
        },
        token=token,
    )

    response = client.post(**args)

    assert response.status_code == 200
    stored = Source.read(
        user_hash=existing_user.name_hash,
        feed_hash=existing_feed.name_hash,
        source_hash=source.name_hash,
    )
    assert stored.config["entry_element_selector"] == "li.post"


# ---------- detection ----------


def test_detect_offers_the_video_backend_for_a_recognized_listing(
    client, existing_user, token, monkeypatch
):
    monkeypatch.setattr(
        source_analyze,
        "detect_source_type",
        lambda url, cookie: {
            "kind": "html",
            "feed_url": None,
            "suggested_source_name": "Example Channel",
        },
    )
    monkeypatch.setattr(
        source_analyze.ytdlp,
        "is_supported",
        lambda url: {"supported": True, "extractor": "ExampleSite"},
    )

    args = build_api_request_args(
        path="/source_analyze/detect",
        data={"url": "https://videos.example.com/c/example"},
        token=token,
    )
    response = client.post(**args)

    assert response.status_code == 200
    assert response.json()["kind"] == "video"
    assert response.json()["extractor"] == "ExampleSite"
    assert response.json()["template_name_hash"]


def test_detect_prefers_a_real_feed_over_extraction(
    client, existing_user, token, monkeypatch
):
    """A feed is lighter on the site and needs no extra service."""
    monkeypatch.setattr(
        source_analyze,
        "detect_source_type",
        lambda url, cookie: {
            "kind": "feed",
            "feed_url": "https://videos.example.com/feed.xml",
            "suggested_source_name": "Example Channel",
        },
    )
    monkeypatch.setattr(
        source_analyze.ytdlp,
        "is_supported",
        lambda url: pytest.fail("should not have asked about extraction"),
    )

    args = build_api_request_args(
        path="/source_analyze/detect",
        data={"url": "https://videos.example.com/c/example"},
        token=token,
    )
    response = client.post(**args)

    assert response.json()["kind"] == "feed"


def test_detect_falls_back_to_extraction_when_the_page_cannot_be_fetched(
    client, existing_user, token, monkeypatch
):
    """Sites that refuse anonymous fetches are exactly what the video backend
    is for, so a failed fetch is not the end of the road."""

    def refuse(url, cookie):
        raise source_analyze.AnalyzeError("Couldn't fetch: 403", status_code=502)

    monkeypatch.setattr(source_analyze, "detect_source_type", refuse)
    monkeypatch.setattr(
        source_analyze.ytdlp,
        "is_supported",
        lambda url: {"supported": True, "extractor": "ExampleSite"},
    )

    args = build_api_request_args(
        path="/source_analyze/detect",
        data={"url": "https://videos.example.com/c/example"},
        token=token,
    )
    response = client.post(**args)

    assert response.status_code == 200
    assert response.json()["kind"] == "video"


def test_detect_still_reports_a_fetch_failure_when_nothing_can_read_it(
    client, existing_user, token, monkeypatch
):
    def refuse(url, cookie):
        raise source_analyze.AnalyzeError("Couldn't fetch: 403", status_code=502)

    monkeypatch.setattr(source_analyze, "detect_source_type", refuse)
    monkeypatch.setattr(
        source_analyze.ytdlp,
        "is_supported",
        lambda url: {"supported": False, "extractor": None},
    )

    args = build_api_request_args(
        path="/source_analyze/detect",
        data={"url": "https://example.com/blog"},
        token=token,
    )
    response = client.post(**args)

    assert response.status_code == 502


# ---------- stream resolution ----------


@pytest.fixture
def video_item(existing_item_strict):
    """An item as the video backend stores it: a page URL and a thumbnail,
    with no playable URL of its own."""
    existing_item_strict.update(
        media=[
            {
                "type": "stream",
                "url": str(existing_item_strict.url),
                "poster": "https://videos.example.com/thumb.jpg",
            }
        ]
    )
    return ItemStrict.read(url_hash=existing_item_strict.url_hash)


def test_stream_url_resolves_a_fresh_url_per_playback(
    client, existing_user, video_item, token, monkeypatch
):
    monkeypatch.setattr(
        ytdlp_backend,
        "resolve_stream",
        lambda url, cookie=None: {
            "url": "https://cdn.example.com/signed.mp4?expires=soon",
            "ext": "mp4",
            "height": 720,
        },
    )

    args = build_api_request_args(
        path="/item/stream_url",
        params={"item_url_hash": video_item.url_hash},
        token=token,
    )
    response = client.get(**args)

    assert response.status_code == 200
    assert response.json()["url"] == "https://cdn.example.com/signed.mp4?expires=soon"
    assert response.json()["height"] == 720


def test_stream_url_refuses_items_that_have_no_stream(
    client, existing_user, existing_item_strict, token
):
    args = build_api_request_args(
        path="/item/stream_url",
        params={"item_url_hash": existing_item_strict.url_hash},
        token=token,
    )
    response = client.get(**args)

    assert response.status_code == 422


def test_stream_url_404s_for_an_unknown_item(client, existing_user, token):
    args = build_api_request_args(
        path="/item/stream_url", params={"item_url_hash": "nope"}, token=token
    )
    response = client.get(**args)

    assert response.status_code == 404


def test_stream_url_surfaces_a_resolution_failure(
    client, existing_user, video_item, token, monkeypatch
):
    def fail(url, cookie=None):
        raise Exception("No directly playable rendition is available")

    monkeypatch.setattr(ytdlp_backend, "resolve_stream", fail)

    args = build_api_request_args(
        path="/item/stream_url",
        params={"item_url_hash": video_item.url_hash},
        token=token,
    )
    response = client.get(**args)

    assert response.status_code == 502
    assert "playable" in response.json()["detail"]
