import pytest

from db.feed import Feed


def test_key(unique_feed):
    """Tests the key property."""
    assert (
        unique_feed.key == f"USER:{unique_feed.user_hash}:FEED:{unique_feed.name_hash}"
    )


def test_items_key(unique_feed):
    """Tests the items_key property."""
    assert (
        unique_feed.items_key
        == f"USER:{unique_feed.user_hash}:FEED:{unique_feed.name_hash}:ITEMS"
    )


def test_sources_key(unique_feed):
    """Tests the sources_key property."""
    assert (
        unique_feed.sources_key
        == f"USER:{unique_feed.user_hash}:FEED:{unique_feed.name_hash}:SOURCES"
    )


def test_feed_creation(existing_user, existing_feed):
    """Tests creation of a feed."""
    assert existing_feed.exists()

    assert existing_feed in existing_user.feeds

    existing_feed.delete()
    assert not existing_feed.exists()


def test_feed_duplicate_creation(unique_feed):
    """Tests that creating a duplicate feed raises an exception."""
    unique_feed.create()

    with pytest.raises(Exception) as e:
        unique_feed.create()  # Attempt to create duplicate feed
    assert "already exists" in str(e.value), "Should not allow duplicate feeds"


def test_feed_read(unique_feed):
    """Tests reading a feed back from the database."""
    unique_feed.create()
    read_feed = Feed.read(
        user_hash=unique_feed.user_hash, name_hash=unique_feed.name_hash
    )
    assert read_feed is not None, "Feed should be readable"
    assert read_feed.name == unique_feed.name, "Feed name should match"


def test_feed_read_all(existing_user):
    """Tests reading all feeds for a user."""
    for i in range(3):
        Feed(user_hash=existing_user.name_hash, name=f"feed-{i}").create()

    feeds = Feed.read_all(existing_user.name_hash)
    assert len(feeds) == 3, "Should read all feeds for a user"

    for feed in feeds:
        assert (
            feed.user_hash == existing_user.name_hash
        ), "Feed should be for the correct user"


@pytest.mark.filterwarnings("ignore::UserWarning")
def test_get_items(unique_feed, unique_item_strict):
    """Tests getting all items for a feed."""
    unique_feed.create()

    items = [unique_item_strict.model_copy() for i in range(3)]

    for i, item in enumerate(items):
        item.url = f"http://example.com/{i}"
        item.create()
        unique_feed.set_items_scores({item.url_hash: i})

    act_items = unique_feed.query_items()
    assert len(act_items) == 3, "Should get all items for a feed"
    for item in act_items:
        assert item.url_hash in [
            i.url_hash for i in items
        ], "Should get the correct items"


@pytest.mark.filterwarnings("ignore::UserWarning")
def test_get_items_with_limit(unique_feed, unique_item_strict):
    """Tests getting all items for a feed with a limit."""
    unique_feed.create()

    items = [unique_item_strict.model_copy() for i in range(3)]

    for i, item in enumerate(items):
        item.url = f"http://example.com/{i}"
        item.create()
        unique_feed.set_items_scores({item.url_hash: i})

    act_items = unique_feed.query_items(limit=2)
    assert len(act_items) == 2, "Should get all items for a feed"
    for item in act_items:
        assert item.url_hash in [
            i.url_hash for i in items
        ], "Should get the correct items"


@pytest.mark.filterwarnings("ignore::UserWarning")
def test_get_items_with_skip(unique_feed, unique_item_strict):
    """Tests getting all items for a feed with a skip."""
    unique_feed.create()

    items = [unique_item_strict.model_copy() for i in range(3)]

    for i, item in enumerate(items):
        item.url = f"http://example.com/{i}"
        item.create()
        unique_feed.set_items_scores({item.url_hash: i})

    act_items = unique_feed.query_items(skip=1)
    assert len(act_items) == 2, "Should get all items for a feed"
    for item in act_items:
        assert item.url_hash in [
            i.url_hash for i in items
        ], "Should get the correct items"


