from tests.testing_utils import build_api_request_args
from pydantic import HttpUrl


def test_create_feed(client, unique_feed, existing_user, token):
    args = build_api_request_args(
        path="/feed/create",
        params={"feed_name": unique_feed.name},
        token=token,
    )

    response = client.post(**args)

    assert response.status_code == 200
    assert response.json() == {
        "feed_name": unique_feed.name,
        "feed_name_hash": unique_feed.name_hash,
    }


def test_create_no_name(client, existing_user, token):
    args = build_api_request_args(
        path="/feed/create",
        params={},
        token=token,
    )

    response = client.post(**args)

    assert response.status_code == 422


def test_delete_feed(client, existing_user, existing_feed, token):
    args = build_api_request_args(
        path="/feed/delete",
        params={"feed_name_hash": existing_feed.name_hash},
        token=token,
    )

    response = client.delete(**args)

    assert response.status_code == 200
    assert response.json() == {"message": "success"}


def test_delete_nonexistent_feed(client, existing_user, token):
    args = build_api_request_args(
        path="/feed/delete",
        params={"feed_name_hash": "nonexistent"},
        token=token,
    )

    response = client.delete(**args)

    assert response.status_code == 404
    assert response.json() == {"detail": "Feed not found"}


def test_get_feed(client, existing_user, existing_feed, token):
    args = build_api_request_args(
        path="/feed/get",
        params={"feed_name_hash": existing_feed.name_hash},
        token=token,
    )

    response = client.get(**args)

    assert response.status_code == 200
    assert response.json() == {
        "feed_name": existing_feed.name,
        "feed_name_hash": existing_feed.name_hash,
    }


def test_get_nonexistent_feed(client, existing_user, token):
    args = build_api_request_args(
        path="/feed/get",
        params={"feed_name_hash": "nonexistent"},
        token=token,
    )

    response = client.get(**args)

    assert response.status_code == 404
    assert response.json() == {"detail": "Feed not found"}


def test_list_feeds(client, existing_user, existing_feed, token):
    args = build_api_request_args(
        path="/feed/list",
        token=token,
    )

    response = client.get(**args)

    assert response.status_code == 200
    assert response.json() == [
        {
            "feed_name": existing_feed.name,
            "feed_name_hash": existing_feed.name_hash,
        }
    ]


def test_list_feeds_no_feeds(client, existing_user, token):
    args = build_api_request_args(
        path="/feed/list",
        token=token,
    )

    response = client.get(**args)

    assert response.status_code == 200
    assert response.json() == []


def test_list_feeds_no_token(client):
    args = build_api_request_args(
        path="/feed/list",
    )

    response = client.get(**args)

    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}


def test_sources(client, existing_user, existing_feed, existing_source, token):
    args = build_api_request_args(
        path="/feed/sources",
        params={"feed_name_hash": existing_feed.name_hash},
        token=token,
    )

    response = client.get(**args)

    assert response.status_code == 200
    assert response.json() == [
        {
            "source_name": existing_source.name,
            "source_name_hash": existing_source.name_hash,
            "source_url": str(existing_source.url),
            "source_feed": existing_source.feed_hash,
        }
    ]


def test_get_all_items(
    client,
    existing_user,
    existing_feed,
    existing_source,
    existing_item_strict,
    token,
):
    args = build_api_request_args(
        path="/feed/items",
        params={"feed_name_hash": existing_feed.name_hash},
        token=token,
    )

    response = client.get(**args)

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["item_url"] == str(existing_item_strict.url)


def test_get_some_items(
    client, existing_user, existing_feed, existing_source, unique_item_strict, token
):
    new_items = [unique_item_strict.model_copy() for i in range(10)]
    for i, item in enumerate(new_items):
        item.url = HttpUrl(f"http://example.com/{i}/")
        item.create()
        existing_feed.add_items(item)
        #  multiply by 8 to differenciate between index and score
        existing_feed.set_items_scores({item.url_hash: 8 * i})

    args = build_api_request_args(
        path="/feed/items",
        params={
            "feed_name_hash": existing_feed.name_hash,
            "skip": 2,
            "limit": 2,
        },
        token=token,
    )

    response = client.get(**args)

    assert response.status_code == 200
    assert len(response.json()) == 2
    assert response.json()[0]["item_url"] == "http://example.com/2/"
    assert response.json()[1]["item_url"] == "http://example.com/3/"
