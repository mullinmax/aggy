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


def _group_of(user, url_hash):
    """This account's grouping for an item, or None when it is not in a group.

    An examined-but-unique item has a row with a NULL group_hash, which is what
    the re-sweep queues off, so "not in a group" is the NULL rather than the
    row's absence.
    """
    with get_db_con() as cur:
        cur.execute(
            "SELECT group_hash, signal, confidence FROM item_duplicates "
            "WHERE user_hash = %s AND item_url_hash = %s "
            "AND group_hash IS NOT NULL",
            (user.name_hash, url_hash),
        )
        return cur.fetchone()


def _groups(user=None):
    """Group sizes, for one account or across all of them."""
    with get_db_con() as cur:
        if user is None:
            cur.execute(
                "SELECT group_hash, COUNT(*) AS n FROM item_duplicates "
                "WHERE group_hash IS NOT NULL GROUP BY 1"
            )
        else:
            cur.execute(
                "SELECT group_hash, COUNT(*) AS n FROM item_duplicates "
                "WHERE user_hash = %s AND group_hash IS NOT NULL GROUP BY 1",
                (user.name_hash,),
            )
        return {row["group_hash"]: row["n"] for row in cur.fetchall()}


# ---------- what is a duplicate ----------


def test_tracking_parameters_alone_make_a_duplicate(existing_user, existing_feed):
    """The cheapest and commonest real duplicate: one article, two sources,
    each appending its own tracking parameters."""
    a = _add_item(existing_feed, "https://example.com/story?utm_source=feed-a")
    b = _add_item(existing_feed, "https://example.com/story?utm_source=feed-b")

    duplicate_detection_job()

    assert (
        _group_of(existing_user, a.url_hash)["group_hash"]
        == _group_of(existing_user, b.url_hash)["group_hash"]
    )
    assert _group_of(existing_user, a.url_hash)["signal"] == "canonical_url"
    # the canonical URL is the one signal that is effectively certain
    assert _group_of(existing_user, a.url_hash)["confidence"] == 1.0


