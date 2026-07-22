"""Router: adding another feed as a source (/source/create_feed)."""

import uuid

from tests.testing_utils import build_api_request_args

from db.feed import Feed


def _make_feed(user, name=None) -> Feed:
    feed = Feed(user_hash=user.name_hash, name=name or f"Feed {uuid.uuid4()}")
    feed.create()
    return feed


def test_create_feed_source(client, existing_user, existing_feed, token):
    origin = _make_feed(existing_user)
    args = build_api_request_args(
        path="/source/create_feed",
        token=token,
        params={
            "feed_name_hash": existing_feed.name_hash,
            "source_feed_name_hash": origin.name_hash,
        },
    )
    response = client.post(**args)
    assert response.status_code == 200
    body = response.json()
    assert body["source_feed_hash"] == origin.name_hash

    # the mirror source is registered on the feed
    stats = existing_feed.sources_with_stats()
    assert any(s["source_feed_hash"] == origin.name_hash for s in stats)


def test_create_feed_source_unknown_feed_404(client, existing_feed, token):
    args = build_api_request_args(
        path="/source/create_feed",
        token=token,
        params={
            "feed_name_hash": existing_feed.name_hash,
            "source_feed_name_hash": "does-not-exist",
        },
    )
    response = client.post(**args)
    assert response.status_code == 404


def test_create_feed_source_self_conflict(client, existing_feed, token):
    args = build_api_request_args(
        path="/source/create_feed",
        token=token,
        params={
            "feed_name_hash": existing_feed.name_hash,
            "source_feed_name_hash": existing_feed.name_hash,
        },
    )
    response = client.post(**args)
    assert response.status_code == 409


def test_create_feed_source_cycle_conflict(
    client, existing_user, existing_feed, token
):
    origin = _make_feed(existing_user)
    # existing_feed sources origin (items flow origin -> existing_feed)
    existing_feed.add_feed_source(origin)

    # now try to make origin source existing_feed, which would close the loop
    args = build_api_request_args(
        path="/source/create_feed",
        token=token,
        params={
            "feed_name_hash": origin.name_hash,
            "source_feed_name_hash": existing_feed.name_hash,
        },
    )
    response = client.post(**args)
    assert response.status_code == 409
