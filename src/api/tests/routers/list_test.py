from tests.testing_utils import build_api_request_args

from db.list import UserList


def test_create_list(client, existing_user, token):
    args = build_api_request_args(
        path="/list/create",
        token=token,
        params={"list_name": "Watch later"},
    )
    response = client.post(**args)
    assert response.status_code == 200
    body = response.json()
    assert body["list_name"] == "Watch later"
    assert body["list_item_count"] == 0

    lst = UserList.read(existing_user.name_hash, body["list_name_hash"])
    assert lst is not None


def test_create_duplicate_list_conflicts(client, existing_list, token):
    args = build_api_request_args(
        path="/list/create",
        token=token,
        params={"list_name": existing_list.name},
    )
    response = client.post(**args)
    assert response.status_code == 409


def test_create_blank_list_rejected(client, token):
    args = build_api_request_args(
        path="/list/create", token=token, params={"list_name": "   "}
    )
    response = client.post(**args)
    assert response.status_code == 422


def test_list_lists(client, existing_list, token):
    args = build_api_request_args(path="/list/list", token=token)
    response = client.get(**args)
    assert response.status_code == 200
    names = {row["list_name"] for row in response.json()}
    assert existing_list.name in names


def test_list_lists_with_item_membership(
    client, existing_list, existing_item_strict, token
):
    existing_list.add_item(existing_item_strict.url_hash)
    args = build_api_request_args(
        path="/list/list",
        token=token,
        params={"item_url_hash": existing_item_strict.url_hash},
    )
    response = client.get(**args)
    assert response.status_code == 200
    row = next(
        r for r in response.json() if r["list_name_hash"] == existing_list.name_hash
    )
    assert row["list_contains_item"] is True
    assert row["list_item_count"] == 1


def test_get_list(client, existing_list, existing_item_strict, token):
    existing_list.add_item(existing_item_strict.url_hash)
    args = build_api_request_args(
        path="/list/get",
        token=token,
        params={"list_name_hash": existing_list.name_hash},
    )
    response = client.get(**args)
    assert response.status_code == 200
    body = response.json()
    assert body["list_name"] == existing_list.name
    assert body["list_item_count"] == 1


def test_get_missing_list_404(client, token):
    args = build_api_request_args(
        path="/list/get", token=token, params={"list_name_hash": "missing"}
    )
    response = client.get(**args)
    assert response.status_code == 404


def test_delete_list(client, existing_list, existing_user, token):
    args = build_api_request_args(
        path="/list/delete",
        token=token,
        params={"list_name_hash": existing_list.name_hash},
    )
    response = client.delete(**args)
    assert response.status_code == 200
    assert UserList.read(existing_user.name_hash, existing_list.name_hash) is None


def test_delete_missing_list_404(client, token):
    args = build_api_request_args(
        path="/list/delete", token=token, params={"list_name_hash": "missing"}
    )
    response = client.delete(**args)
    assert response.status_code == 404


def test_set_item_lists(client, existing_user, existing_item_strict, token):
    a = UserList(user_hash=existing_user.name_hash, name="Alpha")
    b = UserList(user_hash=existing_user.name_hash, name="Beta")
    a.create()
    b.create()

    args = build_api_request_args(
        path="/list/set_item_lists",
        token=token,
        params={
            "item_url_hash": existing_item_strict.url_hash,
            "list_hashes": f"{a.name_hash},{b.name_hash}",
        },
    )
    response = client.post(**args)
    assert response.status_code == 200
    assert a.contains(existing_item_strict.url_hash)
    assert b.contains(existing_item_strict.url_hash)

    # submitting an empty selection clears membership
    args = build_api_request_args(
        path="/list/set_item_lists",
        token=token,
        params={"item_url_hash": existing_item_strict.url_hash, "list_hashes": ""},
    )
    response = client.post(**args)
    assert response.status_code == 200
    assert not a.contains(existing_item_strict.url_hash)
    assert not b.contains(existing_item_strict.url_hash)


def test_set_item_lists_missing_item_404(client, existing_list, token):
    args = build_api_request_args(
        path="/list/set_item_lists",
        token=token,
        params={"item_url_hash": "missing", "list_hashes": existing_list.name_hash},
    )
    response = client.post(**args)
    assert response.status_code == 404


def test_get_list_items(client, existing_list, existing_item_strict, token):
    existing_list.add_item(existing_item_strict.url_hash)
    args = build_api_request_args(
        path="/list/items",
        token=token,
        params={"list_name_hash": existing_list.name_hash},
    )
    response = client.get(**args)
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["item_hash"] == existing_item_strict.url_hash


def test_feed_items_reflect_list_membership(
    client, existing_feed, existing_source, existing_item_strict, existing_list, token
):
    def feed_item():
        args = build_api_request_args(
            path="/feed/items",
            params={"feed_name_hash": existing_feed.name_hash},
            token=token,
        )
        response = client.get(**args)
        assert response.status_code == 200
        return next(
            i
            for i in response.json()
            if i["item_hash"] == existing_item_strict.url_hash
        )

    assert feed_item()["item_in_list"] is False

    existing_list.add_item(existing_item_strict.url_hash)
    assert feed_item()["item_in_list"] is True


def test_list_requires_auth(client):
    response = client.get("/list/list")
    assert response.status_code in (401, 403)
