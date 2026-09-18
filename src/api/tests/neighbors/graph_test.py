"""Database-backed tests for the nearest-neighbour graph.

The walk itself is covered in ``search_test.py`` against hand-built graphs, and
the graph view's layout in ``tests/js/graph_layout_test.js``. What is left for
here is everything the database adds: that a walk placed into a real feed finds
the right articles, that the back-insert keeps the graph navigable in both
directions, that the queue drains, that neither feeds nor accounts leak into
each other, and that the view's query answers with a true subgraph.
"""

import json
import math
from datetime import datetime, timezone

import pytest

from config import config
from db.base import get_db_con
from db.feed import Feed
from db.item import ItemLoose
from db.item_state import ItemState
from db.source import Source
from db.user import User
from neighbors import graph as graph_module
from neighbors.graph import link_item, neighbor_graph_job, neighbor_similarities
from tests.testing_utils import build_api_request_args

LINKS = config.get_int("NEIGHBOR_LINKS")


def _vector(angle: float) -> list:
    """A unit vector on the circle. Two articles are as alike as their angles
    are close, which makes a test's intent readable at a glance."""
    return [math.cos(angle), math.sin(angle)]


def _add_item(feed, url, angle=None, title="Title", published=None, predicted=None):
    """An article in a feed, optionally with a text embedding.

    ``angle=None`` is an article whose embedding never arrived -- the normal
    state between ingest and the embedding pass, and a case the graph has to
    survive rather than trip over.
    """
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
    if angle is not None:
        with get_db_con() as cur:
            cur.execute(
                "UPDATE items SET embeddings = %s WHERE url_hash = %s",
                (json.dumps({"test-model": _vector(angle)}), item.url_hash),
            )
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


def _neighbors(feed, item):
    """An article's own link list, best first."""
    with get_db_con() as cur:
        cur.execute(
            "SELECT neighbor_url_hash, similarity FROM item_neighbors "
            "WHERE user_hash = %s AND feed_hash = %s AND item_url_hash = %s "
            "ORDER BY similarity DESC",
            (feed.user_hash, feed.name_hash, item.url_hash),
        )
        return [(row["neighbor_url_hash"], row["similarity"]) for row in cur.fetchall()]


def _node_state(feed, item):
    with get_db_con() as cur:
        cur.execute(
            "SELECT neighbors_linked_at, neighbors_stale, neighbors_model "
            "FROM feed_items "
            "WHERE user_hash = %s AND feed_hash = %s AND item_url_hash = %s",
            (feed.user_hash, feed.name_hash, item.url_hash),
        )
        return cur.fetchone()


def _with_override(cfg, key, value):
    """config.get_int with one key forced, leaving every other key alone."""
    real = cfg.get_int

    def get_int(name, *args, **kwargs):
        if name == key:
            return value
        return real(name, *args, **kwargs)

    return get_int


def _with_float_override(cfg, key, value):
    """config.get_float with one key forced, leaving every other key alone."""
    real = cfg.get_float

    def get_float(name, *args, **kwargs):
        if name == key:
            return value
        return real(name, *args, **kwargs)

    return get_float


# ---------- placing an article ----------


def test_an_article_is_linked_to_the_ones_most_like_it(existing_feed):
    """Three articles on one subject and three on another: each should come to
    rest among its own."""
    cluster_a = [
        _add_item(existing_feed, f"https://example.com/a{i}", angle=0.02 * i)
        for i in range(3)
    ]
    cluster_b = [
        _add_item(existing_feed, f"https://example.com/b{i}", angle=3.0 + 0.02 * i)
        for i in range(3)
    ]

    neighbor_graph_job()

    a_hashes = {i.url_hash for i in cluster_a}
    nearest = _neighbors(existing_feed, cluster_a[0])[0][0]
    assert nearest in a_hashes - {cluster_a[0].url_hash}
    b_hashes = {i.url_hash for i in cluster_b}
    assert _neighbors(existing_feed, cluster_b[0])[0][0] in b_hashes


