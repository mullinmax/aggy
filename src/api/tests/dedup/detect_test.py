"""Database-backed tests for grouping duplicates and collapsing them in a feed.

The same article reaches a feed through several sources, under a different URL
from each, so it is stored several times over and shown several times over.
These cover what gets grouped, what deliberately does not, and which member
survives the collapse.
"""

from config import config
from db.base import get_db_con
from db.item import ItemLoose
from db.item_state import ItemState
from db.source import Source
from dedup.detect import duplicate_detection_job
from tests.testing_utils import build_api_request_args


def _add_item(feed, url, source=None, title="Title", predicted=None, published=None):
    item = ItemLoose(
        url=url,
        title=title,
        author="Someone",
        domain="example.com",
        excerpt="words",
        content="<p>words</p>",
        date_published=published,
    )
    item.create()
    if source is not None:
        source.add_items(item)
    feed.add_items(item)
    if predicted is not None:
        with get_db_con() as cur:
            cur.execute(
                "UPDATE feed_items SET predicted_score = %s, "
                "predicted_confidence = 0.5, predicted_at = NOW() "
                "WHERE user_hash = %s AND feed_hash = %s AND item_url_hash = %s",
                (predicted, feed.user_hash, feed.name_hash, item.url_hash),
            )
    return item


def _source(user, feed, name):
    source = Source(
        user_hash=user.name_hash,
        feed_hash=feed.name_hash,
        name=name,
        url=f"http://{name}.example.com/rss",
    )
    source.create()
    return source


def _group_of(url_hash):
    with get_db_con() as cur:
        cur.execute(
            "SELECT group_hash, signal, confidence FROM item_duplicates "
            "WHERE item_url_hash = %s",
            (url_hash,),
        )
        return cur.fetchone()


def _groups():
    with get_db_con() as cur:
        cur.execute("SELECT group_hash, COUNT(*) AS n FROM item_duplicates GROUP BY 1")
        return {row["group_hash"]: row["n"] for row in cur.fetchall()}


# ---------- what is a duplicate ----------


def test_tracking_parameters_alone_make_a_duplicate(existing_user, existing_feed):
    """The cheapest and commonest real duplicate: one article, two sources,
    each appending its own tracking parameters."""
    a = _add_item(existing_feed, "https://example.com/story?utm_source=feed-a")
    b = _add_item(existing_feed, "https://example.com/story?utm_source=feed-b")

    duplicate_detection_job()

    assert _group_of(a.url_hash)["group_hash"] == _group_of(b.url_hash)["group_hash"]
    assert _group_of(a.url_hash)["signal"] == "canonical_url"
    # the canonical URL is the one signal that is effectively certain
    assert _group_of(a.url_hash)["confidence"] == 1.0


def test_amp_rendition_is_the_same_article(existing_user, existing_feed):
    plain = _add_item(existing_feed, "https://example.com/news/story")
    amp = _add_item(
        existing_feed,
        "https://example-com.cdn.ampproject.org/c/s/example.com/news/story",
    )

    duplicate_detection_job()

    assert (
        _group_of(plain.url_hash)["group_hash"] == _group_of(amp.url_hash)["group_hash"]
    )


def test_every_variant_lands_in_one_group(existing_user, existing_feed):
    """Four spellings of one URL is one group of four, not two groups of two.
    Pairing two ungrouped items writes both of them, so an item can already be
    grouped by the time the job reaches it -- and looking for a second group
    for it is how one set of duplicates gets split."""
    items = [
        _add_item(existing_feed, url)
        for url in (
            "https://example.com/story?utm_source=rss",
            "https://www.example.com/story/",
            "https://example.com/story?fbclid=xyz",
            "https://example.com/story#comments",
        )
    ]

    duplicate_detection_job()

    groups = {_group_of(i.url_hash)["group_hash"] for i in items}
    assert len(groups) == 1
    assert _groups()[groups.pop()] == 4


def test_unrelated_articles_are_not_grouped(existing_user, existing_feed):
    a = _add_item(existing_feed, "https://example.com/one")
    b = _add_item(existing_feed, "https://example.com/two")

    duplicate_detection_job()

    assert _group_of(a.url_hash) is None
    assert _group_of(b.url_hash) is None


