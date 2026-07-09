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


def test_rescrape_source(client, existing_feed, existing_source, token):
    args = build_api_request_args(
        path="/source/rescrape",
        params={
            "feed_name_hash": existing_feed.name_hash,
            "source_name_hash": existing_source.name_hash,
        },
        token=token,
    )

    response = client.post(**args)
    assert response.status_code == 200
    assert response.json() == {"message": "success"}


def test_rescrape_source_not_found(client, existing_feed, token):
    args = build_api_request_args(
        path="/source/rescrape",
        params={
            "feed_name_hash": existing_feed.name_hash,
            "source_name_hash": "does-not-exist",
        },
        token=token,
    )

    response = client.post(**args)
    assert response.status_code == 404
    assert response.json() == {"detail": "Source not found"}


def test_create_duplicate_source_conflict(client, existing_feed, existing_source, token):
    args = build_api_request_args(
        path="/source/create",
        params={
            "feed_name_hash": existing_feed.name_hash,
            "source_name": existing_source.name,
            "source_url": "http://example.com/other.xml",
        },
        token=token,
    )

    response = client.post(**args)
    assert response.status_code == 409


def test_update_source_rename_and_url(client, existing_feed, existing_source, token):
    args = build_api_request_args(
        path="/source/update",
        data={
            "feed_name_hash": existing_feed.name_hash,
            "source_name_hash": existing_source.name_hash,
            "source_name": f"{existing_source.name} renamed",
            "source_url": "http://example.com/new.xml",
        },
        token=token,
    )

    response = client.post(**args)
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["source_name"] == f"{existing_source.name} renamed"
    assert res_data["source_url"] == "http://example.com/new.xml"

    # the old name_hash no longer resolves; the new one does
    from db.source import Source

    new_source = Source.read(
        user_hash=existing_source.user_hash,
        feed_hash=existing_feed.name_hash,
        source_hash=res_data["source_name_hash"],
    )
    assert new_source.name == f"{existing_source.name} renamed"
    assert str(new_source.url) == "http://example.com/new.xml"


def test_update_source_rename_keeps_items(
    client, existing_feed, existing_source, existing_item_strict, token
):
    args = build_api_request_args(
        path="/source/update",
        data={
            "feed_name_hash": existing_feed.name_hash,
            "source_name_hash": existing_source.name_hash,
            "source_name": f"{existing_source.name} renamed",
        },
        token=token,
    )

    response = client.post(**args)
    assert response.status_code == 200
    new_hash = response.json()["source_name_hash"]

    args = build_api_request_args(
        path="/source/items",
        params={
            "feed_name_hash": existing_feed.name_hash,
            "source_name_hash": new_hash,
        },
        token=token,
    )
    response = client.get(**args)
    assert response.status_code == 200
    assert response.json()[0]["item_title"] == existing_item_strict.title


def test_update_source_rename_conflict(client, existing_feed, existing_source, token):
    from db.source import Source

    other = Source(
        user_hash=existing_source.user_hash,
        feed_hash=existing_feed.name_hash,
        name=f"{existing_source.name} other",
        url="http://example.com/other.xml",
    )
    existing_feed.add_source(other)

    args = build_api_request_args(
        path="/source/update",
        data={
            "feed_name_hash": existing_feed.name_hash,
            "source_name_hash": existing_source.name_hash,
            "source_name": other.name,
        },
        token=token,
    )

    response = client.post(**args)
    assert response.status_code == 409


def test_update_source_ingest_interval(client, existing_feed, existing_source, token):
    args = build_api_request_args(
        path="/source/update",
        data={
            "feed_name_hash": existing_feed.name_hash,
            "source_name_hash": existing_source.name_hash,
            "source_name": existing_source.name,
            "ingest_interval_minutes": 120,
        },
        token=token,
    )

    response = client.post(**args)
    assert response.status_code == 200
    assert response.json()["source_ingest_interval_minutes"] == 120

    # omitting the field leaves the interval unchanged
    args = build_api_request_args(
        path="/source/update",
        data={
            "feed_name_hash": existing_feed.name_hash,
            "source_name_hash": existing_source.name_hash,
            "source_name": existing_source.name,
        },
        token=token,
    )
    response = client.post(**args)
    assert response.status_code == 200
    assert response.json()["source_ingest_interval_minutes"] == 120

    # an explicit null resets to the server default
    args = build_api_request_args(
        path="/source/update",
        data={
            "feed_name_hash": existing_feed.name_hash,
            "source_name_hash": existing_source.name_hash,
            "source_name": existing_source.name,
            "ingest_interval_minutes": None,
        },
        token=token,
    )
    response = client.post(**args)
    assert response.status_code == 200
    assert response.json()["source_ingest_interval_minutes"] is None


def test_update_source_invalid_interval(client, existing_feed, existing_source, token):
    args = build_api_request_args(
        path="/source/update",
        data={
            "feed_name_hash": existing_feed.name_hash,
            "source_name_hash": existing_source.name_hash,
            "source_name": existing_source.name,
            "ingest_interval_minutes": 0,
        },
        token=token,
    )

    response = client.post(**args)
    assert response.status_code == 422


def test_update_source_not_found(client, existing_feed, token):
    args = build_api_request_args(
        path="/source/update",
        data={
            "feed_name_hash": existing_feed.name_hash,
            "source_name_hash": "does-not-exist",
            "source_name": "whatever",
        },
        token=token,
    )

    response = client.post(**args)
    assert response.status_code == 404
