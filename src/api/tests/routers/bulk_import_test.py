from builtin_templates import builtin_template, create_builtin_source_templates
from tests.testing_utils import build_api_request_args


def parse_args(data, token):
    return build_api_request_args(path="/import/parse", data=data, token=token)


def create_args(sources, token):
    return build_api_request_args(
        path="/import/create", data={"sources": sources}, token=token
    )


def test_parse_requires_auth(client):
    response = client.post(
        "/import/parse", json={"platform": "reddit", "data": "r/selfhosted"}
    )

    assert response.status_code == 401


def test_parse_reddit(client, token):
    args = parse_args(
        {"platform": "reddit", "data": "r/selfhosted\nr/alligators"}, token
    )

    response = client.post(**args)

    assert response.status_code == 200
    body = response.json()
    assert [c["name"] for c in body["candidates"]] == ["r/selfhosted", "r/alligators"]
    assert body["candidates"][0]["template_parameters"] == {"subreddit": "selfhosted"}


def test_parse_opml_with_groups(client, token):
    opml = (
        '<opml version="2.0"><body><outline text="Tech">'
        '<outline text="HN" xmlUrl="https://news.ycombinator.com/rss"/>'
        "</outline></body></opml>"
    )
    args = parse_args({"platform": "opml", "data": opml}, token)

    response = client.post(**args)

    assert response.status_code == 200
    body = response.json()
    assert body["candidates"] == [
        {
            "name": "HN",
            "url": "https://news.ycombinator.com/rss",
            "group": "Tech",
            "template_name_hash": None,
            "template_parameters": None,
            "error": None,
        }
    ]


def test_parse_empty_data_rejected(client, token):
    args = parse_args({"platform": "reddit", "data": "   "}, token)

    response = client.post(**args)

    assert response.status_code == 422


def test_parse_no_candidates_rejected(client, token):
    args = parse_args({"platform": "reddit", "data": "!!!"}, token)

    response = client.post(**args)

    assert response.status_code == 422


def test_parse_bluesky_requires_username(client, token):
    args = parse_args({"platform": "bluesky"}, token)

    response = client.post(**args)

    assert response.status_code == 422


def test_bulk_create_raw_urls(client, existing_feed, token):
    sources = [
        {
            "feed_name_hash": existing_feed.name_hash,
            "source_name": "HN",
            "source_url": "https://news.ycombinator.com/rss",
        },
        {
            "feed_name_hash": existing_feed.name_hash,
            "source_name": "Lobsters",
            "source_url": "https://lobste.rs/rss",
        },
    ]

    response = client.post(**create_args(sources, token))

    assert response.status_code == 200
    body = response.json()
    assert body["created"] == 2
    assert body["duplicates"] == 0
    assert body["errors"] == 0
    assert {r["status"] for r in body["results"]} == {"created"}

    # importing the same rows again reports duplicates instead of failing
    response = client.post(**create_args(sources, token))

    assert response.status_code == 200
    body = response.json()
    assert body["created"] == 0
    assert body["duplicates"] == 2


def test_bulk_create_from_template(client, existing_feed, token):
    create_builtin_source_templates()
    template = builtin_template("Reddit Subreddit")
    sources = [
        {
            "feed_name_hash": existing_feed.name_hash,
            "source_name": "r/selfhosted",
            "template_name_hash": template.name_hash,
            "template_parameters": {"subreddit": "selfhosted"},
        }
    ]

    response = client.post(**create_args(sources, token))

    assert response.status_code == 200
    assert response.json()["created"] == 1

    created = existing_feed.sources[0]
    assert str(created.url) == "https://www.reddit.com/r/selfhosted/top.rss?t=day"


def test_bulk_create_reports_per_row_errors(client, existing_feed, token):
    sources = [
        {
            "feed_name_hash": "not_a_feed",
            "source_name": "HN",
            "source_url": "https://news.ycombinator.com/rss",
        },
        {
            "feed_name_hash": existing_feed.name_hash,
            "source_name": "No URL",
        },
        {
            "feed_name_hash": existing_feed.name_hash,
            "source_name": "Bad URL",
            "source_url": "not a url",
        },
        {
            "feed_name_hash": existing_feed.name_hash,
            "source_name": "Good",
            "source_url": "https://example.com/feed.xml",
        },
    ]

    response = client.post(**create_args(sources, token))

    assert response.status_code == 200
    body = response.json()
    assert body["created"] == 1
    assert body["errors"] == 3
    statuses = {r["source_name"]: r["status"] for r in body["results"]}
    assert statuses == {
        "HN": "error",
        "No URL": "error",
        "Bad URL": "error",
        "Good": "created",
    }
    assert (
        next(r for r in body["results"] if r["source_name"] == "HN")["detail"]
        == "Feed not found"
    )