def test_a_discussion_post_is_not_the_article_it_links_to(existing_user, existing_feed):
    """The deliberate stance: only an item's *own* URL is canonicalised, never
    its outbound link target. A Reddit thread about a piece is a different item
    from the piece, and collapsing them would hide whichever the model happened
    to score lower."""
    article = _add_item(existing_feed, "https://example.com/story")
    discussion = _add_item(
        existing_feed,
        "https://reddit.com/r/programming/comments/abc/a_story/",
        # the article's URL is right there in the discussion post's body
        title="A story",
    )
    with get_db_con() as cur:
        cur.execute(
            "UPDATE items SET content = %s WHERE url_hash = %s",
            ('<a href="https://example.com/story">the story</a>', discussion.url_hash),
        )

    duplicate_detection_job()

    assert _group_of(article.url_hash) is None
    assert _group_of(discussion.url_hash) is None


def test_the_same_story_republished_much_later_is_not_a_duplicate(
    existing_user, existing_feed
):
    """Bounded by DUPLICATE_WINDOW_DAYS: the same URL resurfacing months later
    is not a duplicate worth hiding, and the window is also what keeps the
    candidate set small."""
    window = config.get_int("DUPLICATE_WINDOW_DAYS")
    old = _add_item(
        existing_feed,
        "https://example.com/story?utm_source=a",
        published="2024-01-01T00:00:00Z",
    )
    new = _add_item(
        existing_feed,
        "https://example.com/story?utm_source=b",
        published="2024-06-01T00:00:00Z",
    )
    assert window < 150  # the dates above are far further apart than the window

    duplicate_detection_job()

    assert _group_of(old.url_hash) is None
    assert _group_of(new.url_hash) is None


def test_a_group_is_capped(existing_user, existing_feed, monkeypatch):
    """The backstop against a group running away. An item that would overflow
    is left ungrouped -- an uncollapsed duplicate is a far cheaper mistake than
    a wrong collapse."""
    monkeypatch.setattr(
        config, "get_int", _with_override(config, "DUPLICATE_MAX_GROUP", 4)
    )
    items = [
        _add_item(existing_feed, f"https://example.com/story?utm_source=s{i}")
        for i in range(10)
    ]

    duplicate_detection_job()

    sizes = list(_groups().values())
    assert sizes == [4]
    ungrouped = [i for i in items if _group_of(i.url_hash) is None]
    assert len(ungrouped) == 6


def _with_override(cfg, key, value):
    """config.get_int with one key forced, leaving every other key alone."""
    real = cfg.get_int

    def get_int(name, *args, **kwargs):
        if name == key:
            return value
        return real(name, *args, **kwargs)

    return get_int


# ---------- the job itself ----------


def test_the_job_is_restartable_and_idempotent(existing_user, existing_feed):
    """Progress is kept on the rows, so a second pass has nothing to do and
    must not build anything a second time."""
    _add_item(existing_feed, "https://example.com/story?utm_source=a")
    _add_item(existing_feed, "https://example.com/story?utm_source=b")

    duplicate_detection_job()
    first = _groups()
    duplicate_detection_job()

    assert _groups() == first
    with get_db_con() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM items WHERE dedup_computed_at IS NULL")
        assert cur.fetchone()["n"] == 0


def test_the_job_backfills_a_missing_canonical_url(existing_user, existing_feed):
    """An existing install has no canonical_url on any row. It is pure CPU over
    a URL already stored, so the detection pass fills it in rather than needing
    a migration to do it."""
    item = _add_item(existing_feed, "https://example.com/story?utm_source=a")
    with get_db_con() as cur:
        cur.execute(
            "UPDATE items SET canonical_url = NULL, canonical_url_hash = NULL, "
            "dedup_computed_at = NULL WHERE url_hash = %s",
            (item.url_hash,),
        )

    duplicate_detection_job()

    with get_db_con() as cur:
        cur.execute(
            "SELECT canonical_url, canonical_url_hash FROM items WHERE url_hash = %s",
            (item.url_hash,),
        )
        row = cur.fetchone()
    assert row["canonical_url"] == "https://example.com/story"
    assert row["canonical_url_hash"] is not None