@pytest.mark.filterwarnings("ignore::UserWarning")
def test_get_items_with_skip_and_limit(unique_feed, unique_item_strict):
    """Tests getting all items for a feed with a skip and limit."""
    unique_feed.create()

    items = [unique_item_strict.model_copy() for i in range(3)]

    for i, item in enumerate(items):
        item.url = f"http://example.com/{i}"
        item.create()
        unique_feed.set_items_scores({item.url_hash: i})

    act_items = unique_feed.query_items(skip=1, limit=1)
    assert len(act_items) == 1, "Should get all items for a feed"
    for item in act_items:
        assert item.url_hash in [
            i.url_hash for i in items
        ], "Should get the correct items"


def test_sources(unique_feed, unique_source):
    """Tests adding and removing sources from a feed."""
    # the unique_source fixture's existing_feed dependency already
    # persisted this feed
    if not unique_feed.exists():
        unique_feed.create()

    unique_feed.add_source(unique_source)
    assert unique_source.name_hash in unique_feed.source_hashes
    assert len(unique_feed.source_hashes) == 1
    assert unique_source in unique_feed.sources
    assert unique_source.exists()

    unique_feed.delete_source(unique_source)
    assert unique_source.name_hash not in unique_feed.source_hashes
    assert not unique_source.exists()


def test_delete_feed_removes_sources(unique_feed, unique_source):
    """Tests that deleting a feed removes its sources."""
    # the unique_source fixture's existing_feed dependency already
    # persisted this feed
    if not unique_feed.exists():
        unique_feed.create()
    unique_feed.add_source(unique_source)

    assert unique_feed.exists()
    assert unique_source.exists()

    unique_feed.delete()
    assert not unique_source.exists()
    assert not unique_feed.exists()


def test_remove_items(unique_feed, unique_item_strict):
    """Tests removing items from a feed."""
    unique_feed.create()
    unique_item_strict.create()
    unique_feed.add_items(unique_item_strict)

    assert unique_item_strict in unique_feed.query_items()

    unique_feed.remove_items(unique_item_strict)
    assert unique_item_strict not in unique_feed.query_items()
    assert unique_item_strict.exists()


def _make_source(feed, name):
    from db.source import Source

    source = Source(
        user_hash=feed.user_hash,
        feed_hash=feed.name_hash,
        name=name,
        url="http://example.com",
    )
    feed.add_source(source)
    return source


def _add_item(feed, source, item, url, score, **overrides):
    new = item.model_copy()
    new.url = url
    for field, value in overrides.items():
        setattr(new, field, value)
    new.create()
    if source is not None:
        source.add_items(new)
    feed.add_items(new)
    feed.set_items_scores({new.url_hash: score})
    return new


@pytest.mark.filterwarnings("ignore::UserWarning")
def test_query_items_text_only_counts_content_images(unique_feed, unique_item_strict):
    """A content-embedded <img> counts as visual media for text_only."""
    unique_feed.create()

    visual = _add_item(
        unique_feed,
        None,
        unique_item_strict,
        "http://example.com/content-img",
        2,
        image_url=None,
        media=None,
        content='<p>words</p><img src="http://example.com/pic.jpg">',
    )
    text = _add_item(
        unique_feed,
        None,
        unique_item_strict,
        "http://example.com/plain-text",
        1,
        image_url=None,
        media=None,
        content="<p>just words</p>",
    )

    with_media = unique_feed.query_items_with_sources(text_only=False)
    assert [item.url_hash for item, _ in with_media] == [visual.url_hash]

    text_only = unique_feed.query_items_with_sources(text_only=True)
    assert [item.url_hash for item, _ in text_only] == [text.url_hash]

    everything = unique_feed.query_items_with_sources(text_only=None)
    assert len(everything) == 2


