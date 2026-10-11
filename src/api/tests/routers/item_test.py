from datetime import datetime

from tests.testing_utils import build_api_request_args

from db.item import ItemLoose
from db.item_state import ItemState


def test_set_item_state(
    client,
    existing_user,
    existing_source,
    existing_feed,
    existing_item_strict,
    token,
):
    item_state = ItemState.read(
        user_hash=existing_user.name_hash,
        feed_hash=existing_feed.name_hash,
        item_url_hash=existing_item_strict.url_hash,
    )
    assert item_state is None

    args = build_api_request_args(
        path="/item/set_state",
        token=token,
        params={
            "feed_hash": existing_feed.name_hash,
            "item_url_hash": existing_item_strict.url_hash,
            "score": 0.7631,
            "mark_as_read": True,
        },
    )

    response = client.post(**args)
    print("response.json(): ", response.json())
    assert response.status_code == 200

    item_state = ItemState.read(
        user_hash=existing_user.name_hash,
        feed_hash=existing_feed.name_hash,
        item_url_hash=existing_item_strict.url_hash,
    )
    assert item_state.score == 0.7631
    assert item_state.is_read


def test_get_item_state(
    client,
    existing_source,
    existing_feed,
    existing_item_strict,
    existing_item_state,
    token,
):
    args = build_api_request_args(
        path="/item/get_state",
        token=token,
        params={
            "feed_hash": existing_feed.name_hash,
            "item_url_hash": existing_item_strict.url_hash,
        },
    )

    response = client.get(**args)
    print("response.json(): ", response.json())
    assert response.status_code == 200

    item_state = response.json()
    assert item_state["score"] == existing_item_state.score
    # compared as instants, not strings: the API renders UTC as "...Z" while
    # datetime.isoformat() writes "+00:00" for the very same moment
    assert datetime.fromisoformat(
        item_state["score_date"].replace("Z", "+00:00")
    ) == existing_item_state.score_date
    assert item_state["is_read"] == existing_item_state.is_read


def test_set_state_non_existent_feed(
    client, existing_user, existing_source, existing_item_strict, token
):
    args = build_api_request_args(
        path="/item/set_state",
        token=token,
        params={
            "feed_hash": "non_existent_feed",
            "item_url_hash": existing_item_strict.url_hash,
            "score": 0.7631,
            "mark_as_read": True,
        },
    )

    response = client.post(**args)
    assert response.status_code == 404


def test_get_state_non_existent_item(
    client, existing_user, existing_source, existing_feed, token
):
    args = build_api_request_args(
        path="/item/get_state",
        token=token,
        params={
            "feed_hash": existing_feed.name_hash,
            "item_url_hash": "non_existent_item",
        },
    )

    response = client.get(**args)
    assert response.status_code == 404


def _rescrape_args(item_url_hash, feed_hash, token):
    return build_api_request_args(
        path="/item/rescrape",
        token=token,
        params={"item_url_hash": item_url_hash, "feed_hash": feed_hash},
    )


def test_rescrape_item_returns_the_updated_article(
    monkeypatch, client, existing_feed, existing_item_strict, existing_item_state, token
):
    from ingest import jobs

    monkeypatch.setattr(jobs, "ingest_reddit_item", lambda item: None)
    monkeypatch.setattr(
        jobs,
        "ingest_open_graph_item",
        lambda item: ItemLoose(url=item.url, content=item.content + " and much more"),
    )
    monkeypatch.setattr(jobs, "ingest_mercury_item", lambda item: None)
    retrained = []
    monkeypatch.setattr("routers.item.rerank_feeds", retrained.append)

    response = client.post(
        **_rescrape_args(existing_item_strict.url_hash, existing_feed.name_hash, token)
    )

    assert response.status_code == 200
    body = response.json()
    assert body["changed"] is True
    assert body["feeds_retraining"] == 1
    assert body["item"]["item_hash"] == existing_item_strict.url_hash
    assert body["item"]["item_content"] == existing_item_strict.content + " and much more"
    # the feed that voted on it retrains, after the response went out
    assert retrained == [
        {(existing_item_state.user_hash, existing_item_state.feed_hash)}
    ]


def test_rescrape_item_with_nothing_new(
    monkeypatch, client, existing_feed, existing_item_strict, token
):
    from ingest import jobs

    for scraper in ("ingest_reddit_item", "ingest_open_graph_item", "ingest_mercury_item"):
        monkeypatch.setattr(jobs, scraper, lambda item: None)

    response = client.post(
        **_rescrape_args(existing_item_strict.url_hash, existing_feed.name_hash, token)
    )

    assert response.status_code == 200
    assert response.json()["changed"] is False
    assert response.json()["feeds_retraining"] == 0


def test_rescrape_item_not_in_any_of_the_users_sources(
    client, existing_feed, existing_source, token
):
    response = client.post(
        **_rescrape_args("does-not-exist", existing_feed.name_hash, token)
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Item not found"}