def test_an_unusable_url_costs_that_item_only(existing_user, existing_feed):
    """A URL with no canonical form is ungrouped, not an error, and the rest of
    the batch still gets worked."""
    odd = _add_item(existing_feed, "https://example.com/odd")
    with get_db_con() as cur:
        cur.execute(
            "UPDATE items SET url = 'ftp://example.com/x', canonical_url = NULL, "
            "canonical_url_hash = NULL WHERE url_hash = %s",
            (odd.url_hash,),
        )
    a = _add_item(existing_feed, "https://example.com/story?utm_source=a")
    b = _add_item(existing_feed, "https://example.com/story?utm_source=b")

    duplicate_detection_job()

    assert _group_of(odd.url_hash) is None
    assert _group_of(a.url_hash)["group_hash"] == _group_of(b.url_hash)["group_hash"]


# ---------- collapsing in the feed ----------


def test_the_highest_scoring_member_survives(existing_user, existing_feed):
    """The whole point of the feature: the member shown is whichever the
    current model scores highest."""
    low = _add_item(
        existing_feed, "https://example.com/story?utm_source=a", predicted=0.1
    )
    high = _add_item(
        existing_feed, "https://example.com/story?utm_source=b", predicted=0.9
    )

    duplicate_detection_job()

    shown = existing_feed.query_items_with_sources(
        sort="newest", collapse_duplicates=True
    )
    hashes = [item.url_hash for item, _ in shown]
    assert high.url_hash in hashes
    assert low.url_hash not in hashes


def test_collapsing_reports_how_many_it_stands_for(existing_user, existing_feed):
    for i in range(3):
        _add_item(
            existing_feed,
            f"https://example.com/story?utm_source=s{i}",
            predicted=i / 10,
        )
    _add_item(existing_feed, "https://example.com/alone", predicted=0.5)

    duplicate_detection_job()

    rows = existing_feed.query_items_with_sources(
        sort="newest", collapse_duplicates=True
    )
    counts = sorted(meta["duplicate_count"] for _, meta in rows)
    # the survivor stands for the two hidden members; the lone article for none
    assert counts == [0, 2]
    # and an ungrouped item reports no group, so the UI shows it no badge
    assert [meta["duplicate_group"] for _, meta in rows].count(None) == 1


def test_not_collapsing_returns_every_member(existing_user, existing_feed):
    """ "Show me everything" has to stay possible."""
    for i in range(3):
        _add_item(existing_feed, f"https://example.com/story?utm_source=s{i}")

    duplicate_detection_job()

    collapsed = existing_feed.query_items_with_sources(
        sort="newest", collapse_duplicates=True
    )
    everything = existing_feed.query_items_with_sources(
        sort="newest", collapse_duplicates=False
    )
    assert len(collapsed) == 1
    assert len(everything) == 3


def test_an_ungrouped_feed_is_untouched_by_collapsing(existing_user, existing_feed):
    """Every ungrouped item is a group of one. Partitioning on the group alone
    would put them all in a single NULL partition and hide all but one of
    them, so this is the guard on that."""
    items = [_add_item(existing_feed, f"https://example.com/{i}") for i in range(5)]

    duplicate_detection_job()

    rows = existing_feed.query_items_with_sources(
        sort="newest", collapse_duplicates=True
    )
    assert {item.url_hash for item, _ in rows} == {i.url_hash for i in items}
    assert all(meta["duplicate_count"] == 0 for _, meta in rows)


