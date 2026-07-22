"""Integration tests for feed item filters/sorts and the ranking endpoints."""

from pydantic import HttpUrl

from db.item_state import ItemState
from tests.testing_utils import build_api_request_args


def _make_items(existing_feed, existing_source, unique_item_strict, n=6):
    items = []
    for i in range(n):
        item = unique_item_strict.model_copy()
        item.url = HttpUrl(f"http://example.com/{i}/")
        item.image_url = f"http://example.com/{i}.jpg" if i % 2 == 0 else None
        # two well-separated clusters (even vs odd) with slight per-item jitter
        item.embeddings = {"test-model": [5.0 if i % 2 == 0 else -5.0, 0.1 * i]}
        item.create()
        existing_source.add_items(item)
        existing_feed.add_items(item)
        items.append(item)
    return items


def _get_items(client, token, feed, **params):
    args = build_api_request_args(
        path="/feed/items",
        params={"feed_name_hash": feed.name_hash, **params},
        token=token,
    )
    response = client.get(**args)
    assert response.status_code == 200
    return response.json()


def test_items_exclude_read(
    client, existing_user, existing_feed, existing_source, unique_item_strict, token
):
    items = _make_items(existing_feed, existing_source, unique_item_strict)
    ItemState.set_state(
        user_hash=existing_user.name_hash,
        feed_hash=existing_feed.name_hash,
        item_url_hash=items[0].url_hash,
        score=1,
        is_read=True,
    )

    unread = _get_items(client, token, existing_feed, include_read=False)
    assert len(unread) == len(items) - 1
    assert all(i["item_url"] != str(items[0].url) for i in unread)

    everything = _get_items(client, token, existing_feed, include_read=True)
    assert len(everything) == len(items)
    voted = next(i for i in everything if i["item_url"] == str(items[0].url))
    assert voted["item_user_score"] == 1


def test_items_neutral_vote_counts_as_read(
    client, existing_user, existing_feed, existing_source, existing_item_strict, token
):
    args = build_api_request_args(
        path="/item/set_state",
        params={
            "feed_hash": existing_feed.name_hash,
            "item_url_hash": existing_item_strict.url_hash,
            "score": 0,
        },
        token=token,
    )
    assert client.post(**args).status_code == 200

    assert _get_items(client, token, existing_feed, include_read=False) == []
    everything = _get_items(client, token, existing_feed, include_read=True)
    assert everything[0]["item_user_score"] == 0


def test_items_text_only_filter(
    client, existing_user, existing_feed, existing_source, unique_item_strict, token
):
    _make_items(existing_feed, existing_source, unique_item_strict)

    text = _get_items(client, token, existing_feed, text_only=True)
    assert text and all(i["item_image_url"] is None for i in text)

    visual = _get_items(client, token, existing_feed, text_only=False)
    assert visual and all(i["item_image_url"] is not None for i in visual)


def test_items_source_filter(
    client, existing_user, existing_feed, existing_source, unique_item_strict, token
):
    _make_items(existing_feed, existing_source, unique_item_strict, n=2)

    all_items = _get_items(
        client, token, existing_feed, sources=existing_source.name_hash
    )
    assert len(all_items) == 2

    none = _get_items(client, token, existing_feed, sources="nonexistent-source")
    assert none == []


def test_items_sort_newest_oldest(
    client, existing_user, existing_feed, existing_source, unique_item_strict, token
):
    from datetime import datetime, timedelta

    for i in range(3):
        item = unique_item_strict.model_copy()
        item.url = HttpUrl(f"http://example.com/{i}/")
        item.date_published = datetime(2024, 1, 1) + timedelta(days=i)
        item.create()
        existing_source.add_items(item)
        existing_feed.add_items(item)

    newest = _get_items(client, token, existing_feed, sort="newest")
    assert newest[0]["item_url"] == "http://example.com/2/"
    oldest = _get_items(client, token, existing_feed, sort="oldest")
    assert oldest[0]["item_url"] == "http://example.com/0/"


def test_items_bad_sort_rejected(client, existing_user, existing_feed, token):
    args = build_api_request_args(
        path="/feed/items",
        params={"feed_name_hash": existing_feed.name_hash, "sort": "bogus"},
        token=token,
    )
    assert client.get(**args).status_code == 422


