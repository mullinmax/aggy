"""Fetching a stream on the viewer's behalf when the site refuses them."""

import pytest
from pydantic import HttpUrl
from requests.structures import CaseInsensitiveDict

from db.item import ItemLoose
from routers import item as item_router
from streaming import tickets

MEDIA_URL = "https://cdn.example.com/v.mp4?sig=abc"


class FakeUpstream:
    """Stands in for the site's answer to `requests.get(..., stream=True)`."""

    def __init__(self, status_code=200, headers=None, body=b"", url=MEDIA_URL):
        self.status_code = status_code
        # a real response's headers are case insensitive, and header names
        # arrive however the origin chose to spell them
        self.headers = CaseInsensitiveDict(headers or {"Content-Type": "video/mp4"})
        self.url = url
        self._body = body
        self.raw = self
        self.closed = False

    def iter_content(self, chunk_size=None):
        yield self._body

    def read(self, amount=None, decode_content=False):
        return self._body

    def close(self):
        self.closed = True


@pytest.fixture
def stream_item(existing_source, existing_feed):
    item = ItemLoose(
        url=HttpUrl("http://example.com/clip/"),
        title="A clip",
        domain="example.com",
        excerpt="clip",
        content="clip",
        media=[{"type": "stream", "url": "http://example.com/clip/"}],
    )
    item.create()
    existing_source.add_items(item)
    existing_feed.add_items(item)
    return item


def _capture(monkeypatch, upstream):
    seen = {}

    def fake_get(url, headers=None, stream=False, allow_redirects=True, timeout=None):
        seen["url"] = url
        seen["headers"] = headers or {}
        return upstream

    monkeypatch.setattr(item_router.requests, "get", fake_get)
    return seen


def _fetch(client, ticket, headers=None):
    return client.get(f"/item/stream?ticket={ticket}", headers=headers or {})


def test_the_bytes_come_back_with_the_origin_s_answer(
    monkeypatch, client, existing_user, stream_item
):
    upstream = FakeUpstream(
        status_code=206,
        headers={
            "Content-Type": "video/mp4",
            "Content-Range": "bytes 0-9/2048",
            "Accept-Ranges": "bytes",
        },
        body=b"0123456789",
    )
    seen = _capture(monkeypatch, upstream)
    ticket = tickets.mint(MEDIA_URL, existing_user.name_hash, stream_item.url_hash)

    response = _fetch(client, ticket, headers={"Range": "bytes=0-9"})

    assert response.status_code == 206
    assert response.content == b"0123456789"
    assert response.headers["content-range"] == "bytes 0-9/2048"
    assert response.headers["accept-ranges"] == "bytes"
    # without the range going out, dragging a scrub bar pulls the whole file
    assert seen["headers"]["Range"] == "bytes=0-9"
    assert seen["url"] == MEDIA_URL


def test_the_request_looks_like_the_one_the_site_signed_for(
    monkeypatch, client, existing_user, existing_source, stream_item
):
    """A CDN checks who is asking and where they came from, and the source's
    cookie is what got past the door in the first place."""
    existing_source.update(
        name=existing_source.name,
        url=existing_source.url,
        config={"cookie": "age_verified=1"},
    )
    seen = _capture(monkeypatch, FakeUpstream(body=b"x"))
    ticket = tickets.mint(MEDIA_URL, existing_user.name_hash, stream_item.url_hash)

    assert _fetch(client, ticket).status_code == 200
    assert seen["headers"]["Cookie"] == "age_verified=1"
    assert seen["headers"]["Referer"] == str(stream_item.url)
    assert "Mozilla/5.0" in seen["headers"]["User-Agent"]


def test_a_playlist_keeps_its_segments_on_this_server(
    monkeypatch, client, existing_user, stream_item
):
    """Rewriting the playlist but not what it names would move the problem one
    hop down: the segments would be fetched direct and refused the same way."""
    playlist = b"#EXTM3U\n#EXTINF:6.0,\nseg1.ts\n"
    upstream = FakeUpstream(
        headers={"Content-Type": "application/vnd.apple.mpegurl"},
        body=playlist,
        url="https://cdn.example.com/hls/index.m3u8",
    )
    _capture(monkeypatch, upstream)
    ticket = tickets.mint(
        "https://cdn.example.com/hls/index.m3u8",
        existing_user.name_hash,
        stream_item.url_hash,
    )

    response = _fetch(client, ticket)

    assert response.status_code == 200
    lines = response.text.splitlines()
    assert lines[0] == "#EXTM3U"
    assert lines[-1].startswith("/item/stream?ticket=")
    # and the ticket it minted points at the segment, still on this user's behalf
    claims = tickets.verify(lines[-1].split("ticket=", 1)[1])
    assert claims["url"] == "https://cdn.example.com/hls/seg1.ts"
    assert claims["user"] == existing_user.name_hash


def test_a_ticket_this_server_did_not_sign_gets_nothing(monkeypatch, client):
    def explode(*args, **kwargs):
        raise AssertionError("an unsigned ticket must never reach the network")

    monkeypatch.setattr(item_router.requests, "get", explode)

    response = _fetch(client, "not-a-real-ticket")

    assert response.status_code == 403


def test_an_origin_that_refuses_us_too_says_so(
    monkeypatch, client, existing_user, stream_item
):
    _capture(monkeypatch, FakeUpstream(status_code=403))
    ticket = tickets.mint(MEDIA_URL, existing_user.name_hash, stream_item.url_hash)

    response = _fetch(client, ticket)

    assert response.status_code == 502
    assert "403" in response.json()["detail"]