def test_amp_rendition_is_the_same_article(existing_user, existing_feed):
    plain = _add_item(existing_feed, "https://example.com/news/story")
    amp = _add_item(
        existing_feed,
        "https://example-com.cdn.ampproject.org/c/s/example.com/news/story",
    )

    duplicate_detection_job()

    assert (
        _group_of(existing_user, plain.url_hash)["group_hash"]
        == _group_of(existing_user, amp.url_hash)["group_hash"]
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

    groups = {_group_of(existing_user, i.url_hash)["group_hash"] for i in items}
    assert len(groups) == 1
    assert _groups(existing_user)[groups.pop()] == 4


def test_unrelated_articles_are_not_grouped(existing_user, existing_feed):
    a = _add_item(existing_feed, "https://example.com/one")
    b = _add_item(existing_feed, "https://example.com/two")

    duplicate_detection_job()

    assert _group_of(existing_user, a.url_hash) is None
    assert _group_of(existing_user, b.url_hash) is None


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

    assert _group_of(existing_user, article.url_hash) is None
    assert _group_of(existing_user, discussion.url_hash) is None


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

    assert _group_of(existing_user, old.url_hash) is None
    assert _group_of(existing_user, new.url_hash) is None


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

    sizes = list(_groups(existing_user).values())
    assert sizes == [4]
    ungrouped = [i for i in items if _group_of(existing_user, i.url_hash) is None]
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
    first = _groups(existing_user)
    duplicate_detection_job()

    assert _groups(existing_user) == first
    with get_db_con() as cur:
        cur.execute(
            "SELECT COUNT(*) AS n FROM feed_items c "
            "LEFT JOIN item_duplicates d ON d.user_hash = c.user_hash "
            " AND d.item_url_hash = c.item_url_hash "
            "WHERE d.item_url_hash IS NULL"
        )
        assert cur.fetchone()["n"] == 0


def test_the_job_backfills_a_missing_canonical_url(existing_user, existing_feed):
    """An existing install has no canonical_url on any row. It is pure CPU over
    a URL already stored, so the detection pass fills it in rather than needing
    a migration to do it."""
    item = _add_item(existing_feed, "https://example.com/story?utm_source=a")
    with get_db_con() as cur:
        cur.execute(
            "UPDATE items SET canonical_url = NULL, canonical_url_hash = NULL "
            "WHERE url_hash = %s",
            (item.url_hash,),
        )
        cur.execute("DELETE FROM item_duplicates")

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

    assert _group_of(existing_user, odd.url_hash) is None
    assert (
        _group_of(existing_user, a.url_hash)["group_hash"]
        == _group_of(existing_user, b.url_hash)["group_hash"]
    )


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

    group = _group_of(existing_user, shown.url_hash)["group_hash"]
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


# ---------- the "only duplicates" filter ----------


def test_only_duplicates_keeps_just_the_duplicated_stories(
    existing_user, existing_feed
):
    """The filter exists to audit what the collapse is hiding, so collapsed it
    is one row per duplicated story."""
    _add_item(existing_feed, "https://example.com/story?utm_source=a", predicted=0.1)
    survivor = _add_item(
        existing_feed, "https://example.com/story?utm_source=b", predicted=0.9
    )
    _add_item(existing_feed, "https://example.com/alone", predicted=0.5)
    _add_item(existing_feed, "https://example.com/also-alone", predicted=0.4)

    duplicate_detection_job()

    rows = existing_feed.query_items_with_sources(
        sort="newest", only_duplicates=True, collapse_duplicates=True
    )
    assert [item.url_hash for item, _ in rows] == [survivor.url_hash]
    assert rows[0][1]["duplicate_count"] == 1


def test_only_duplicates_uncollapsed_shows_every_copy(existing_user, existing_feed):
    a = _add_item(existing_feed, "https://example.com/story?utm_source=a")
    b = _add_item(existing_feed, "https://example.com/story?utm_source=b")
    _add_item(existing_feed, "https://example.com/alone")

    duplicate_detection_job()

    rows = existing_feed.query_items_with_sources(
        sort="newest", only_duplicates=True, collapse_duplicates=False
    )
    assert {item.url_hash for item, _ in rows} == {a.url_hash, b.url_hash}


def test_only_duplicates_on_a_feed_with_none_is_empty(existing_user, existing_feed):
    """Empty rather than unfiltered: asking for duplicates in a feed that has
    none has an answer, and it is not "here is everything"."""
    for i in range(3):
        _add_item(existing_feed, f"https://example.com/{i}")

    duplicate_detection_job()

    assert (
        existing_feed.query_items_with_sources(sort="newest", only_duplicates=True)
        == []
    )


def test_being_a_duplicate_does_not_depend_on_the_other_filters(
    existing_user, existing_feed
):
    """Whether an article arrived twice is a fact about the feed, not about the
    filters in force. Counting the group over the filtered rows instead would
    make a source filter quietly redefine what a duplicate is -- and would
    disagree with the list /feed/item_duplicates expands the badge into."""
    s1 = _source(existing_user, existing_feed, "S1")
    s2 = _source(existing_user, existing_feed, "S2")
    a = _add_item(
        existing_feed,
        "https://example.com/story?utm_source=a",
        source=s1,
        predicted=0.1,
    )
    _add_item(
        existing_feed,
        "https://example.com/story?utm_source=b",
        source=s2,
        predicted=0.9,
    )

    duplicate_detection_job()

    # narrowed to the one source that holds the *hidden* copy: it is still a
    # duplicate, and still reports the whole group
    rows = existing_feed.query_items_with_sources(
        sort="newest",
        only_duplicates=True,
        collapse_duplicates=False,
        source_hashes=[s1.name_hash],
    )
    assert [item.url_hash for item, _ in rows] == [a.url_hash]
    assert rows[0][1]["duplicate_count"] == 1


def test_feed_items_only_duplicates_over_the_api(
    client, existing_user, existing_feed, token
):
    _add_item(existing_feed, "https://example.com/story?utm_source=a", predicted=0.1)
    _add_item(existing_feed, "https://example.com/story?utm_source=b", predicted=0.9)
    _add_item(existing_feed, "https://example.com/alone", predicted=0.5)

    duplicate_detection_job()

    def items(**params):
        args = build_api_request_args(
            path="/feed/items",
            params={
                "feed_name_hash": existing_feed.name_hash,
                "sort": "newest",
                **params,
            },
            token=token,
        )
        response = client.get(**args)
        assert response.status_code == 200
        return response.json()

    # the default is unchanged: every story, duplicates collapsed
    assert len(items()) == 2
    assert len(items(only_duplicates="true")) == 1
    assert len(items(only_duplicates="true", collapse_duplicates="false")) == 2
    assert items(only_duplicates="true")[0]["item_duplicate_count"] == 1


# ---------- the account boundary ----------


def _second_account(name="somebody-else"):
    """Another account with a feed of its own."""
    from db.feed import Feed
    from db.user import User

    other = User(name=name)
    other.set_password("password")
    other.create()
    feed = Feed(user_hash=other.name_hash, name=f"Feed {name}")
    feed.create()
    return other, feed


def test_the_same_article_in_two_accounts_is_not_a_duplicate(
    existing_user, existing_feed
):
    """Matching never crosses accounts. Two people collecting the same story
    each hold one copy of it, and one copy is not a duplicate of anything."""
    mine = _add_item(existing_feed, "https://example.com/story?utm_source=mine")
    _, their_feed = _second_account()
    theirs = _add_item(their_feed, "https://example.com/story?utm_source=theirs")

    duplicate_detection_job()

    assert _group_of(existing_user, mine.url_hash) is None
    assert _groups() == {}  # not for anyone, not just not for me
    # and the item that is only in the other account's feed is not in mine
    rows = existing_feed.query_items_with_sources(collapse_duplicates=False)
    assert [item.url_hash for item, _ in rows] == [mine.url_hash]
    assert theirs.url_hash != mine.url_hash


def test_another_account_cannot_fill_my_group(
    existing_user, existing_feed, monkeypatch
):
    """The concrete cost of a shared group: DUPLICATE_MAX_GROUP counting
    strangers' copies would let a widely-held article push my own copies out of
    their group, so another account's data would change my feed."""
    monkeypatch.setattr(
        config, "get_int", _with_override(config, "DUPLICATE_MAX_GROUP", 2)
    )

    # six other accounts holding the same story
    for i in range(6):
        _, feed = _second_account(f"stranger-{i}")
        _add_item(feed, f"https://example.com/story?utm_source=s{i}")
    # and my own two copies
    mine = [
        _add_item(existing_feed, f"https://example.com/story?utm_source=mine-{i}")
        for i in range(2)
    ]

    duplicate_detection_job()

    groups = _groups(existing_user)
    assert list(groups.values()) == [2]
    assert all(_group_of(existing_user, i.url_hash) for i in mine)


def test_votes_never_travel_between_accounts(existing_user, existing_feed):
    """A group is per account, so there is no path for a vote to reach another
    account's copy of an article."""
    other, their_feed = _second_account()
    shared_url = "https://example.com/story?utm_source=a"
    mine = _add_item(existing_feed, shared_url)
    mine_too = _add_item(existing_feed, "https://example.com/story?utm_source=b")
    theirs = _add_item(their_feed, "https://example.com/story?utm_source=theirs")

    duplicate_detection_job()
    ItemState.set_state(
        user_hash=existing_user.name_hash,
        feed_hash=existing_feed.name_hash,
        item_url_hash=mine.url_hash,
        score=-1.0,
        is_read=True,
    )

    with get_db_con() as cur:
        # my own twin inherited it
        cur.execute(
            "SELECT score FROM user_item_votes "
            "WHERE user_hash = %s AND item_url_hash = %s",
            (existing_user.name_hash, mine_too.url_hash),
        )
        assert cur.fetchone()["score"] == -1.0
        # the other account has no vote on anything
        cur.execute(
            "SELECT COUNT(*) AS n FROM item_states WHERE user_hash = %s",
            (other.name_hash,),
        )
        assert cur.fetchone()["n"] == 0
    assert theirs.url_hash not in (mine.url_hash, mine_too.url_hash)


# ---------- re-examining articles already seen ----------


def _age_checks(days=30):
    """Push every "examined and unique" check into the past, so the re-sweep
    considers those items due."""
    with get_db_con() as cur:
        cur.execute(
            "UPDATE item_duplicates SET checked_at = NOW() - make_interval(days => %s) "
            "WHERE group_hash IS NULL",
            (days,),
        )


def test_an_already_examined_article_is_grouped_when_its_twin_arrives(
    existing_user, existing_feed
):
    """Detection is not ingestion-only. The copy that arrives first is examined
    and found unique; when the second copy turns up, the first must be pulled
    into the group with it rather than left behind."""
    first = _add_item(existing_feed, "https://example.com/story?utm_source=a")
    duplicate_detection_job()
    assert _group_of(existing_user, first.url_hash) is None

    late = _add_item(existing_feed, "https://example.com/story?utm_source=b")
    duplicate_detection_job()

    assert (
        _group_of(existing_user, first.url_hash)["group_hash"]
        == _group_of(existing_user, late.url_hash)["group_hash"]
    )


def test_the_re_sweep_recovers_items_a_full_group_turned_away(
    existing_user, existing_feed, monkeypatch
):
    """An item left ungrouped is not left ungrouped forever. The cap is the
    reproducible case: raise it, and the copies it turned away are grouped on
    the next sweep rather than staying out permanently."""
    monkeypatch.setattr(
        config, "get_int", _with_override(config, "DUPLICATE_MAX_GROUP", 2)
    )
    items = [
        _add_item(existing_feed, f"https://example.com/story?utm_source=s{i}")
        for i in range(4)
    ]
    duplicate_detection_job()
    assert list(_groups(existing_user).values()) == [2]
    monkeypatch.undo()

    # a sweep only revisits checks older than DUPLICATE_RECHECK_DAYS, so a
    # re-run straight away is deliberately a no-op
    duplicate_detection_job()
    assert list(_groups(existing_user).values()) == [2]

    _age_checks()
    duplicate_detection_job()

    assert list(_groups(existing_user).values()) == [4]
    assert all(_group_of(existing_user, i.url_hash) for i in items)


def test_the_re_sweep_leaves_grouped_items_alone(existing_user, existing_feed):
    """Only the unique ones are queued. A grouped item is never revisited, so a
    group cannot drift as its neighbours are re-examined."""
    a = _add_item(existing_feed, "https://example.com/story?utm_source=a")
    _add_item(existing_feed, "https://example.com/story?utm_source=b")
    _add_item(existing_feed, "https://example.com/alone")
    duplicate_detection_job()
    before = _group_of(existing_user, a.url_hash)["group_hash"]

    _age_checks()
    duplicate_detection_job()

    assert _group_of(existing_user, a.url_hash)["group_hash"] == before


def test_new_articles_are_examined_before_the_re_sweep(
    existing_user, existing_feed, monkeypatch
):
    """A busy install must spend its budget on articles it has never seen. The
    sweep only runs with what is left of the batch once the backlog is clear."""
    _add_item(existing_feed, "https://example.com/old-unique")
    duplicate_detection_job()
    _age_checks()

    # a batch of one, and one never-examined article waiting
    monkeypatch.setattr(
        config,
        "get_int",
        _with_override(config, "DUPLICATE_DETECTION_BATCH_SIZE", 1),
    )
    fresh = _add_item(existing_feed, "https://example.com/brand-new")
    duplicate_detection_job()

    # the new article was examined; the aged one waited its turn
    with get_db_con() as cur:
        cur.execute(
            "SELECT 1 FROM item_duplicates WHERE user_hash = %s AND item_url_hash = %s",
            (existing_user.name_hash, fresh.url_hash),
        )
        assert cur.fetchone() is not None
