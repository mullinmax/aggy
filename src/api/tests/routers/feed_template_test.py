from tests.utils import build_api_request_args

from db.feed import Feed


def test_create_feed_template(unique_feed_template):
    assert unique_feed_template.exists() is False
    unique_feed_template.create()
    assert unique_feed_template.exists() is True


def test_list_all_templates(client, existing_feed_template, token):
    args = build_api_request_args(
        path="/feed_template/list_all",
        token=token,
    )

    response = client.get(**args)

    assert response.status_code == 200
    assert existing_feed_template.name_hash in response.json()


def test_create_feed_from_template(
    client, existing_feed_template, existing_category, token, unique_feed
):
    args = build_api_request_args(
        path="/feed_template/create",
        token=token,
        data={
            "feed_template_name_hash": existing_feed_template.name_hash,
            "category_hash": existing_category.name_hash,
            "feed_name": unique_feed.name,
            "parameters": {"parameter_name": "value"},
        },
    )

    response = client.post(**args)

    assert response.status_code == 200
    res_data = response.json()

    new_feed = Feed.read_by_key(unique_feed.key)

    assert new_feed.exists()
    assert new_feed.name == unique_feed.name

    assert res_data["feed_name"] == new_feed.name
    assert res_data["feed_name_hash"] == new_feed.name_hash
    assert (
        res_data["feed_url"]
        == "http://dev-aggy-rss-bridge/?action=display&bridge=test&format=Atom&context=by+user&parameter_name=value"
    )
    assert str(new_feed.url) == res_data["feed_url"]
    assert res_data["feed_category"] == existing_category.name_hash


def test_get_feed_template(client, existing_feed_template, token):
    args = build_api_request_args(
        path="/feed_template/get",
        token=token,
        params={"name_hash": existing_feed_template.name_hash},
    )

    response = client.get(**args)

    assert response.status_code == 200
    res_data = response.json()

    print("res_data: ", res_data)
    print(type(existing_feed_template.json))
    assert res_data["name"] == existing_feed_template.name
    assert res_data["context"] == existing_feed_template.context
    assert res_data["bridge_short_name"] == existing_feed_template.bridge_short_name


def test_get_nonexistent_feed_template(client, token):
    args = build_api_request_args(
        path="/feed_template/get",
        token=token,
        params={"name_hash": "nonexistent_feed_template"},
    )

    response = client.get(**args)

    assert response.status_code == 404


def create_feed_with_nonexistent_template(
    client, existing_category, token, unique_feed
):
    args = build_api_request_args(
        path="/feed_template/create",
        token=token,
        data={
            "feed_template_name_hash": "nonexistent_feed_template",
            "category_hash": existing_category.name_hash,
            "feed_name": unique_feed.name,
            "parameters": {"parameter_name": "value"},
        },
    )

    response = client.post(**args)

    assert response.status_code == 404
