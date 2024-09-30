from tests.utils import build_api_request_args

from db.source import Source


def test_create_source_template(unique_source_template):
    assert unique_source_template.exists() is False
    unique_source_template.create()
    assert unique_source_template.exists() is True


def test_list_all_templates(client, existing_source_template, token):
    args = build_api_request_args(
        path="/source_template/list_all",
        token=token,
    )

    response = client.get(**args)

    assert response.status_code == 200
    assert existing_source_template.name_hash in response.json()


def test_create_source_from_template(
    client, existing_source_template, existing_category, token, unique_source
):
    args = build_api_request_args(
        path="/source_template/create",
        token=token,
        data={
            "source_template_name_hash": existing_source_template.name_hash,
            "category_hash": existing_category.name_hash,
            "source_name": unique_source.name,
            "parameters": {"parameter_name": "value"},
        },
    )

    response = client.post(**args)

    assert response.status_code == 200
    res_data = response.json()

    new_source = Source.read_by_key(unique_source.key)

    assert new_source.exists()
    assert new_source.name == unique_source.name

    assert res_data["source_name"] == new_source.name
    assert res_data["source_name_hash"] == new_source.name_hash
    assert (
        res_data["source_url"]
        == "http://dev-aggy-rss-bridge/?action=display&bridge=test&format=Atom&context=by+user&parameter_name=value"
    )
    assert str(new_source.url) == res_data["source_url"]
    assert res_data["source_category"] == existing_category.name_hash


def test_get_source_template(client, existing_source_template, token):
    args = build_api_request_args(
        path="/source_template/get",
        token=token,
        params={"name_hash": existing_source_template.name_hash},
    )

    response = client.get(**args)

    assert response.status_code == 200
    res_data = response.json()

    print("res_data: ", res_data)
    print(type(existing_source_template.json))
    assert res_data["name"] == existing_source_template.name
    assert res_data["context"] == existing_source_template.context
    assert res_data["bridge_short_name"] == existing_source_template.bridge_short_name


def test_get_nonexistent_source_template(client, token):
    args = build_api_request_args(
        path="/source_template/get",
        token=token,
        params={"name_hash": "nonexistent_source_template"},
    )

    response = client.get(**args)

    assert response.status_code == 404


def create_source_with_nonexistent_template(
    client, existing_category, token, unique_source
):
    args = build_api_request_args(
        path="/source_template/create",
        token=token,
        data={
            "source_template_name_hash": "nonexistent_source_template",
            "category_hash": existing_category.name_hash,
            "source_name": unique_source.name,
            "parameters": {"parameter_name": "value"},
        },
    )

    response = client.post(**args)

    assert response.status_code == 404
