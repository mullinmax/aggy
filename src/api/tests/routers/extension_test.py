import pytest

from builtin_templates import builtin_template
from db.item import ItemLoose
from db.item_state import ItemState
from db.source import Source
from tests.testing_utils import build_api_request_args


@pytest.fixture
def reddit_templates():
    """The built-in reddit templates, as the start-up seeding job stores them."""
    templates = [
        builtin_template("Reddit Subreddit"),
        builtin_template("Reddit User"),
    ]
    for template in templates:
        template.create()
    yield templates
    for template in templates:
        template.delete()


def _no_network(monkeypatch):
    """Keep recommendation off the network: no fetches, no extractor, no model."""
    monkeypatch.setattr(
        "bridge.recommend.detect_source_type",
        lambda url, cookie="": {
            "kind": "html",
            "feed_url": None,
            "suggested_source_name": "Example",
        },
    )
    monkeypatch.setattr(
        "bridge.recommend.ytdlp.is_supported",
        lambda url: {"supported": False, "extractor": None},
    )
    monkeypatch.setattr(
        "bridge.recommend._model_template_option", lambda url, title: (None, None)
    )


def test_recommend_prefers_the_reddit_template(
    client, token, reddit_templates, monkeypatch
):
    _no_network(monkeypatch)

    args = build_api_request_args(
        path="/extension/recommend",
        token=token,
        data={"url": "https://www.reddit.com/r/selfhosted/"},
    )
    response = client.post(**args)

    assert response.status_code == 200
    options = response.json()["options"]

    first = options[0]
    assert first["strategy"] == "template"
    assert first["confidence"] == "high"
    assert first["template_parameters"] == {"subreddit": "selfhosted"}
    assert first["suggested_source_name"] == "r/selfhosted"

    # the generic fallback is always offered, and always last
    assert options[-1]["strategy"] == "scrape"
    assert options[-1]["requires_analysis"] is True


def test_recommend_offers_feeds_the_browser_found(client, token, monkeypatch):
    _no_network(monkeypatch)

    args = build_api_request_args(
        path="/extension/recommend",
        token=token,
        data={
            "url": "https://example.com/blog/",
            "page_title": "Example Blog | Posts",
            "page_feeds": [
                "https://example.com/feed.xml",
                "not-a-url",
                "https://example.com/feed.xml",
            ],
        },
    )
    response = client.post(**args)

    assert response.status_code == 200
    options = response.json()["options"]

    # the malformed and the duplicate entry are both dropped
    feed_options = [o for o in options if o["strategy"] == "rss"]
    assert [o["feed_url"] for o in feed_options] == ["https://example.com/feed.xml"]
    assert feed_options[0]["suggested_source_name"] == "Example Blog"


def test_recommend_rejects_a_non_http_url(client, token):
    args = build_api_request_args(
        path="/extension/recommend",
        token=token,
        data={"url": "chrome://extensions"},
    )
    assert client.post(**args).status_code == 422


def test_create_source_from_a_template_option(
    client, token, existing_feed, reddit_templates, monkeypatch
):
    # a freshly created source is ingested in the background; that would go to
    # the network, and this test is about what got stored
    monkeypatch.setattr("routers.extension.ingest_source_now", lambda source: None)

    template = reddit_templates[0]
    args = build_api_request_args(
        path="/extension/create_source",
        token=token,
        data={
            "feed_hash": existing_feed.name_hash,
            "source_name": "r/selfhosted",
            "option": {
                "strategy": "template",
                "label": "Follow r/selfhosted",
                "reason": "It's a subreddit",
                "confidence": "high",
                "suggested_source_name": "r/selfhosted",
                "template_name_hash": template.name_hash,
                "template_parameters": {"subreddit": "selfhosted"},
            },
        },
    )
    response = client.post(**args)

    assert response.status_code == 200
    source = Source.read(
        user_hash=existing_feed.user_hash,
        feed_hash=existing_feed.name_hash,
        source_hash=response.json()["source_name_hash"],
    )
    assert str(source.url) == template.create_rss_url(subreddit="selfhosted")
    assert source.template_parameters == {"subreddit": "selfhosted"}
    assert source.kind == "rss"


def test_create_scraped_source_keeps_the_shared_cookie(
    client, token, existing_feed, monkeypatch
):
    monkeypatch.setattr("routers.extension.ingest_source_now", lambda source: None)

    args = build_api_request_args(
        path="/extension/create_source",
        token=token,
        data={
            "feed_hash": existing_feed.name_hash,
            "source_name": "Example Blog",
            "cookie": "session=abc",
            "rendered": True,
            "parameters": {
                "home_page": "https://example.com/blog/",
                "entry_element_selector": "div.post",
            },
            "option": {
                "strategy": "scrape",
                "label": "Build a feed from this page",
                "reason": "No feed here",
                "confidence": "low",
                "suggested_source_name": "Example Blog",
                "requires_analysis": True,
            },
        },
    )
    response = client.post(**args)

    assert response.status_code == 200
    source = Source.read(
        user_hash=existing_feed.user_hash,
        feed_hash=existing_feed.name_hash,
        source_hash=response.json()["source_name_hash"],
    )
    assert source.kind == "html"
    # the cookie is stored on the source, so later ingests fetch the page the
    # same way the preview did
    assert source.config["cookie"] == "session=abc"
    assert source.config["render"] is True


