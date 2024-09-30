from tests.testing_utils import build_api_request_args


def test_create_source(client, unique_source, existing_feed, token):
    args = build_api_request_args(
        path="/source/create",
        params={
            "feed_name_hash": existing_feed.name_hash,
            "source_name": unique_source.name,
            "source_url": unique_source.url,
        },
        token=token,
    )

    response = client.post(**args)

    assert response.status_code == 200
    assert response.json() == {"message": "success"}


def test_create_no_name(client, unique_source, existing_feed, token):
    args = build_api_request_args(
        path="/source/create",
        params={
            "feed_name_hash": existing_feed.name_hash,
            "source_url": unique_source.url,
        },
        token=token,
    )

    response = client.post(**args)
    assert response.status_code == 422


def test_create_no_url(client, unique_source, existing_feed, token):
    args = build_api_request_args(
        path="/source/create",
        params={
            "feed_name_hash": existing_feed.name_hash,
            "source_name": unique_source.name,
        },
        token=token,
    )

    response = client.post(**args)

    assert response.status_code == 422


def test_source_no_items(client, existing_feed, existing_source, token):
    args = build_api_request_args(
        path="/source/items",
        params={
            "feed_name_hash": existing_feed.name_hash,
            "source_name_hash": existing_source.name_hash,
        },
        token=token,
    )

    response = client.get(**args)
    assert response.status_code == 200
    assert response.json() == []


def test_source_with_items(
    client, existing_feed, existing_source, existing_item_strict, token
):
    args = build_api_request_args(
        path="/source/items",
        params={
            "feed_name_hash": existing_feed.name_hash,
            "source_name_hash": existing_source.name_hash,
        },
        token=token,
    )

    response = client.get(**args)

    assert response.status_code == 200
    item_json = response.json()[0]
    assert item_json["item_title"] == existing_item_strict.title
    assert item_json["item_url"] == str(existing_item_strict.url)


def test_delete_source(client, existing_feed, existing_source, token):
    args = build_api_request_args(
        path="/source/delete",
        params={
            "feed_name_hash": existing_feed.name_hash,
            "source_name_hash": existing_source.name_hash,
        },
        token=token,
    )

    response = client.delete(**args)
    assert response.status_code == 200
    assert response.json() == {"message": "success"}

    # confirm source is deleted
    args = build_api_request_args(
        path="/source/items",
        params={
            "feed_name_hash": existing_feed.name_hash,
            "source_name_hash": existing_source.name_hash,
        },
        token=token,
    )

    response = client.get(**args)
    assert response.status_code == 404
    assert response.json() == {"detail": "Source not found"}
