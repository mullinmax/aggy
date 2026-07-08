from tests.testing_utils import build_api_request_args

from db.source import Source
from db.source_template import SourceTemplate


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
    client, existing_source_template, existing_feed, token, unique_source
):
    args = build_api_request_args(
        path="/source_template/create",
        token=token,
        data={
            "source_template_name_hash": existing_source_template.name_hash,
            "feed_hash": existing_feed.name_hash,
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
    assert res_data["source_feed"] == existing_feed.name_hash


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
    client, existing_feed, token, unique_source
):
    args = build_api_request_args(
        path="/source_template/create",
        token=token,
        data={
            "source_template_name_hash": "nonexistent_source_template",
            "feed_hash": existing_feed.name_hash,
            "source_name": unique_source.name,
            "parameters": {"parameter_name": "value"},
        },
    )

    response = client.post(**args)

    assert response.status_code == 404


def _make_dummy_templates(count):
    templates = []
    for i in range(count):
        template = SourceTemplate(
            name=f"test_template_{i}",
            context="test",
            bridge_short_name="test",
            url="http://example.com",
            description="Dummy template",
            parameters={},
        )
        template.create()
        templates.append(template)
    return templates


def test_search_source_templates(client, existing_source_template, token):
    dummies = _make_dummy_templates(5)

    try:
        args = build_api_request_args(
            path="/source_template/search",
            token=token,
            params={
                "query": existing_source_template.name,
                "limit": "3",
            },
        )

        response = client.get(**args)

        assert response.status_code == 200
        res_data = response.json()

        assert isinstance(res_data, list)
        assert len(res_data) == 3
        # best match first, and the hash is included for follow-up requests
        assert res_data[0]["name"] == existing_source_template.name
        assert res_data[0]["name_hash"] == existing_source_template.name_hash
    finally:
        for template in dummies:
            template.delete()


def test_search_without_query_returns_all(client, existing_source_template, token):
    dummies = _make_dummy_templates(3)

    try:
        args = build_api_request_args(path="/source_template/search", token=token)

        response = client.get(**args)

        assert response.status_code == 200
        res_data = response.json()

        names = [t["name"] for t in res_data]
        assert existing_source_template.name in names
        for template in dummies:
            assert template.name in names
        # alphabetized by user-friendly name
        friendly = [t["user_friendly_name"].lower() for t in res_data]
        assert friendly == sorted(friendly)
    finally:
        for template in dummies:
            template.delete()


def test_search_returns_minimum_results_for_bad_query(
    client, existing_source_template, token
):
    dummies = _make_dummy_templates(5)

    try:
        args = build_api_request_args(
            path="/source_template/search",
            token=token,
            params={"query": "zzzzqqqqxxxx no such thing 12345"},
        )

        response = client.get(**args)

        assert response.status_code == 200
        assert len(response.json()) >= 4
    finally:
        for template in dummies:
            template.delete()


def test_create_duplicate_source_from_template_conflict(
    client, existing_source_template, existing_feed, token, unique_source
):
    data = {
        "source_template_name_hash": existing_source_template.name_hash,
        "feed_hash": existing_feed.name_hash,
        "source_name": unique_source.name,
        "parameters": {"parameter_name": "value"},
    }
    args = build_api_request_args(path="/source_template/create", token=token, data=data)

    response = client.post(**args)
    assert response.status_code == 200

    # same name again — must be rejected instead of silently ignored
    response = client.post(**args)
    assert response.status_code == 409


def test_update_source_template_parameters(
    client, existing_source_template, existing_feed, token, unique_source
):
    args = build_api_request_args(
        path="/source_template/create",
        token=token,
        data={
            "source_template_name_hash": existing_source_template.name_hash,
            "feed_hash": existing_feed.name_hash,
            "source_name": unique_source.name,
            "parameters": {"parameter_name": "value"},
        },
    )
    response = client.post(**args)
    assert response.status_code == 200
    created = response.json()
    assert created["source_template_name_hash"] == existing_source_template.name_hash
    assert created["source_template_parameters"] == {"parameter_name": "value"}

    # change the parameter; the source URL is rebuilt from the template
    args = build_api_request_args(
        path="/source/update",
        token=token,
        data={
            "feed_name_hash": existing_feed.name_hash,
            "source_name_hash": created["source_name_hash"],
            "source_name": created["source_name"],
            "parameters": {"parameter_name": "other_value"},
        },
    )
    response = client.post(**args)
    assert response.status_code == 200
    updated = response.json()
    assert "parameter_name=other_value" in updated["source_url"]
    assert updated["source_template_parameters"] == {"parameter_name": "other_value"}


def test_update_source_template_bad_parameters(
    client, existing_source_template, existing_feed, token, unique_source
):
    args = build_api_request_args(
        path="/source_template/create",
        token=token,
        data={
            "source_template_name_hash": existing_source_template.name_hash,
            "feed_hash": existing_feed.name_hash,
            "source_name": unique_source.name,
            "parameters": {"parameter_name": "value"},
        },
    )
    response = client.post(**args)
    assert response.status_code == 200
    created = response.json()

    args = build_api_request_args(
        path="/source/update",
        token=token,
        data={
            "feed_name_hash": existing_feed.name_hash,
            "source_name_hash": created["source_name_hash"],
            "source_name": created["source_name"],
            "parameters": {"parameter_name": "not_an_option"},
        },
    )
    response = client.post(**args)
    assert response.status_code == 422