def _stub_extractors(monkeypatch):
    """No network for the per-item scrapers; the browser's values stand alone."""
    monkeypatch.setattr("routers.extension.ingest_open_graph_item", lambda item: None)
    monkeypatch.setattr("routers.extension.ingest_mercury_item", lambda item: None)
    monkeypatch.setattr("routers.extension.ingest_reddit_item", lambda item: None)


def test_save_item_files_it_under_saved_links(
    client, token, existing_feed, monkeypatch
):
    _stub_extractors(monkeypatch)

    args = build_api_request_args(
        path="/extension/save_item",
        token=token,
        data={
            "url": "https://example.com/posts/one",
            "feed_hash": existing_feed.name_hash,
            "title": "One good post",
            "excerpt": "The post's own summary",
            "score": 1,
        },
    )
    response = client.post(**args)

    assert response.status_code == 200
    body = response.json()
    assert body["created"] is True
    assert body["source_name"] == "Saved Links"
    assert body["item"]["title"] == "One good post"

    # it is a real item in the feed, attributed to a source nothing polls
    source = Source.read(
        user_hash=existing_feed.user_hash,
        feed_hash=existing_feed.name_hash,
        source_hash=body["source_name_hash"],
    )
    assert source.kind == "manual"
    assert [str(i.url) for i in source.query_items()] == [
        "https://example.com/posts/one"
    ]
    assert body["item_hash"] in existing_feed.item_url_hashes()

    # and the vote landed with it
    state = ItemState.read(
        existing_feed.user_hash, existing_feed.name_hash, body["item_hash"]
    )
    assert state.score == 1


def test_saving_the_same_page_twice_refiles_it(
    client, token, existing_feed, monkeypatch
):
    _stub_extractors(monkeypatch)

    data = {
        "url": "https://example.com/posts/one",
        "feed_hash": existing_feed.name_hash,
        "title": "One good post",
    }
    first = client.post(
        **build_api_request_args(path="/extension/save_item", token=token, data=data)
    )
    second = client.post(
        **build_api_request_args(
            path="/extension/save_item", token=token, data={**data, "score": -1}
        )
    )

    assert first.json()["created"] is True
    # the second save is not an error, and the vote it carries still applies
    assert second.status_code == 200
    assert second.json()["created"] is False
    state = ItemState.read(
        existing_feed.user_hash, existing_feed.name_hash, second.json()["item_hash"]
    )
    assert state.score == -1


def test_save_item_needs_a_feed_that_exists(client, token, monkeypatch):
    _stub_extractors(monkeypatch)

    args = build_api_request_args(
        path="/extension/save_item",
        token=token,
        data={"url": "https://example.com/posts/one", "feed_hash": "nope"},
    )
    assert client.post(**args).status_code == 404


def test_status_reports_saved_items_and_followed_sites(
    client, token, existing_feed, monkeypatch
):
    _stub_extractors(monkeypatch)
    monkeypatch.setattr("routers.extension.ingest_source_now", lambda source: None)

    client.post(
        **build_api_request_args(
            path="/extension/save_item",
            token=token,
            data={
                "url": "https://example.com/posts/one",
                "feed_hash": existing_feed.name_hash,
                "title": "One good post",
                "score": 1,
            },
        )
    )
    existing_feed.add_source(
        Source(
            user_hash=existing_feed.user_hash,
            feed_hash=existing_feed.name_hash,
            name="Example Blog",
            url="https://www.example.com/feed.xml",
        )
    )

    args = build_api_request_args(
        path="/extension/status",
        token=token,
        params={"url": "https://example.com/posts/one"},
    )
    response = client.get(**args)

    assert response.status_code == 200
    body = response.json()
    assert body["item_saved"] is True
    assert body["item_hash"] == ItemLoose(url="https://example.com/posts/one").url_hash
    assert body["item_feeds"][0]["feed_name"] == existing_feed.name
    assert body["item_feeds"][0]["score"] == 1
    # the www. of the source and the bare host of the page are the same site
    assert [s["source_name"] for s in body["site_sources"]] == ["Example Blog"]


def test_status_on_an_unknown_page(client, token):
    args = build_api_request_args(
        path="/extension/status",
        token=token,
        params={"url": "https://elsewhere.example/nothing"},
    )
    response = client.get(**args)

    assert response.status_code == 200
    assert response.json() == {
        "item_saved": False,
        "item_hash": None,
        "item_feeds": [],
        "site_sources": [],
    }


def test_extension_routes_require_a_token(client):
    assert client.get("/extension/status?url=https://example.com").status_code == 401
    assert (
        client.post(
            "/extension/save_item", json={"url": "x", "feed_hash": "y"}
        ).status_code
        == 401
    )