def test_the_similarity_recorded_is_the_measured_one(existing_feed):
    """Confidence in a duplicate row and "% alike" in the reader are both this
    number, so it has to be the real cosine rather than a rank."""
    _add_item(existing_feed, "https://example.com/a", angle=0.0)
    b = _add_item(existing_feed, "https://example.com/b", angle=1.0)

    neighbor_graph_job()

    _neighbor_hash, similarity = _neighbors(existing_feed, b)[0]
    assert similarity == pytest.approx(math.cos(1.0), abs=1e-9)


def test_a_new_article_is_written_into_its_neighbours_lists(existing_feed):
    """The back-insert. Cosine is symmetric, so the similarity the walk
    measured is exact in both directions -- writing it straight back is what
    saves re-walking every neighbour on every ingest."""
    a = _add_item(existing_feed, "https://example.com/a", angle=0.0)
    neighbor_graph_job()
    assert _neighbors(existing_feed, a) == []

    b = _add_item(existing_feed, "https://example.com/b", angle=0.05)
    neighbor_graph_job()

    assert [h for h, _s in _neighbors(existing_feed, b)] == [a.url_hash]
    # a never walked again, and still knows about b
    assert [h for h, _s in _neighbors(existing_feed, a)] == [b.url_hash]


def test_a_displaced_neighbour_is_marked_for_a_re_walk(existing_feed):
    """A new arrival can change a neighbour's neighbourhood by more than the
    one link we wrote back, so the neighbour is queued to be walked again."""
    a = _add_item(existing_feed, "https://example.com/a", angle=0.0)
    neighbor_graph_job()
    assert _node_state(existing_feed, a)["neighbors_stale"] is False

    _add_item(existing_feed, "https://example.com/b", angle=0.05)
    neighbor_graph_job()

    assert _node_state(existing_feed, a)["neighbors_stale"] is True


def test_a_node_keeps_only_its_best_links(existing_feed, monkeypatch):
    """Each node's list is trimmed to NEIGHBOR_LINKS, including after a
    back-insert -- an unbounded list is how one popular article ends up holding
    an edge to everything in the feed."""
    monkeypatch.setattr(config, "get_int", _with_override(config, "NEIGHBOR_LINKS", 2))
    for i in range(8):
        _add_item(existing_feed, f"https://example.com/{i}", angle=0.02 * i)
        neighbor_graph_job()

    with get_db_con() as cur:
        cur.execute(
            "SELECT item_url_hash, COUNT(*) AS n FROM item_neighbors "
            "WHERE user_hash = %s AND feed_hash = %s GROUP BY 1",
            (existing_feed.user_hash, existing_feed.name_hash),
        )
        counts = [row["n"] for row in cur.fetchall()]
    assert counts and max(counts) <= 2


def _clear_cooldown(feed):
    """Age every link so the next pass is willing to re-walk it.

    The cooldown is a rate limit, not part of what these tests are about: they
    ask where the queue ends up, not how many days it takes to get there.
    """
    with get_db_con() as cur:
        cur.execute(
            "UPDATE feed_items SET neighbors_linked_at = "
            "neighbors_linked_at - make_interval(days => 365) "
            "WHERE user_hash = %s AND feed_hash = %s",
            (feed.user_hash, feed.name_hash),
        )


def _still_queued(feed):
    """Articles still asking to be walked again."""
    with get_db_con() as cur:
        cur.execute(
            "SELECT item_url_hash FROM feed_items "
            "WHERE user_hash = %s AND feed_hash = %s AND neighbors_stale",
            (feed.user_hash, feed.name_hash),
        )
        return [row["item_url_hash"] for row in cur.fetchall()]


def _settle(feed, passes=6):
    """Run the pass until the graph stops moving."""
    for _ in range(passes):
        _clear_cooldown(feed)
        neighbor_graph_job()


def _freshen_cooldown(feed):
    """Put every article back inside its cooldown, as one just walked would be.

    The opposite of ``_clear_cooldown``, and needed after ``_settle`` because
    settling ages every link by a year to force the re-walks. A pass runs until
    its queue is empty, so an article woken while that ageing is still in place
    would be re-walked by the same pass that woke it -- which is right in
    production, where it is a day or two away from being due, and useless in a
    test that wants to see what the waking did.
    """
    with get_db_con() as cur:
        cur.execute(
            "UPDATE feed_items SET neighbors_linked_at = NOW() "
            "WHERE user_hash = %s AND feed_hash = %s "
            "AND neighbors_linked_at IS NOT NULL",
            (feed.user_hash, feed.name_hash),
        )


