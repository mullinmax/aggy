from tests.utils import build_api_request_args


def test_create_category(client, unique_category, existing_user, token):
    args = build_api_request_args(
        path="/category/create",
        params={"name": unique_category.name},
        token=token,
    )

    response = client.post(**args)

    assert response.status_code == 200
    assert response.json() == {
        "name": unique_category.name,
        "name_hash": unique_category.name_hash,
    }


def test_create_no_name(client, existing_user, token):
    args = build_api_request_args(
        path="/category/create",
        params={},
        token=token,
    )

    response = client.post(**args)

    assert response.status_code == 422


def test_delete_category(client, existing_user, existing_category, token):
    args = build_api_request_args(
        path="/category/delete",
        params={"category_name_hash": existing_category.name_hash},
        token=token,
    )

    response = client.delete(**args)

    assert response.status_code == 200
    assert response.json() == {"message": "success"}


def test_delete_nonexistent_category(client, existing_user, token):
    args = build_api_request_args(
        path="/category/delete",
        params={"category_name_hash": "nonexistent"},
        token=token,
    )

    response = client.delete(**args)

    assert response.status_code == 500
    assert response.json() == {"detail": "Category not found"}


def test_get_category(client, existing_user, existing_category, token):
    args = build_api_request_args(
        path="/category/get",
        params={"category_name_hash": existing_category.name_hash},
        token=token,
    )

    response = client.get(**args)

    assert response.status_code == 200
    assert response.json() == {
        "name": existing_category.name,
        "name_hash": existing_category.name_hash,
    }


def test_get_nonexistent_category(client, existing_user, token):
    args = build_api_request_args(
        path="/category/get",
        params={"category_name_hash": "nonexistent"},
        token=token,
    )

    response = client.get(**args)

    assert response.status_code == 500
    assert response.json() == {"detail": "Category not found"}


def test_get_all_categories(client, existing_user, existing_category, token):
    args = build_api_request_args(
        path="/category/get_all",
        token=token,
    )

    response = client.get(**args)

    assert response.status_code == 200
    assert response.json() == [
        {
            "name": existing_category.name,
            "name_hash": existing_category.name_hash,
        }
    ]


def test_get_all_categories_no_categories(client, existing_user, token):
    args = build_api_request_args(
        path="/category/get_all",
        token=token,
    )

    response = client.get(**args)

    assert response.status_code == 200
    assert response.json() == []


def test_get_all_categories_no_token(client):
    args = build_api_request_args(
        path="/category/get_all",
    )

    response = client.get(**args)

    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}


def test_get_all_items(
    client, existing_user, existing_category, existing_feed, existing_item_strict, token
):
    args = build_api_request_args(
        path="/category/items",
        params={"category_name_hash": existing_category.name_hash},
        token=token,
    )

    response = client.get(**args)

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["url"] == str(existing_item_strict.url)
