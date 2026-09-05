"""Integration tests for feed item filters/sorts and the ranking endpoints."""

import time

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


def _rerank(client, token, feed):
    args = build_api_request_args(
        path="/feed/rerank",
        params={"feed_name_hash": feed.name_hash},
        token=token,
    )
    response = client.post(**args)
    assert response.status_code == 200
    return response.json()


def _training_status(client, token, feed):
    args = build_api_request_args(
        path="/feed/training_status",
        params={"feed_name_hash": feed.name_hash},
        token=token,
    )
    response = client.get(**args)
    assert response.status_code == 200
    return response.json()


def _wait_for_training(client, token, feed, timeout=60.0):
    """Block until the feed's background training run reports a result."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = _training_status(client, token, feed)
        run = status["training"]
        assert run is not None, "the training run went missing"
        if run["status"] != "running":
            assert run["status"] == "done", run["error"]
            return status
        time.sleep(0.05)
    raise AssertionError("training did not finish in time")


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


# Comfortably past db.feed.TEXT_BODY_MIN_CHARS, so the item reads as a post
# with a body of its own rather than a bare pointer at another page.
LONG_BODY = "A properly written article body, with something to say. " * 4


def _post_type_items(existing_feed, existing_source, unique_item_strict):
    """One item of each shape the post-type filter is meant to tell apart."""
    shapes = {
        # an illustrated article: a picture and a body, so image *and* text
        "article": {"content": LONG_BODY, "excerpt": LONG_BODY},
        # a picture post: a photo with a caption, nothing to read
        "photo": {},
        # a video listing entry: playable, no picture of its own
        "video": {
            "image_url": None,
            "media": [{"type": "stream", "url": "http://example.com/video/"}],
        },
        # a link post pointing off-site
        "link": {
            "image_url": None,
            "media": [{"type": "link", "url": "http://elsewhere.example.com/story"}],
        },
        # no picture, no media and nothing to read: a bare pointer
        "stub": {"image_url": None, "excerpt": "click here", "content": "click here"},
    }
    for name, overrides in shapes.items():
        item = unique_item_strict.model_copy()
        item.url = HttpUrl(f"http://example.com/{name}/")
        for field, value in overrides.items():
            setattr(item, field, value)
        item.create()
        existing_source.add_items(item)
        existing_feed.add_items(item)
    return {name: f"http://example.com/{name}/" for name in shapes}


def test_items_post_type_filter(
    client, existing_user, existing_feed, existing_source, unique_item_strict, token
):
    url = _post_type_items(existing_feed, existing_source, unique_item_strict)

    def urls(**params):
        items = _get_items(client, token, existing_feed, **params)
        return {i["item_url"] for i in items}

    assert urls(post_types="image") == {url["article"], url["photo"]}
    assert urls(post_types="video") == {url["video"]}
    assert urls(post_types="text") == {url["article"]}
    # a link card, and a post that is nothing but a pointer, both read as links
    assert urls(post_types="link") == {url["link"], url["stub"]}

    # ticked types add up rather than narrow each other down
    assert urls(post_types="video,link") == {url["video"], url["link"], url["stub"]}
    # and every item answers to at least one type, so ticking them all is the
    # same view as ticking none
    assert urls(post_types="image,video,link,text") == urls()


def test_items_youtube_url_counts_as_video(
    client, existing_user, existing_feed, existing_source, unique_item_strict, token
):
    """A YouTube link plays inline with no stored media entry, so it counts as
    a video post even though nothing was ingested for it."""
    unique_item_strict.url = HttpUrl("https://www.youtube.com/watch?v=abcdefghijk")
    unique_item_strict.create()
    existing_source.add_items(unique_item_strict)
    existing_feed.add_items(unique_item_strict)

    assert len(_get_items(client, token, existing_feed, post_types="video")) == 1


def test_items_no_post_types_selected_is_empty(
    client, existing_user, existing_feed, existing_source, unique_item_strict, token
):
    """Clearing every box shows nothing, which is what the panel then says."""
    _make_items(existing_feed, existing_source, unique_item_strict, n=2)

    assert _get_items(client, token, existing_feed, post_types="") == []


def test_items_bad_post_type_rejected(client, existing_user, existing_feed, token):
    args = build_api_request_args(
        path="/feed/items",
        params={"feed_name_hash": existing_feed.name_hash, "post_types": "hologram"},
        token=token,
    )
    assert client.get(**args).status_code == 422


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


def test_items_max_age_filter(
    client, existing_user, existing_feed, existing_source, unique_item_strict, token
):
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    ages = {
        "fresh": timedelta(hours=2),
        "this-week": timedelta(days=3),
        "old": timedelta(days=40),
    }
    for name, age in ages.items():
        item = unique_item_strict.model_copy()
        item.url = HttpUrl(f"http://example.com/{name}/")
        item.date_published = now - age
        item.create()
        existing_source.add_items(item)
        existing_feed.add_items(item)

    def urls(**params):
        items = _get_items(client, token, existing_feed, **params)
        return {i["item_url"] for i in items}

    assert urls(max_age="day") == {"http://example.com/fresh/"}
    assert urls(max_age="week") == {
        "http://example.com/fresh/",
        "http://example.com/this-week/",
    }
    # "month" is a 30-day window, so the 40-day-old item drops out
    assert len(urls(max_age="month")) == 2
    assert len(urls(max_age="year")) == 3
    assert len(urls(max_age="all")) == 3
    # the default keeps every item, same as "all"
    assert len(urls()) == 3


def test_items_max_age_falls_back_to_added_at(
    client, existing_user, existing_feed, existing_source, unique_item_strict, token
):
    """Items with no publish date are dated by when the feed picked them up."""
    unique_item_strict.date_published = None
    unique_item_strict.create()
    existing_source.add_items(unique_item_strict)
    existing_feed.add_items(unique_item_strict)

    assert len(_get_items(client, token, existing_feed, max_age="day")) == 1


def test_items_bad_max_age_rejected(client, existing_user, existing_feed, token):
    args = build_api_request_args(
        path="/feed/items",
        params={"feed_name_hash": existing_feed.name_hash, "max_age": "decade"},
        token=token,
    )
    assert client.get(**args).status_code == 422


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

    body = _rerank(client, token, existing_feed)
    assert body["up_votes"] == 2
    assert body["down_votes"] == 2
    assert body["total_items"] == len(items)
    # training runs in the background, so the snapshot the request returns is
    # the state it started from; the votes are all newer than the last (never)
    # training run
    assert body["votes_since_training"] == 4

    status = _wait_for_training(client, token, existing_feed)
    assert status["training"]["status"] == "done"
    assert status["last_trained_at"] is not None
    assert status["trained_model"]
    assert status["trained_labels"] == 4
    # everything the models learned from is now accounted for
    assert status["votes_since_training"] == 0

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
    assert stats["predicted_items"] == len(items)
    assert sum(1 for m in stats["models"] if m["chosen"]) == 1

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
    image_preview = fields["image"]["preview"]
    assert image_preview["has_image"] is True  # item[4] is even/imaged
    # no vision model in the test, so the image is scored by presence only
    assert image_preview["image_embedded"] is False


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
