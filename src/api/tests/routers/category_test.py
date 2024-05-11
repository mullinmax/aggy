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