def test_every_article_ends_up_with_a_full_list(existing_feed):
    """The promise the queue makes. An article placed into a thin graph comes
    up short -- the first one in a feed has nothing to link to at all -- so it
    stays queued until it holds a full list rather than being left with two
    links forever."""
    items = [
        _add_item(existing_feed, f"https://example.com/{i}", angle=0.05 * i)
        for i in range(LINKS + 3)
    ]

    _settle(existing_feed)

    for item in items:
        assert len(_neighbors(existing_feed, item)) == LINKS


def test_a_feed_too_small_to_fill_a_list_stops_asking(existing_feed):
    """The other half of that rule. A feed of three articles can never give
    anything in it five neighbours, and a node that kept asking would be
    re-walked forever for an answer that is not coming."""
    items = [
        _add_item(existing_feed, f"https://example.com/{i}", angle=0.05 * i)
        for i in range(3)
    ]

    _settle(existing_feed)

    for item in items:
        assert len(_neighbors(existing_feed, item)) == len(items) - 1
    assert _still_queued(existing_feed) == []


def test_a_graph_at_rest_stops_walking_itself(existing_feed):
    """A re-walk writes the same edges back, so marking every neighbour stale
    would have each re-walk dirty five more nodes, each dirtying five more. The
    queue has to reach a fixed point, or a feed nobody has touched re-walks
    most of itself every cooldown for no change at all."""
    for i in range(LINKS + 4):
        _add_item(existing_feed, f"https://example.com/{i}", angle=0.05 * i)

    _settle(existing_feed)

    assert _still_queued(existing_feed) == []


def test_a_new_arrival_still_wakes_the_neighbours_it_changed(existing_feed):
    """...without the fixed point becoming a graph that ignores new articles.
    A node whose list this arrival genuinely changed is queued; one it did not
    reach is left alone."""
    for i in range(LINKS + 4):
        _add_item(existing_feed, f"https://example.com/{i}", angle=0.05 * i)
    _settle(existing_feed)
    assert _still_queued(existing_feed) == []
    # as they would be in a settled feed: recently walked, so a wake means
    # "due in a day or two" rather than "due right now"
    _freshen_cooldown(existing_feed)

    arrival = _add_item(existing_feed, "https://example.com/new", angle=0.0)
    neighbor_graph_job()

    woken = set(_still_queued(existing_feed))
    assert woken  # the ones it displaced a link of
    assert arrival.url_hash not in woken  # it was placed, not displaced
    assert len(woken) <= LINKS


def test_an_article_with_no_embedding_stays_on_the_queue(existing_feed):
    """Embedding can fail at ingest and be filled in later. A node dropped from
    the queue for good would never be placed when it is."""
    item = _add_item(existing_feed, "https://example.com/unembedded", angle=None)

    neighbor_graph_job()

    state = _node_state(existing_feed, item)
    assert state["neighbors_linked_at"] is not None  # the cooldown has started
    assert state["neighbors_stale"] is True  # ...but it has not been placed
    assert _neighbors(existing_feed, item) == []


def test_an_article_is_never_its_own_neighbour(existing_feed):
    a = _add_item(existing_feed, "https://example.com/a", angle=0.0)
    _add_item(existing_feed, "https://example.com/b", angle=0.05)

    neighbor_graph_job()

    assert a.url_hash not in [h for h, _s in _neighbors(existing_feed, a)]


def test_the_model_that_measured_the_links_is_recorded(existing_feed):
    """Cosine distances from two different embedding models are not comparable,
    so which model produced them has to be answerable."""
    a = _add_item(existing_feed, "https://example.com/a", angle=0.0)
    _add_item(existing_feed, "https://example.com/b", angle=0.05)

    neighbor_graph_job()

    assert _node_state(existing_feed, a)["neighbors_model"] == "test-model"


# ---------- the job ----------