@pytest.mark.filterwarnings("ignore::UserWarning")
def test_query_items_text_only_counts_media_list(unique_feed, unique_item_strict):
    """Ingested media counts as visual; an empty media list does not."""
    unique_feed.create()

    gif = _add_item(
        unique_feed,
        None,
        unique_item_strict,
        "http://example.com/gif",
        2,
        image_url=None,
        media=[{"type": "gif", "url": "http://example.com/a.mp4"}],
        content="<p>words</p>",
    )
    _add_item(
        unique_feed,
        None,
        unique_item_strict,
        "http://example.com/scraped-no-media",
        1,
        image_url=None,
        media=[],
        content="<p>words</p>",
    )

    with_media = unique_feed.query_items_with_sources(text_only=False)
    assert [item.url_hash for item, _ in with_media] == [gif.url_hash]


@pytest.mark.filterwarnings("ignore::UserWarning")
def test_query_items_interleaves_sources(unique_feed, unique_item_strict):
    """Items alternate between sources while respecting the sort order."""
    unique_feed.create()
    source_a = _make_source(unique_feed, "source-a")
    source_b = _make_source(unique_feed, "source-b")

    # source-a's items all outscore source-b's, so a plain sort would put
    # all of source-a first
    _add_item(unique_feed, source_a, unique_item_strict, "http://example.com/a1", 40)
    _add_item(unique_feed, source_a, unique_item_strict, "http://example.com/a2", 30)
    _add_item(unique_feed, source_b, unique_item_strict, "http://example.com/b1", 20)
    _add_item(unique_feed, source_b, unique_item_strict, "http://example.com/b2", 10)

    results = unique_feed.query_items_with_sources(sort="best")
    names = [meta["source_name"] for _, meta in results]
    assert names == ["source-a", "source-b", "source-a", "source-b"]


@pytest.mark.filterwarnings("ignore::UserWarning")
def test_query_items_predicted_sort_is_monotonic(unique_feed, unique_item_strict):
    """Prediction sorts return strict sort order, not interleaved by source, so
    the feed's threshold dividers land on a monotonic ranking."""
    unique_feed.create()
    source_a = _make_source(unique_feed, "source-a")
    source_b = _make_source(unique_feed, "source-b")

    # every source-a item is predicted higher than every source-b item; the
    # interleaved browse sort would zig-zag between sources, but a prediction
    # sort must keep the scores strictly descending
    items = [
        _add_item(unique_feed, source_a, unique_item_strict, "http://example.com/a1", 0),
        _add_item(unique_feed, source_a, unique_item_strict, "http://example.com/a2", 0),
        _add_item(unique_feed, source_b, unique_item_strict, "http://example.com/b1", 0),
        _add_item(unique_feed, source_b, unique_item_strict, "http://example.com/b2", 0),
    ]
    predictions = {
        items[0].url_hash: 0.9,
        items[1].url_hash: 0.6,
        items[2].url_hash: -0.2,
        items[3].url_hash: -0.7,
    }
    with unique_feed.db_con() as cur:
        for url_hash, score in predictions.items():
            cur.execute(
                "UPDATE feed_items SET predicted_score = %s, "
                "predicted_confidence = %s WHERE user_hash = %s "
                "AND feed_hash = %s AND item_url_hash = %s",
                (score, abs(score), unique_feed.user_hash,
                 unique_feed.name_hash, url_hash),
            )

    results = unique_feed.query_items_with_sources(sort="predicted")
    scores = [meta["predicted_score"] for _, meta in results]
    assert scores == sorted(scores, reverse=True)
    names = [meta["source_name"] for _, meta in results]
    assert names == ["source-a", "source-a", "source-b", "source-b"]


