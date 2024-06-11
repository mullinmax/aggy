from tests.utils import build_api_request_args


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


# TODO fix once db tests are done
# def test_create_feed_from_template(client, existing_feed_template, existing_category, token):
#     args = build_api_request_args(
#         path="/feed_template/create",
#         data={
#             "feed_template_name_hash": existing_feed_template.name_hash,
#             "category_hash": existing_category.name_hash,
#             "feed_name": "Test Feed",
#             "parameters": {"param_name": "value"},
#         },
#         token=token,
#     )

#     response = client.post(**args)

#     print(response.json())
#     print(response)

#     assert response.status_code == 200
#     assert response.json()["name"] == feed_name
#     assert response.json()["url"] == "http://example.com?param_name=value"