def test_the_job_drains_its_queue_and_then_has_nothing_to_do(existing_feed):
    """Progress is kept on the rows, so a second pass finds nothing -- which is
    what makes the job safe to run on an interval and by hand."""
    for i in range(4):
        _add_item(existing_feed, f"https://example.com/{i}", angle=0.1 * i)

    neighbor_graph_job()
    before = _all_edges(existing_feed)
    neighbor_graph_job()

    assert _all_edges(existing_feed) == before


def _all_edges(feed):
    with get_db_con() as cur:
        cur.execute(
            "SELECT item_url_hash, neighbor_url_hash, similarity FROM item_neighbors "
            "WHERE user_hash = %s AND feed_hash = %s "
            "ORDER BY item_url_hash, neighbor_url_hash",
            (feed.user_hash, feed.name_hash),
        )
        return cur.fetchall()


def _linked_count(feed):
    with get_db_con() as cur:
        cur.execute(
            "SELECT COUNT(*) AS n FROM feed_items "
            "WHERE user_hash = %s AND feed_hash = %s "
            "AND neighbors_linked_at IS NOT NULL",
            (feed.user_hash, feed.name_hash),
        )
        return cur.fetchone()["n"]


def test_a_pass_keeps_going_until_its_queue_is_empty(existing_feed, monkeypatch):
    """The batch size is how much of the queue to read at a time, not how much
    to do. An install catching up should catch up, rather than placing a fixed
    few and then sitting idle until the next interval."""
    monkeypatch.setattr(
        config, "get_int", _with_override(config, "NEIGHBOR_GRAPH_BATCH_SIZE", 2)
    )
    for i in range(7):
        _add_item(existing_feed, f"https://example.com/{i}", angle=0.5 * i)

    neighbor_graph_job()

    assert _linked_count(existing_feed) == 7


def test_a_pass_stops_when_its_time_is_up(existing_feed, monkeypatch):
    """...but not past its deadline, so two passes never overlap. Progress is
    kept on the rows, so stopping early loses nothing -- the next pass picks up
    where this one stopped."""
    for i in range(6):
        _add_item(existing_feed, f"https://example.com/{i}", angle=0.5 * i)
    monkeypatch.setattr(
        config,
        "get_float",
        _with_float_override(config, "NEIGHBOR_GRAPH_TIME_BUDGET_SECONDS", 0.0),
    )

    neighbor_graph_job()
    assert _linked_count(existing_feed) == 0

    # and with its time back, the next pass does the lot
    monkeypatch.undo()
    neighbor_graph_job()
    assert _linked_count(existing_feed) == 6


def test_one_broken_article_does_not_eat_the_whole_pass(existing_feed, monkeypatch):
    """An article leaves the queue by having its timestamp moved, and that is
    the work's own doing -- so an article whose work throws is still due, and
    the next chunk hands it straight back. Bounded by a batch that cost one
    retry; bounded by a deadline it would cost the entire pass."""
    items = [
        _add_item(existing_feed, f"https://example.com/{i}", angle=0.5 * i)
        for i in range(4)
    ]
    boom = items[1]
    real_link = graph_module.link_item
    attempts = []

    def exploding(cur, user_hash, feed_hash, url_hash):
        attempts.append(url_hash)
        if url_hash == boom.url_hash:
            raise RuntimeError("this article cannot be placed")
        return real_link(cur, user_hash, feed_hash, url_hash)

    monkeypatch.setattr(graph_module, "link_item", exploding)

    neighbor_graph_job()

    assert attempts.count(boom.url_hash) == 1  # tried once, not until the clock ran out
    assert _linked_count(existing_feed) == 3  # and the rest were still placed


def test_a_pass_with_nothing_to_do_leaves_no_trace(existing_feed):
    """One of these every few minutes, forever, would bury the passes that did
    work."""
    _add_item(existing_feed, "https://example.com/a", angle=0.0)
    neighbor_graph_job()

    with get_db_con() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM task_runs WHERE kind = 'neighbor_graph'")
        before = cur.fetchone()["n"]
    neighbor_graph_job()
    with get_db_con() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM task_runs WHERE kind = 'neighbor_graph'")
        assert cur.fetchone()["n"] == before