def test_the_source_interleave_has_no_holes(existing_user, existing_feed):
    """The duplicate filter has to run *before* source_rank is computed.

    Ranking over rows that are then hidden leaves a hole: the hidden row eats
    its source's rank 1, so that source's best visible item is demoted to the
    second round-robin block and drops off the first page of the feed. The
    interleave exists precisely so every source gets a turn in the first
    block, so this asks for one block and checks both sources are in it.

    S1's copy of the shared story is its newest item and the one that loses
    the collapse; its only other item is the oldest thing in the feed, so a
    stolen rank sends it behind both of S2's.
    """
    s1 = _source(existing_user, existing_feed, "S1")
    s2 = _source(existing_user, existing_feed, "S2")

    only_s1_item = _add_item(
        existing_feed,
        "https://example.com/s1/old",
        source=s1,
        published="2024-03-01T00:00:00Z",
    )
    _add_item(
        existing_feed,
        "https://example.com/s2/second",
        source=s2,
        published="2024-03-08T00:00:00Z",
    )
    survivor = _add_item(
        existing_feed,
        "https://example.com/story?utm_source=2",
        source=s2,
        predicted=0.9,
        published="2024-03-09T00:00:00Z",
    )
    # newest in the feed, and the member the collapse hides
    _add_item(
        existing_feed,
        "https://example.com/story?utm_source=1",
        source=s1,
        predicted=0.1,
        published="2024-03-10T00:00:00Z",
    )

    duplicate_detection_job()

    first_block = existing_feed.query_items_with_sources(
        sort="newest", limit=2, collapse_duplicates=True
    )
    shown = {meta["source_name"] for _, meta in first_block}
    assert shown == {"S1", "S2"}
    # each source's best *visible* item, not whatever a stolen rank left over
    assert {item.url_hash for item, _ in first_block} == {
        only_s1_item.url_hash,
        survivor.url_hash,
    }


def test_a_group_with_no_predictions_still_collapses(existing_user, existing_feed):
    """New items the model has not scored yet fall through to the publish date.
    The next scoring pass re-resolves the group."""
    _add_item(
        existing_feed,
        "https://example.com/story?utm_source=a",
        published="2024-03-02T00:00:00Z",
    )
    older = _add_item(
        existing_feed,
        "https://example.com/story?utm_source=b",
        published="2024-03-01T00:00:00Z",
    )

    duplicate_detection_job()

    rows = existing_feed.query_items_with_sources(
        sort="newest", collapse_duplicates=True
    )
    assert len(rows) == 1
    # earliest published wins the tie, which credits the original
    assert rows[0][0].url_hash == older.url_hash


# ---------- votes across a group ----------


def test_voting_on_the_survivor_covers_its_twins(existing_user, existing_feed):
    """A vote is about the content, so it covers every copy of it. Without
    this, downvoting a story and then retraining brings it straight back as
    whichever twin the new model scores highest."""
    shown = _add_item(
        existing_feed, "https://example.com/story?utm_source=a", predicted=0.9
    )
    hidden = _add_item(
        existing_feed, "https://example.com/story?utm_source=b", predicted=0.1
    )

    duplicate_detection_job()
    ItemState.set_state(
        user_hash=existing_user.name_hash,
        feed_hash=existing_feed.name_hash,
        item_url_hash=shown.url_hash,
        score=-1.0,
        is_read=True,
    )

    with get_db_con() as cur:
        cur.execute(
            "SELECT score FROM user_item_votes "
            "WHERE user_hash = %s AND item_url_hash = %s",
            (existing_user.name_hash, hidden.url_hash),
        )
        assert cur.fetchone()["score"] == -1.0

    # so "hide read" hides the whole story, not just the copy that was voted on
    unread = existing_feed.query_items_with_sources(
        include_read=False, collapse_duplicates=False
    )
    assert unread == []


def test_an_explicit_vote_on_a_twin_is_never_overwritten(existing_user, existing_feed):
    """An inherited vote must not clobber a judgement the user made on this
    copy themselves."""
    a = _add_item(existing_feed, "https://example.com/story?utm_source=a")
    b = _add_item(existing_feed, "https://example.com/story?utm_source=b")
    duplicate_detection_job()

    for item, score in ((b, 1.0), (a, -1.0)):
        ItemState.set_state(
            user_hash=existing_user.name_hash,
            feed_hash=existing_feed.name_hash,
            item_url_hash=item.url_hash,
            score=score,
            is_read=True,
        )

    with get_db_con() as cur:
        cur.execute(
            "SELECT score FROM user_item_votes "
            "WHERE user_hash = %s AND item_url_hash = %s",
            (existing_user.name_hash, b.url_hash),
        )
        assert cur.fetchone()["score"] == 1.0  # b's own upvote, not a's downvote


