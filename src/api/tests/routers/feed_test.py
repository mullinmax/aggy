from tests.utils import build_api_request_args


def test_create_feed(client, unique_feed, existing_user, existing_category, token):
    args = build_api_request_args(
        path="/feed/create",
        params={
            "category_name_hash": existing_category.name_hash,
            "feed_name": unique_feed.name,
            "feed_url": unique_feed.url,
        },
        token=token,
    )

    response = client.post(**args)

    assert response.status_code == 200
    assert response.json() == {"message": "success"}


def test_create_no_name(client, unique_feed, existing_user, existing_category, token):
    args = build_api_request_args(
        path="/feed/create",
        params={
            "category_name_hash": existing_category.name_hash,
            "feed_url": unique_feed.url,
        },
        token=token,
    )

    response = client.post(**args)
    assert response.status_code == 422


def test_create_no_url(client, unique_feed, existing_user, existing_category, token):
    args = build_api_request_args(
        path="/feed/create",
        params={
            "category_name_hash": existing_category.name_hash,
            "feed_name": unique_feed.name,
        },
        token=token,
    )

    response = client.post(**args)

    assert response.status_code == 422


def test_feed_no_items(client, existing_user, existing_category, existing_feed, token):
    args = build_api_request_args(
        path="/feed/items",
        params={
            "category_name_hash": existing_category.name_hash,
            "feed_name_hash": existing_feed.name_hash,
        },
        token=token,
    )

    response = client.get(**args)
    assert response.status_code == 200
    assert response.json() == []


def test_feed_with_items(
    client, existing_user, existing_category, existing_feed, existing_item_strict, token
):
    args = build_api_request_args(
        path="/feed/items",
        params={
            "category_name_hash": existing_category.name_hash,
            "feed_name_hash": existing_feed.name_hash,
        },
        token=token,
    )

    response = client.get(**args)

    assert response.status_code == 200
    item_json = response.json()[0]
    assert item_json["item_title"] == existing_item_strict.title
    assert item_json["item_url"] == str(existing_item_strict.url)


def test_delete_feed(client, existing_user, existing_category, existing_feed, token):
    args = build_api_request_args(
        path="/feed/delete",
        params={
            "category_name_hash": existing_category.name_hash,
            "feed_name_hash": existing_feed.name_hash,
        },
        token=token,
    )

    response = client.delete(**args)
    assert response.status_code == 200
    assert response.json() == {"message": "success"}

    # confirm feed is deleted
    args = build_api_request_args(
        path="/feed/items",
        params={
            "category_name_hash": existing_category.name_hash,
            "feed_name_hash": existing_feed.name_hash,
        },
        token=token,
    )

    response = client.get(**args)
    assert response.status_code == 404
    assert response.json() == {"detail": "Feed not found"}