def test_an_article_leaving_a_feed_takes_its_edges_with_it(existing_feed):
    """A dangling edge would send a walk to a node the feed no longer holds."""
    a = _add_item(existing_feed, "https://example.com/a", angle=0.0)
    b = _add_item(existing_feed, "https://example.com/b", angle=0.05)
    neighbor_graph_job()
    assert _neighbors(existing_feed, b)

    with get_db_con() as cur:
        cur.execute(
            "DELETE FROM feed_items WHERE user_hash = %s AND feed_hash = %s "
            "AND item_url_hash = %s",
            (existing_feed.user_hash, existing_feed.name_hash, a.url_hash),
        )

    # the edge pointing at it is gone in both directions
    assert _neighbors(existing_feed, b) == []


# ---------- what the graph must not cross ----------


def test_feeds_do_not_share_a_graph(existing_user, existing_feed):
    """The reader's question is what else *in this feed* is like this, so the
    answer cannot come from another one."""
    other = Feed(user_hash=existing_user.name_hash, name="Other feed")
    other.create()
    here = _add_item(existing_feed, "https://example.com/here", angle=0.0)
    _add_item(other, "https://example.com/there", angle=0.001)

    neighbor_graph_job()

    assert _neighbors(existing_feed, here) == []


def _second_account(name="somebody-else"):
    """Another account with a feed of its own."""
    other = User(name=name)
    other.set_password("password")
    other.create()
    feed = Feed(user_hash=other.name_hash, name=f"Feed {name}")
    feed.create()
    return other, feed


def test_accounts_do_not_share_a_graph(existing_user, existing_feed):
    """The same boundary item_duplicates draws: this compares article content,
    and that comparison must not cross accounts."""
    _stranger, their_feed = _second_account()
    mine = _add_item(existing_feed, "https://example.com/story", angle=0.0)
    _add_item(their_feed, "https://example.com/story-too", angle=0.001)

    neighbor_graph_job()

    assert _neighbors(existing_feed, mine) == []
    with get_db_con() as cur:
        assert neighbor_similarities(cur, existing_user.name_hash, mine.url_hash) == []


def test_neighbor_similarities_spans_an_accounts_feeds(existing_user, existing_feed):
    """Duplicate groups are per account rather than per feed, so the signal
    they read has to see every feed the account holds the article in."""
    other = Feed(user_hash=existing_user.name_hash, name="Other feed")
    other.create()
    a = _add_item(existing_feed, "https://example.com/a", angle=0.0)
    b = _add_item(existing_feed, "https://example.com/b", angle=0.05)
    # the same two stories, collected into a second feed as well
    c = _add_item(other, "https://example.com/c", angle=0.0)
    _add_item(other, "https://example.com/d", angle=0.05)

    neighbor_graph_job()

    with get_db_con() as cur:
        assert b.url_hash in dict(
            neighbor_similarities(cur, existing_user.name_hash, a.url_hash)
        )
        assert a.url_hash not in dict(
            neighbor_similarities(cur, existing_user.name_hash, c.url_hash)
        )


def test_link_item_places_one_article_on_its_own(existing_feed):
    """The unit the pass is built out of: given a cursor, it places one article
    in one feed and answers with what it found."""
    a = _add_item(existing_feed, "https://example.com/a", angle=0.0)
    neighbor_graph_job()
    b = _add_item(existing_feed, "https://example.com/b", angle=0.05)

    with get_db_con() as cur:
        found = link_item(
            cur, existing_feed.user_hash, existing_feed.name_hash, b.url_hash
        )

    assert [h for h, _s in found] == [a.url_hash]


# ---------- the graph view ----------
#
# What the drawing is made of. The layout itself is arithmetic and is checked
# without a browser in tests/js/graph_layout_test.js; what is left for here is
# the query behind it.
#
# The angles are deliberately wide apart. Articles closer than
# DUPLICATE_SIMILARITY_THRESHOLD are the same story, and the view collapses
# those exactly as the article list does -- which is its own test, below, and
# would otherwise quietly turn every one of these into a single node.


