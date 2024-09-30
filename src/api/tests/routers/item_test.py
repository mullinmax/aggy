from tests.utils import build_api_request_args

from db.item_state import ItemState


def test_set_item_state(
    client,
    existing_user,
    existing_source,
    existing_category,
    existing_item_strict,
    token,
):
    item_state = ItemState.read(
        user_hash=existing_user.name_hash,
        category_hash=existing_category.name_hash,
        item_url_hash=existing_item_strict.url_hash,
    )
    assert item_state is None

    args = build_api_request_args(
        path="/item/set_state",
        token=token,
        params={
            "category_hash": existing_category.name_hash,
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
        category_hash=existing_category.name_hash,
        item_url_hash=existing_item_strict.url_hash,
    )
    assert item_state.score == 0.7631
    assert item_state.is_read


def test_get_item_state(
    client,
    existing_source,
    existing_category,
    existing_item_strict,
    existing_item_state,
    token,
):
    args = build_api_request_args(
        path="/item/get_state",
        token=token,
        params={
            "category_hash": existing_category.name_hash,
            "item_url_hash": existing_item_strict.url_hash,
        },
    )

    response = client.get(**args)
    print("response.json(): ", response.json())
    assert response.status_code == 200

    item_state = response.json()
    assert item_state["score"] == existing_item_state.score
    assert item_state["score_date"] == existing_item_state.score_date.isoformat()
    assert item_state["is_read"] == existing_item_state.is_read


def test_set_state_non_existent_category(
    client, existing_user, existing_source, existing_item_strict, token
):
    args = build_api_request_args(
        path="/item/set_state",
        token=token,
        params={
            "category_hash": "non_existent_category",
            "item_url_hash": existing_item_strict.url_hash,
            "score": 0.7631,
            "mark_as_read": True,
        },
    )

    response = client.post(**args)
    assert response.status_code == 404


def test_get_state_non_existent_item(
    client, existing_user, existing_source, existing_category, token
):
    args = build_api_request_args(
        path="/item/get_state",
        token=token,
        params={
            "category_hash": existing_category.name_hash,
            "item_url_hash": "non_existent_item",
        },
    )

    response = client.get(**args)
    assert response.status_code == 404
