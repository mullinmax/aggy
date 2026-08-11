from db.item import ItemLoose
from tests.testing_utils import build_api_request_args


def add_item(feed, url, **overrides):
    fields = {
        "url": url,
        "title": "Title",
        "domain": "example.com",
        "excerpt": "Excerpt",
        "content": "<p>Article body</p>",
        "author": "Author",
    }
    fields.update(overrides)
    item = ItemLoose(**fields)
    item.create(overwrite=True)
    feed.add_items(item)
    return item


def test_article_stats_requires_auth(client):
    response = client.get(**build_api_request_args(path="/stats/articles"))

    assert response.status_code == 401


def test_article_stats_empty(client, existing_user, token):
    args = build_api_request_args(path="/stats/articles", token=token)

    response = client.get(**args)

    assert response.status_code == 200
    body = response.json()
    assert body["domains"] == []
    assert body["summary"]["total_articles"] == 0
    assert body["summary"]["domain_count"] == 0
    assert len(body["timeline"]) == 31


def test_article_stats_by_domain(client, existing_user, existing_feed, token):
    add_item(
        existing_feed,
        "https://www.reddit.com/r/a/1",
        image_url="https://i.redd.it/a.jpg",
        image_embeddings={"clip": [0.1]},
        embeddings={"text-model": [0.2]},
    )
    add_item(existing_feed, "https://old.reddit.com/r/a/2", content="text only")
    add_item(existing_feed, "https://example.com/a", content="text only")

    args = build_api_request_args(
        path="/stats/articles", params={"timeline_days": 7}, token=token
    )

    response = client.get(**args)

    assert response.status_code == 200
    body = response.json()

    assert body["summary"]["total_articles"] == 3
    assert body["summary"]["domain_count"] == 2
    assert body["summary"]["with_preview_image"] == 1
    assert body["summary"]["with_image_embedding"] == 1
    assert body["summary"]["with_text_embedding"] == 1

    reddit, example = body["domains"]
    assert reddit["domain"] == "reddit.com"
    assert reddit["article_count"] == 2
    assert reddit["with_preview_image"] == 1
    assert example["domain"] == "example.com"
    assert example["article_count"] == 1

    assert len(body["timeline"]) == 8
    assert body["timeline"][-1]["article_count"] == 3


def test_article_stats_rejects_out_of_range_timeline(client, existing_user, token):
    args = build_api_request_args(
        path="/stats/articles", params={"timeline_days": 0}, token=token
    )

    response = client.get(**args)

    assert response.status_code == 422
