"""Resolving a playable URL for a video item."""

import pytest
from pydantic import HttpUrl

from db.item import ItemLoose
from db.source import Source
from ingest.backends import ytdlp
from tests.testing_utils import build_api_request_args


def _stream_item(existing_source, existing_feed, url="http://example.com/clip/"):
    item = ItemLoose(
        url=HttpUrl(url),
        title="A clip",
        domain="example.com",
        excerpt="clip",
        content="clip",
        media=[{"type": "stream", "url": url}],
    )
    item.create()
    existing_source.add_items(item)
    existing_feed.add_items(item)
    return item


def _request(client, token, item):
    args = build_api_request_args(
        path="/item/stream_url",
        params={"item_url_hash": item.url_hash},
        token=token,
    )
    return client.get(**args)


def test_the_sources_cookie_is_used_for_playback(
    monkeypatch, client, token, existing_user, existing_feed, existing_source
):
    """Whatever gets a source past a site's door has to come along to
    playback: the listing and the video are the same site."""
    item = _stream_item(existing_source, existing_feed)
    existing_source.update(
        name=existing_source.name,
        url=existing_source.url,
        config={"cookie": "age_verified=1"},
    )

    seen = {}

    def fake_resolve(url, cookie=None):
        seen["url"] = url
        seen["cookie"] = cookie
        return {"url": "http://cdn.example.com/v.mp4", "is_hls": False}

    monkeypatch.setattr(ytdlp, "resolve_stream", fake_resolve)

    response = _request(client, token, item)

    assert response.status_code == 200
    assert seen["cookie"] == "age_verified=1"
    assert response.json()["url"] == "http://cdn.example.com/v.mp4"


def test_a_source_without_a_cookie_sends_none(
    monkeypatch, client, token, existing_user, existing_feed, existing_source
):
    item = _stream_item(existing_source, existing_feed)

    seen = {}

    def fake_resolve(url, cookie=None):
        seen["cookie"] = cookie
        return {"url": "http://cdn.example.com/v.mp4"}

    monkeypatch.setattr(ytdlp, "resolve_stream", fake_resolve)

    assert _request(client, token, item).status_code == 200
    assert seen["cookie"] is None


def test_another_users_cookie_is_never_borrowed(
    existing_user, existing_feed, existing_source
):
    """The lookup is scoped to the asking user: a cookie is a credential."""
    item = _stream_item(existing_source, existing_feed)
    existing_source.update(
        name=existing_source.name,
        url=existing_source.url,
        config={"cookie": "age_verified=1"},
    )

    assert (
        Source.cookie_for_item(existing_user.name_hash, item.url_hash)
        == "age_verified=1"
    )
    assert Source.cookie_for_item("someone-else", item.url_hash) is None


@pytest.mark.parametrize(
    "status_code,detail",
    [
        (422, "The site refused this request (403)"),
        (504, "The site took longer than 40s to answer"),
        (501, "This server has no video extraction service configured"),
    ],
)
def test_the_reason_reaches_the_viewer(
    monkeypatch,
    client,
    token,
    existing_user,
    existing_feed,
    existing_source,
    status_code,
    detail,
):
    """Each way a resolve can fail keeps its own status and its own sentence,
    so the card can say what happened instead of "can't play here"."""
    item = _stream_item(existing_source, existing_feed)

    def fake_resolve(url, cookie=None):
        raise ytdlp.StreamUnavailable(detail, status_code=status_code)

    monkeypatch.setattr(ytdlp, "resolve_stream", fake_resolve)

    response = _request(client, token, item)
    assert response.status_code == status_code
    assert response.json()["detail"] == detail


def test_an_item_with_no_stream_is_rejected_before_the_service(
    monkeypatch, client, token, existing_user, existing_feed, existing_source
):
    item = ItemLoose(
        url=HttpUrl("http://example.com/article/"),
        title="An article",
        domain="example.com",
        excerpt="words",
        content="words",
    )
    item.create()
    existing_source.add_items(item)
    existing_feed.add_items(item)

    def explode(url, cookie=None):
        raise AssertionError("the extraction service should not be asked")

    monkeypatch.setattr(ytdlp, "resolve_stream", explode)

    response = _request(client, token, item)
    assert response.status_code == 422
    assert "no resolvable stream" in response.json()["detail"]


def test_the_item_has_to_exist(client, token, existing_user):
    args = build_api_request_args(
        path="/item/stream_url",
        params={"item_url_hash": "nope"},
        token=token,
    )
    assert client.get(**args).status_code == 404