def test_rerank_and_stats(
    client, existing_user, existing_feed, existing_source, unique_item_strict, token
):
    items = _make_items(existing_feed, existing_source, unique_item_strict)
    # vote along the embedding clusters: even items up, odd items down
    for i, item in enumerate(items[:4]):
        ItemState.set_state(
            user_hash=existing_user.name_hash,
            feed_hash=existing_feed.name_hash,
            item_url_hash=item.url_hash,
            score=1 if i % 2 == 0 else -1,
            is_read=True,
        )

    args = build_api_request_args(
        path="/feed/rerank",
        params={"feed_name_hash": existing_feed.name_hash},
        token=token,
    )
    response = client.post(**args)
    assert response.status_code == 200
    body = response.json()
    assert body["up_votes"] == 2
    assert body["down_votes"] == 2
    assert body["total_items"] == len(items)
    assert body["predicted_items"] == len(items)
    assert sum(1 for m in body["models"] if m["chosen"]) == 1

    # stats endpoint returns the persisted evaluation
    args = build_api_request_args(
        path="/feed/ranking_stats",
        params={"feed_name_hash": existing_feed.name_hash},
        token=token,
    )
    response = client.get(**args)
    assert response.status_code == 200
    stats = response.json()
    assert {m["model_name"] for m in stats["models"]} >= {
        "global_mean",
        "source_mean",
        "knn_embedding",
    }
    assert any(m["chosen"] for m in stats["models"])

    # predictions now drive the predicted sorts
    ranked = _get_items(client, token, existing_feed, sort="predicted")
    assert all(i["item_predicted_score"] is not None for i in ranked)
    scores = [i["item_predicted_score"] for i in ranked]
    assert scores == sorted(scores, reverse=True)
    worst_first = _get_items(client, token, existing_feed, sort="predicted_asc")
    assert [i["item_predicted_score"] for i in worst_first] == sorted(scores)
    # the confidence sorts order by how sure the model is, either direction
    confident = _get_items(client, token, existing_feed, sort="confident")
    confs = [i["item_predicted_confidence"] for i in confident]
    assert all(c is not None for c in confs)
    assert confs == sorted(confs, reverse=True)
    controversial = _get_items(client, token, existing_feed, sort="controversial")
    assert [i["item_predicted_confidence"] for i in controversial] == sorted(confs)
    # unvoted items get a prediction consistent with their cluster
    unvoted = {str(items[4].url): 1, str(items[5].url): -1}
    for entry in ranked:
        if entry["item_url"] in unvoted:
            assert entry["item_predicted_score"] * unvoted[entry["item_url"]] > 0


def test_item_explanation(
    client, existing_user, existing_feed, existing_source, unique_item_strict, token
):
    items = _make_items(existing_feed, existing_source, unique_item_strict)
    # even items up, odd down — the embedding cluster fully separates the vote
    for i, item in enumerate(items[:4]):
        ItemState.set_state(
            user_hash=existing_user.name_hash,
            feed_hash=existing_feed.name_hash,
            item_url_hash=item.url_hash,
            score=1 if i % 2 == 0 else -1,
            is_read=True,
        )

    args = build_api_request_args(
        path="/feed/item_explanation",
        params={
            "feed_name_hash": existing_feed.name_hash,
            "item_url_hash": items[4].url_hash,  # unvoted, even (liked) cluster
        },
        token=token,
    )
    response = client.get(**args)
    assert response.status_code == 200
    body = response.json()
    assert body["model_name"]
    fields = {f["field"]: f for f in body["fields"]}
    # text and image are scored as separate pieces, never lumped as "content"
    assert {"text", "image", "source", "author", "recency", "media"} <= set(fields)
    assert "content" not in fields
    # every field reports a valid mark count and direction
    for f in body["fields"]:
        assert f["level"] in (0, 1, 2)
        assert f["sign"] in (-1, 0, 1)
        assert (f["level"] == 0) == (f["sign"] == 0)
    # text (the embedding) drives this recommendation and pushes it up
    assert fields["text"]["level"] >= 1
    assert fields["text"]["sign"] == 1

    # every field carries a plain-language description and a preview of exactly
    # what was evaluated for this article
    assert all(f["description"] for f in body["fields"])
    assert all(f["preview"] is not None for f in body["fields"])
    # the preview is this article's own data (same across fields, one per piece)
    text_preview = fields["text"]["preview"]
    assert text_preview["text"]  # the item's title/excerpt
    assert fields["image"]["preview"]["has_image"] is True  # item[4] is even/imaged


def test_item_explanation_needs_votes(
    client, existing_user, existing_feed, existing_source, existing_item_strict, token
):
    args = build_api_request_args(
        path="/feed/item_explanation",
        params={
            "feed_name_hash": existing_feed.name_hash,
            "item_url_hash": existing_item_strict.url_hash,
        },
        token=token,
    )
    assert client.get(**args).status_code == 409


def test_ranking_stats_empty_feed(client, existing_user, existing_feed, token):
    args = build_api_request_args(
        path="/feed/ranking_stats",
        params={"feed_name_hash": existing_feed.name_hash},
        token=token,
    )
    response = client.get(**args)
    assert response.status_code == 200
    body = response.json()
    assert body["models"] == []
    assert body["up_votes"] == 0
    assert body["total_items"] == 0