def test_marking_read_does_not_spread(existing_user, existing_feed):
    """Reading something is not a judgement about the content, so only a score
    travels across the group."""
    a = _add_item(existing_feed, "https://example.com/story?utm_source=a")
    b = _add_item(existing_feed, "https://example.com/story?utm_source=b")
    duplicate_detection_job()

    ItemState.set_state(
        user_hash=existing_user.name_hash,
        feed_hash=existing_feed.name_hash,
        item_url_hash=a.url_hash,
        is_read=True,
    )

    with get_db_con() as cur:
        cur.execute(
            "SELECT is_read FROM item_states WHERE user_hash = %s "
            "AND feed_hash = %s AND item_url_hash = %s",
            (existing_user.name_hash, existing_feed.name_hash, b.url_hash),
        )
        assert cur.fetchone() is None


def test_a_twin_arriving_later_inherits_the_vote(existing_user, existing_feed):
    """The other direction: an item that joins the group *after* the vote would
    otherwise arrive unvoted and resurface the story."""
    first = _add_item(existing_feed, "https://example.com/story?utm_source=a")
    duplicate_detection_job()
    ItemState.set_state(
        user_hash=existing_user.name_hash,
        feed_hash=existing_feed.name_hash,
        item_url_hash=first.url_hash,
        score=-1.0,
        is_read=True,
    )

    late = _add_item(existing_feed, "https://example.com/story?utm_source=b")
    duplicate_detection_job()

    with get_db_con() as cur:
        cur.execute(
            "SELECT score FROM user_item_votes "
            "WHERE user_hash = %s AND item_url_hash = %s",
            (existing_user.name_hash, late.url_hash),
        )
        assert cur.fetchone()["score"] == -1.0


# ---------- the API ----------


def test_feed_items_collapses_by_default(client, existing_user, existing_feed, token):
    _add_item(existing_feed, "https://example.com/story?utm_source=a", predicted=0.1)
    _add_item(existing_feed, "https://example.com/story?utm_source=b", predicted=0.9)
    duplicate_detection_job()

    args = build_api_request_args(
        path="/feed/items",
        params={"feed_name_hash": existing_feed.name_hash, "sort": "newest"},
        token=token,
    )
    body = client.get(**args).json()

    assert len(body) == 1
    assert body[0]["item_duplicate_count"] == 1
    assert body[0]["item_duplicate_group"] is not None


def test_feed_items_can_show_every_member(client, existing_user, existing_feed, token):
    _add_item(existing_feed, "https://example.com/story?utm_source=a")
    _add_item(existing_feed, "https://example.com/story?utm_source=b")
    duplicate_detection_job()

    args = build_api_request_args(
        path="/feed/items",
        params={
            "feed_name_hash": existing_feed.name_hash,
            "sort": "newest",
            "collapse_duplicates": "false",
        },
        token=token,
    )
    assert len(client.get(**args).json()) == 2


def test_item_duplicates_lists_the_group(client, existing_user, existing_feed, token):
    s1 = _source(existing_user, existing_feed, "S1")
    s2 = _source(existing_user, existing_feed, "S2")
    _add_item(
        existing_feed,
        "https://example.com/story?utm_source=a",
        source=s1,
        predicted=0.1,
    )
    shown = _add_item(
        existing_feed,
        "https://example.com/story?utm_source=b",
        source=s2,
        predicted=0.9,
    )
    duplicate_detection_job()

    group = _group_of(shown.url_hash)["group_hash"]
    args = build_api_request_args(
        path="/feed/item_duplicates",
        params={"feed_name_hash": existing_feed.name_hash, "group_hash": group},
        token=token,
    )
    body = client.get(**args).json()

    assert body["duplicate_group"] == group
    assert len(body["members"]) == 2
    # the shown member comes first and is marked, so the UI need not work out
    # which one it already has
    assert body["members"][0]["item_hash"] == shown.url_hash
    assert body["members"][0]["item_is_shown"] is True
    assert body["members"][1]["item_is_shown"] is False
    assert body["members"][0]["item_source_name"] == "S2"
    assert body["members"][0]["item_duplicate_signal"] == "canonical_url"


def test_item_duplicates_404s_for_an_unknown_group(
    client, existing_user, existing_feed, token
):
    args = build_api_request_args(
        path="/feed/item_duplicates",
        params={
            "feed_name_hash": existing_feed.name_hash,
            "group_hash": "not-a-group",
        },
        token=token,
    )
    assert client.get(**args).status_code == 404
