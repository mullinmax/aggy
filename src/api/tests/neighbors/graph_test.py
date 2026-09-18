"""Database-backed tests for the nearest-neighbour graph.

The walk itself is covered in ``search_test.py`` against hand-built graphs.
What is left for here is everything the database adds: that a walk placed into
a real feed finds the right articles, that the back-insert keeps the graph
navigable in both directions, that the queue drains, and that neither feeds nor
accounts leak into each other.
"""

import json
import math

import pytest

from config import config
from db.base import get_db_con
from db.feed import Feed
from db.item import ItemLoose
from db.user import User
from neighbors.graph import link_item, neighbor_graph_job, neighbor_similarities

LINKS = config.get_int("NEIGHBOR_LINKS")


def _vector(angle: float) -> list:
    """A unit vector on the circle. Two articles are as alike as their angles
    are close, which makes a test's intent readable at a glance."""
    return [math.cos(angle), math.sin(angle)]


def _add_item(feed, url, angle=None, title="Title", published=None):
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


def test_a_batch_bounds_one_pass(existing_feed, monkeypatch):
    """A large backlog is worked over several passes rather than one long
    transaction."""
    monkeypatch.setattr(
        config, "get_int", _with_override(config, "NEIGHBOR_GRAPH_BATCH_SIZE", 2)
    )
    for i in range(6):
        _add_item(existing_feed, f"https://example.com/{i}", angle=0.1 * i)

    neighbor_graph_job()

    with get_db_con() as cur:
        cur.execute(
            "SELECT COUNT(*) AS n FROM feed_items "
            "WHERE user_hash = %s AND feed_hash = %s "
            "AND neighbors_linked_at IS NOT NULL",
            (existing_feed.user_hash, existing_feed.name_hash),
        )
        assert cur.fetchone()["n"] == 2


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
