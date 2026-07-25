import time

import pytest

from tests.testing_utils import build_api_request_args
from tests.bridge.analyze_test import SAMPLE_HTML, RAW_SUGGESTIONS

from bridge.analyze import AnalyzeError

from db.source_template import SourceTemplate, SourceTemplateParameter


@pytest.fixture
def css_selector_template():
    """The rss-bridge CSS Selector Complex template as the catalog job stores it."""

    def param(name, required=False):
        return SourceTemplateParameter(name=name, required=required, type="text")

    template = SourceTemplate(
        name="CSS Selector Complex",
        bridge_short_name="CssSelectorComplexBridge",
        url="http://example.com",
        description="Convert any site to RSS feed using CSS selectors",
        parameters={
            "home_page": param("Site URL", required=True),
            "cookie": param("Cookie"),
            "entry_element_selector": param("Entry selector", required=True),
            "url_selector": param("URL selector"),
            "title_selector": param("Title selector"),
            "author_selector": param("Author selector"),
            "time_selector": param("Time selector"),
            "time_format": param("Time format"),
            "limit": param("Limit"),
        },
    )
    template.create()
    yield template
    template.delete()


ATOM_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Example Blog</title>
  <entry>
    <title>First post</title>
    <link href="https://example.com/blog/one"/>
    <author><name>Alice</name></author>
    <published>2026-01-01T10:00:00Z</published>
    <content type="html">&lt;p&gt;Summary of the first post&lt;/p&gt;
      &lt;img src="https://example.com/img/one.jpg"/&gt;</content>
  </entry>
</feed>
"""


class FakeResponse:
    def __init__(self, content, ok=True, status_code=200):
        self.content = content if isinstance(content, bytes) else content.encode()
        self.ok = ok
        self.status_code = status_code


def poll_suggest_job(client, token, job_id, timeout_seconds=10):
    """Poll the suggest_result endpoint until the background job finishes."""
    deadline = time.monotonic() + timeout_seconds
    while True:
        response = client.get(
            f"/source_analyze/suggest_result?job_id={job_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        if response.status_code != 200 or response.json()["status"] != "running":
            return response
        assert time.monotonic() < deadline, "analysis job never finished"
        time.sleep(0.05)


def test_suggest_returns_validated_candidates(
    client, token, css_selector_template, monkeypatch
):
    seen = {}

    def fake_fetch(url, cookie=""):
        seen["cookie"] = cookie
        return SAMPLE_HTML

    monkeypatch.setattr("routers.source_analyze.fetch_page", fake_fetch)
    monkeypatch.setattr(
        "routers.source_analyze.request_selector_suggestions",
        lambda url, html: RAW_SUGGESTIONS,
    )

    args = build_api_request_args(
        path="/source_analyze/suggest",
        token=token,
        data={"url": "https://example.com/blog/", "cookie": "consent=yes"},
    )
    response = client.post(**args)

    # analysis runs as a background job the client polls for
    assert response.status_code == 200
    job_id = response.json()["job_id"]

    response = poll_suggest_job(client, token, job_id)
    assert response.status_code == 200
    assert response.json()["status"] == "done"
    data = response.json()["result"]

    assert data["page_title"] == "Example Blog | Great Posts"
    assert data["suggested_source_name"] == "Example Blog"
    assert data["template_name_hash"] == css_selector_template.name_hash

    entry_selectors = [
        c["selector"] for c in data["candidates"]["entry_element_selector"]
    ]
    assert entry_selectors == ["div.post"]
    assert data["candidates"]["title_selector"][0]["selector"] == "h2.post-title"
    assert data["candidates"]["time_selector"][0]["time_format"] == "Y-m-d\\TH:i:sP"

    # the consent cookie is used for the fetch and kept for the saved source
    assert seen["cookie"] == "consent=yes"
    assert data["defaults"]["cookie"] == "consent=yes"

    # defaults are directly previewable, with author/time left off
    assert data["defaults"]["home_page"] == "https://example.com/blog/"
    assert data["defaults"]["entry_element_selector"] == "div.post"
    assert data["defaults"]["title_selector"] == "h2.post-title"
    assert data["defaults"]["author_selector"] == ""
    assert data["defaults"]["time_selector"] == ""


def test_suggest_without_template_is_503(client, token, monkeypatch):
    args = build_api_request_args(
        path="/source_analyze/suggest",
        token=token,
        data={"url": "https://example.com/blog/"},
    )
    response = client.post(**args)

    assert response.status_code == 503


def test_suggest_job_errors_are_surfaced_on_poll(
    client, token, css_selector_template, monkeypatch
):
    def failing_fetch(url, cookie=""):
        raise AnalyzeError("Couldn't fetch the page", status_code=502)

    monkeypatch.setattr("routers.source_analyze.fetch_page", failing_fetch)

    args = build_api_request_args(
        path="/source_analyze/suggest",
        token=token,
        data={"url": "https://example.com/blog/"},
    )
    job_id = client.post(**args).json()["job_id"]

    response = poll_suggest_job(client, token, job_id)
    assert response.status_code == 502
    assert "Couldn't fetch" in response.json()["detail"]


def test_suggest_result_unknown_job_is_404(client, token):
    response = client.get(
        "/source_analyze/suggest_result?job_id=nope",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404


def test_suggest_requires_auth(client):
    response = client.post(
        "/source_analyze/suggest", json={"url": "https://example.com/"}
    )
    assert response.status_code == 401


def test_detect_returns_feed_kind(client, token, monkeypatch):
    monkeypatch.setattr(
        "routers.source_analyze.detect_source_type",
        lambda url, cookie: {
            "kind": "feed",
            "feed_url": url,
            "suggested_source_name": "Example Blog",
        },
    )

    args = build_api_request_args(
        path="/source_analyze/detect",
        token=token,
        data={"url": "https://example.com/feed.xml"},
    )
    response = client.post(**args)

    assert response.status_code == 200
    data = response.json()
    assert data["kind"] == "feed"
    assert data["feed_url"] == "https://example.com/feed.xml"
    assert data["suggested_source_name"] == "Example Blog"


def test_detect_offers_a_site_feed_that_misses_the_page(client, token, monkeypatch):
    """An advertised feed the page doesn't match is returned, not chosen."""
    monkeypatch.setattr(
        "routers.source_analyze.detect_source_type",
        lambda url, cookie: {
            "kind": "html",
            "feed_url": None,
            "site_feed_url": "https://example.com/rss",
            "suggested_source_name": "Some Section",
        },
    )

    args = build_api_request_args(
        path="/source_analyze/detect",
        token=token,
        data={"url": "https://example.com/sections/some-section"},
    )
    response = client.post(**args)

    assert response.status_code == 200
    data = response.json()
    assert data["kind"] == "html"
    assert data["feed_url"] is None
    assert data["site_feed_url"] == "https://example.com/rss"