def test_the_view_returns_the_articles_and_the_links_between_them(existing_feed):
    items = [
        _add_item(existing_feed, f"https://example.com/{i}", angle=0.5 * i)
        for i in range(4)
    ]
    _settle(existing_feed)

    nodes, edges = existing_feed.graph()

    assert {node["url_hash"] for node in nodes} == {item.url_hash for item in items}
    assert edges
    for edge in edges:
        assert edge["source"] < edge["target"]
        assert 0 < edge["similarity"] <= 1


def test_the_two_stored_directions_are_drawn_as_one_line(existing_feed):
    """The graph holds each link both ways round so a walk stays connected.
    Two lines on top of each other is just a thicker line, so the view folds
    them."""
    a = _add_item(existing_feed, "https://example.com/a", angle=0.0)
    b = _add_item(existing_feed, "https://example.com/b", angle=0.5)
    _settle(existing_feed)

    # both directions really are stored
    assert _neighbors(existing_feed, a) and _neighbors(existing_feed, b)

    _nodes, edges = existing_feed.graph()

    assert len(edges) == 1


def test_an_edge_with_one_end_outside_the_window_is_not_drawn(existing_feed):
    """A window has to be a true subgraph. An edge to an article that was left
    out would be a line running off the side of the canvas to nothing."""
    for i in range(6):
        _add_item(
            existing_feed,
            f"https://example.com/{i}",
            angle=0.5 * i,
            published=datetime(2024, 1, i + 1, tzinfo=timezone.utc),
        )
    _settle(existing_feed)

    nodes, edges = existing_feed.graph(limit=3)
    drawn = {node["url_hash"] for node in nodes}

    assert len(nodes) == 3
    for edge in edges:
        assert edge["source"] in drawn
        assert edge["target"] in drawn


def test_no_limit_draws_the_whole_feed(existing_feed):
    """A window is the default because a picture of ten thousand articles is a
    hairball, not because the whole thing is off limits."""
    for i in range(12):
        _add_item(existing_feed, f"https://example.com/{i}", angle=0.5 * i)

    nodes, _edges = existing_feed.graph(limit=None)

    assert len(nodes) == 12


def test_the_window_keeps_the_end_of_the_feed_it_was_asked_for(existing_feed):
    best = _add_item(
        existing_feed, "https://example.com/best", angle=0.0, predicted=0.9
    )
    _add_item(existing_feed, "https://example.com/worst", angle=1.0, predicted=-0.9)
    _add_item(existing_feed, "https://example.com/middling", angle=2.0, predicted=0.0)

    nodes, _edges = existing_feed.graph(limit=1, sort="predicted")

    assert [node["url_hash"] for node in nodes] == [best.url_hash]


def test_an_unlinked_article_is_still_a_node(existing_feed):
    """A feed mid-backfill should look like a graph filling in, not a graph
    with holes in it."""
    lonely = _add_item(existing_feed, "https://example.com/lonely", angle=0.0)

    nodes, edges = existing_feed.graph()

    assert [node["url_hash"] for node in nodes] == [lonely.url_hash]
    assert edges == []


def test_the_view_carries_what_the_drawing_needs(existing_feed):
    """Colour comes from the source, size from the prediction, and a ring from
    a real vote -- so all three have to actually arrive."""
    source = Source(
        user_hash=existing_feed.user_hash,
        feed_hash=existing_feed.name_hash,
        name="Some source",
        url="http://some-source.example.com/rss",
    )
    source.create()
    item = _add_item(existing_feed, "https://example.com/a", angle=0.0, predicted=0.4)
    source.add_items(item)

    nodes, _edges = existing_feed.graph()

    assert nodes[0]["source_name"] == "Some source"
    assert nodes[0]["predicted_score"] == pytest.approx(0.4)
    assert nodes[0]["title"] == "Title"


# ---------- the same filters as the list ----------
#
# The graph is a picture of the feed you were just looking at, so the two have
# to agree about what is hidden. They share one implementation; these check
# that the sharing actually reaches the graph.


