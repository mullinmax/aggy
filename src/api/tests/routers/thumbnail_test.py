"""Finding a picture for a video item when the stored one stops loading."""

import pytest
from pydantic import HttpUrl
from requests.structures import CaseInsensitiveDict

from db.item import ItemLoose
from ingest.backends import ytdlp
from routers import item as item_router
from streaming import tickets
from tests.testing_utils import build_api_request_args

STORED = "https://cdn.example.com/thumbs/old.jpg"
FRESH = "https://cdn.example.com/thumbs/new.jpg"


class FakeResponse:
    def __init__(self, status_code=200):
        self.status_code = status_code
        self.headers = CaseInsensitiveDict({"Content-Type": "image/jpeg"})

    def close(self):
        pass


@pytest.fixture(autouse=True)
def no_cooldown_between_tests():
    item_router._thumbnail_refreshed_at.clear()
    yield
    item_router._thumbnail_refreshed_at.clear()


@pytest.fixture
def video_item(existing_source, existing_feed):
    item = ItemLoose(
        url=HttpUrl("http://example.com/clip/"),
        title="A clip",
        domain="example.com",
        excerpt="clip",
        content="clip",
        image_url=STORED,
        media=[{"type": "stream", "url": "http://example.com/clip/", "poster": STORED}],
    )
    item.create()
    existing_source.add_items(item)
    existing_feed.add_items(item)
    return item


def _request(client, token, item):
    args = build_api_request_args(
        path="/item/thumbnail",
        params={"item_url_hash": item.url_hash},
        token=token,
    )
    return client.get(**args)


def test_a_picture_that_is_still_there_is_served_from_here(
    monkeypatch, client, token, existing_user, video_item
):
    """The usual reason a thumbnail won't load in the page is the site
    refusing a request it didn't expect - the picture itself is fine."""
    seen = {}

    def fake_get(url, headers=None, **kwargs):
        seen["url"] = url
        seen["headers"] = headers or {}
        return FakeResponse()

    monkeypatch.setattr(item_router.requests, "get", fake_get)

    body = _request(client, token, video_item).json()

    assert seen["url"] == STORED
    assert seen["headers"]["Referer"] == str(video_item.url)
    assert tickets.verify(body["url"].split("ticket=", 1)[1])["url"] == STORED


def test_a_picture_that_has_expired_is_replaced_and_kept(
    monkeypatch, client, token, existing_user, video_item
):
    """Sites sign their thumbnails too, so a stored one goes stale. Storing
    the replacement means only the first reader waits for it."""
    monkeypatch.setattr(
        item_router.requests, "get", lambda url, **kwargs: FakeResponse(403)
    )
    monkeypatch.setattr(ytdlp, "poster_for", lambda url: FRESH)

    body = _request(client, token, video_item).json()

    assert tickets.verify(body["url"].split("ticket=", 1)[1])["url"] == FRESH
    stored = ItemLoose.read(url_hash=video_item.url_hash)
    assert stored.image_url == FRESH
    assert stored.media[0]["poster"] == FRESH


def test_the_site_is_not_asked_again_and_again_about_a_picture_that_is_gone(
    monkeypatch, client, token, existing_user, video_item
):
    """Asking means visiting the item's page. An item with no picture left
    would otherwise pay for that every time its card is drawn."""
    monkeypatch.setattr(
        item_router.requests, "get", lambda url, **kwargs: FakeResponse(404)
    )
    asked = []

    def count(url):
        asked.append(url)
        return None

    monkeypatch.setattr(ytdlp, "poster_for", count)

    assert _request(client, token, video_item).status_code == 404
    assert _request(client, token, video_item).status_code == 404
    assert len(asked) == 1


def test_the_item_has_to_exist(client, token, existing_user):
    args = build_api_request_args(
        path="/item/thumbnail",
        params={"item_url_hash": "nope"},
        token=token,
    )
    assert client.get(**args).status_code == 404