def test_detect_surfaces_fetch_errors(client, token, monkeypatch):
    def failing_detect(url, cookie):
        raise AnalyzeError("Couldn't fetch the page", status_code=502)

    monkeypatch.setattr("routers.source_analyze.detect_source_type", failing_detect)

    args = build_api_request_args(
        path="/source_analyze/detect",
        token=token,
        data={"url": "https://example.com/"},
    )
    response = client.post(**args)

    assert response.status_code == 502
    assert "Couldn't fetch" in response.json()["detail"]


def test_detect_requires_auth(client):
    response = client.post(
        "/source_analyze/detect", json={"url": "https://example.com/"}
    )
    assert response.status_code == 401


def test_preview_renders_bridge_feed(client, token, css_selector_template, monkeypatch):
    captured = {}

    def fake_get(url, timeout=None):
        captured["url"] = url
        return FakeResponse(ATOM_FEED)

    monkeypatch.setattr("routers.source_analyze.requests.get", fake_get)

    args = build_api_request_args(
        path="/source_analyze/preview",
        token=token,
        data={
            "parameters": {
                "home_page": "https://example.com/blog/",
                "entry_element_selector": "div.post",
                "title_selector": "h2.post-title",
                "limit": "10",
            }
        },
    )
    response = client.post(**args)

    assert response.status_code == 200
    data = response.json()

    # the preview goes through rss-bridge with the chosen selectors
    assert "bridge=CssSelectorComplexBridge" in captured["url"]
    assert "entry_element_selector=div.post" in captured["url"]

    assert data["feed_title"] == "Example Blog"
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["title"] == "First post"
    assert item["url"] == "https://example.com/blog/one"
    assert item["author"] == "Alice"
    assert item["excerpt"] == "Summary of the first post"
    assert item["image"] == "https://example.com/img/one.jpg"


def test_preview_surfaces_bridge_errors(
    client, token, css_selector_template, monkeypatch
):
    monkeypatch.setattr(
        "routers.source_analyze.requests.get",
        lambda url, timeout=None: FakeResponse(
            "<html><body>No entry elements for entry selector</body></html>",
            ok=False,
            status_code=500,
        ),
    )

    args = build_api_request_args(
        path="/source_analyze/preview",
        token=token,
        data={
            "parameters": {
                "home_page": "https://example.com/blog/",
                "entry_element_selector": "div.wrong",
            }
        },
    )
    response = client.post(**args)

    assert response.status_code == 502
    assert "No entry elements" in response.json()["detail"]


def test_preview_rejects_missing_required_parameters(
    client, token, css_selector_template
):
    args = build_api_request_args(
        path="/source_analyze/preview",
        token=token,
        data={"parameters": {"home_page": "https://example.com/blog/"}},
    )
    response = client.post(**args)

    assert response.status_code == 422