def test_the_graph_collapses_duplicates_like_the_list_does(existing_feed):
    _add_item(existing_feed, "https://outlet-a.com/story", angle=0.0)
    _add_item(existing_feed, "https://outlet-b.com/story", angle=0.01)
    _add_item(existing_feed, "https://example.com/unrelated", angle=2.0)
    _settle(existing_feed)

    collapsed, _edges = existing_feed.graph()
    every_copy, _edges = existing_feed.graph(collapse_duplicates=False)

    assert len(collapsed) == 2  # the story once, plus the unrelated article
    assert len(every_copy) == 3


def test_the_graph_honours_the_date_filter(existing_feed):
    _add_item(
        existing_feed,
        "https://example.com/ancient",
        angle=0.0,
        published=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )
    recent = _add_item(
        existing_feed,
        "https://example.com/today",
        angle=1.0,
        published=datetime.now(timezone.utc),
    )

    nodes, _edges = existing_feed.graph(max_age="week")

    assert [node["url_hash"] for node in nodes] == [recent.url_hash]


def test_the_graph_honours_the_source_filter(existing_feed):
    wanted = Source(
        user_hash=existing_feed.user_hash,
        feed_hash=existing_feed.name_hash,
        name="Wanted",
        url="http://wanted.example.com/rss",
    )
    wanted.create()
    mine = _add_item(existing_feed, "https://example.com/wanted", angle=0.0)
    wanted.add_items(mine)
    _add_item(existing_feed, "https://example.com/other", angle=1.0)

    nodes, _edges = existing_feed.graph(source_hashes=[wanted.name_hash])

    assert [node["url_hash"] for node in nodes] == [mine.url_hash]


def test_the_graph_can_hide_what_you_have_voted_on(existing_feed):
    voted = _add_item(existing_feed, "https://example.com/voted", angle=0.0)
    unvoted = _add_item(existing_feed, "https://example.com/unvoted", angle=1.0)
    ItemState(
        user_hash=existing_feed.user_hash,
        feed_hash=existing_feed.name_hash,
        item_url_hash=voted.url_hash,
        score=1.0,
    ).create()

    nodes, _edges = existing_feed.graph(include_read=False)

    assert [node["url_hash"] for node in nodes] == [unvoted.url_hash]


# ---------- over the API ----------


def test_the_graph_endpoint_answers_with_nodes_and_edges(
    client, existing_user, existing_feed, token
):
    _add_item(existing_feed, "https://example.com/a", angle=0.0)
    _add_item(existing_feed, "https://example.com/b", angle=0.5)
    _settle(existing_feed)

    args = build_api_request_args(
        path="/feed/graph",
        params={"feed_name_hash": existing_feed.name_hash},
        token=token,
    )
    body = client.get(**args).json()

    assert len(body["nodes"]) == 2
    assert len(body["edges"]) == 1
    assert body["total_items"] == 2
    assert body["nodes"][0]["item_hash"]
    assert body["edges"][0]["similarity"] > 0


def test_the_graph_endpoint_takes_the_filters_the_list_takes(
    client, existing_user, existing_feed, token
):
    _add_item(
        existing_feed,
        "https://example.com/ancient",
        angle=0.0,
        published=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )
    _add_item(
        existing_feed,
        "https://example.com/today",
        angle=1.0,
        published=datetime.now(timezone.utc),
    )

    args = build_api_request_args(
        path="/feed/graph",
        params={"feed_name_hash": existing_feed.name_hash, "max_age": "week"},
        token=token,
    )
    body = client.get(**args).json()

    assert len(body["nodes"]) == 1


def test_the_graph_endpoint_rejects_a_sort_it_does_not_have(
    client, existing_user, existing_feed, token
):
    args = build_api_request_args(
        path="/feed/graph",
        params={"feed_name_hash": existing_feed.name_hash, "sort": "vibes"},
        token=token,
    )
    assert client.get(**args).status_code == 422


def test_the_graph_endpoint_cannot_be_pointed_at_another_account(
    client, existing_user, existing_feed, token
):
    _stranger, their_feed = _second_account("graph-stranger")
    _add_item(their_feed, "https://example.com/theirs", angle=0.0)

    args = build_api_request_args(
        path="/feed/graph",
        params={"feed_name_hash": their_feed.name_hash},
        token=token,
    )
    assert client.get(**args).status_code == 404