@pytest.mark.filterwarnings("ignore::UserWarning")
def test_query_items_source_filter(unique_feed, unique_item_strict):
    """source_hashes restricts results to the selected sources."""
    unique_feed.create()
    source_a = _make_source(unique_feed, "source-a")
    source_b = _make_source(unique_feed, "source-b")

    item_a = _add_item(
        unique_feed, source_a, unique_item_strict, "http://example.com/a", 2
    )
    item_b = _add_item(
        unique_feed, source_b, unique_item_strict, "http://example.com/b", 1
    )

    only_a = unique_feed.query_items_with_sources(source_hashes=[source_a.name_hash])
    assert [item.url_hash for item, _ in only_a] == [item_a.url_hash]

    only_b = unique_feed.query_items_with_sources(source_hashes=[source_b.name_hash])
    assert [item.url_hash for item, _ in only_b] == [item_b.url_hash]

    none = unique_feed.query_items_with_sources(source_hashes=[])
    assert none == []

    both = unique_feed.query_items_with_sources(
        source_hashes=[source_a.name_hash, source_b.name_hash]
    )
    assert len(both) == 2


@pytest.mark.filterwarnings("ignore::UserWarning")
def test_feed_stats(unique_feed, unique_item_strict):
    """Dashboard stats: totals, unvoted count, and posts/day."""
    from db.item_state import ItemState

    unique_feed.create()

    items = [
        _add_item(unique_feed, None, unique_item_strict, f"http://example.com/{i}", i)
        for i in range(3)
    ]
    ItemState(
        user_hash=unique_feed.user_hash,
        feed_hash=unique_feed.name_hash,
        item_url_hash=items[0].url_hash,
        score=1,
    ).create()

    stats = unique_feed.stats()
    assert stats["feed_item_count"] == 3
    assert stats["feed_unread_count"] == 2
    assert stats["feed_posts_per_day"] == 3.0  # 3 items on day one


@pytest.mark.filterwarnings("ignore::UserWarning")
def test_rename_feed_keeps_attached_data(unique_feed, unique_item_strict):
    """Renaming a feed changes its hash but carries sources, items, votes,
    and model stats along via the ON UPDATE CASCADE foreign keys."""
    from db.item_state import ItemState

    unique_feed.create()
    source = _make_source(unique_feed, "source-a")
    item = _add_item(
        unique_feed, source, unique_item_strict, "http://example.com/keep", 3
    )
    ItemState(
        user_hash=unique_feed.user_hash,
        feed_hash=unique_feed.name_hash,
        item_url_hash=item.url_hash,
        score=1,
    ).create()

    old_hash = unique_feed.name_hash
    unique_feed.rename("renamed feed")
    new_hash = unique_feed.name_hash

    assert new_hash != old_hash
    # the old hash no longer resolves; the new one does
    assert Feed.read(user_hash=unique_feed.user_hash, name_hash=old_hash) is None
    renamed = Feed.read(user_hash=unique_feed.user_hash, name_hash=new_hash)
    assert renamed is not None
    assert renamed.name == "renamed feed"

    # source, item, and vote all followed the feed to its new hash
    assert source.name_hash in renamed.source_hashes
    results = renamed.query_items_with_sources()
    assert [i.url_hash for i, _ in results] == [item.url_hash]
    assert results[0][1]["source_name"] == "source-a"
    assert results[0][1]["user_score"] == 1


def test_source_color_assigned_and_editable(unique_feed):
    """Sources get a palette color at creation; updates can change it."""
    from db.source import SOURCE_COLORS, Source

    unique_feed.create()
    source = Source(
        user_hash=unique_feed.user_hash,
        feed_hash=unique_feed.name_hash,
        name="colorful",
        url="http://example.com",
    )
    unique_feed.add_source(source)
    stored = Source.read(
        user_hash=unique_feed.user_hash,
        feed_hash=unique_feed.name_hash,
        source_hash=source.name_hash,
    )
    assert stored.color in SOURCE_COLORS

    stored.update(name=stored.name, url=str(stored.url), color="#123abc")
    reread = Source.read(
        user_hash=unique_feed.user_hash,
        feed_hash=unique_feed.name_hash,
        source_hash=stored.name_hash,
    )
    assert reread.color == "#123abc"
