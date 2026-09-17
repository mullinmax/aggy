"""Build and read the nearest-neighbour graph described in V25.

One node per (account, feed, article); each node stores its ``NEIGHBOR_LINKS``
nearest articles in that feed. A new article is placed by walking the existing
graph (``neighbors.search.greedy_search``) rather than by scanning the feed,
and the walk's own result is the node's link list.

The back-insert is the part worth understanding. When an article lands in the
neighbourhood of five others, it is very likely closer to some of them than one
of *their* existing links is -- but re-walking those five to find out would
cost five more searches per ingested article. Instead the walk's similarities,
which are exact and already computed, are written straight back as edges in the
reverse direction, each neighbour's list is trimmed to its best
``NEIGHBOR_LINKS``, and the neighbour is marked stale so a later pass re-walks
it properly. The cheap exact update happens immediately; the expensive
approximate one happens on the background job's own schedule.

Everything here takes a cursor and does no transaction management of its own,
so a caller can place an article and act on the result atomically.
"""

import logging
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from config import config
from db.base import get_db_con
from db.task_run import KIND_NEIGHBOR_GRAPH, task_run

from .search import (
    embedding_model_name,
    greedy_search,
    parse_embedding,
    similarity,
    unit,
)


def _fetch_vectors(cur, url_hashes: Sequence[str]) -> Dict[str, np.ndarray]:
    """Unit text embeddings for a batch of articles.

    Articles with no embedding are simply absent from the result, which is what
    ``greedy_search`` reads as "cannot take part". Batched because the walk
    expands a whole node's worth of neighbours at a time and a round trip per
    neighbour is most of what a walk would otherwise cost.
    """
    url_hashes = [h for h in dict.fromkeys(url_hashes) if h]
    if not url_hashes:
        return {}
    cur.execute(
        "SELECT url_hash, embeddings FROM items WHERE url_hash = ANY(%s)",
        (list(url_hashes),),
    )
    vectors = {}
    for row in cur.fetchall():
        vector = unit(parse_embedding(row["embeddings"]))
        if vector is not None:
            vectors[row["url_hash"]] = vector
    return vectors


def item_vector(cur, url_hash: str) -> Tuple[Optional[np.ndarray], Optional[str]]:
    """One article's unit embedding and the model that produced it."""
    cur.execute("SELECT embeddings FROM items WHERE url_hash = %s", (url_hash,))
    row = cur.fetchone()
    if not row:
        return None, None
    return unit(parse_embedding(row["embeddings"])), embedding_model_name(
        row["embeddings"]
    )


def _adjacency(cur, user_hash: str, feed_hash: str, url_hash: str) -> List[str]:
    """A node's links, in both directions.

    Forward edges are the node's own nearest list. Reverse edges are the nodes
    that named *it*, and they matter as much: a node's own list ages as better
    neighbours arrive, and without the reverse direction a well-connected
    article would become unreachable from the articles that point at it.

    The reverse side is capped at ``NEIGHBOR_MAX_FANOUT``, best first. A hub --
    the one article about a topic a feed keeps returning to -- can be named by
    hundreds of others, and expanding it would fetch every one of their
    vectors, which is the scan the graph exists to avoid.
    """
    fanout = config.get_int("NEIGHBOR_MAX_FANOUT")
    cur.execute(
        "SELECT neighbor_url_hash AS other FROM item_neighbors "
        "WHERE user_hash = %s AND feed_hash = %s AND item_url_hash = %s "
        "UNION "
        "SELECT other FROM (SELECT item_url_hash AS other, similarity"
        " FROM item_neighbors"
        " WHERE user_hash = %s AND feed_hash = %s AND neighbor_url_hash = %s"
        " ORDER BY similarity DESC LIMIT %s) back_edges",
        (user_hash, feed_hash, url_hash, user_hash, feed_hash, url_hash, fanout),
    )
    return [row["other"] for row in cur.fetchall()]


def _entry_points(
    cur, user_hash: str, feed_hash: str, url_hash: str, count: int
) -> List[str]:
    """Where to start the walk.

    Two kinds, mixed deliberately. The most recently linked articles are a good
    guess for a newly ingested one -- feeds arrive in topical bursts, and the
    piece that came in an hour ago is often about the same thing. Random nodes
    are the insurance: starting only from recent articles would explore one
    corner of the graph over and over, and a walk that begins in the wrong
    corner has no way back out. A node the walk has already linked is a valid
    entry point even if it ended up with no links of its own; that is how the
    very first articles in a feed find each other.

    ``ORDER BY random()`` sorts the feed's own rows, which the (user, feed)
    primary-key prefix already narrows to -- it is not a scan of every account.
    """
    half = max(1, count // 2)
    recent_sql = (
        "SELECT item_url_hash FROM feed_items "
        "WHERE user_hash = %s AND feed_hash = %s AND item_url_hash <> %s "
        "AND neighbors_linked_at IS NOT NULL "
        "ORDER BY neighbors_linked_at DESC LIMIT %s"
    )
    cur.execute(recent_sql, (user_hash, feed_hash, url_hash, half))
    points = [row["item_url_hash"] for row in cur.fetchall()]

    cur.execute(
        "SELECT item_url_hash FROM feed_items "
        "WHERE user_hash = %s AND feed_hash = %s AND item_url_hash <> %s "
        "AND neighbors_linked_at IS NOT NULL "
        "ORDER BY random() LIMIT %s",
        (user_hash, feed_hash, url_hash, count - half),
    )
    points += [row["item_url_hash"] for row in cur.fetchall()]

    # A node being re-walked starts from where it already is: its current
    # neighbourhood is the best-known guess at its own position, and skipping
    # it would throw away everything the last walk found.
    cur.execute(
        "SELECT neighbor_url_hash FROM item_neighbors "
        "WHERE user_hash = %s AND feed_hash = %s AND item_url_hash = %s",
        (user_hash, feed_hash, url_hash),
    )
    points += [row["neighbor_url_hash"] for row in cur.fetchall()]

    # Nothing has been linked yet (a brand new feed): any article in it will
    # do, since the point of the first walk is only to find the others.
    if not points:
        cur.execute(
            "SELECT item_url_hash FROM feed_items "
            "WHERE user_hash = %s AND feed_hash = %s AND item_url_hash <> %s "
            "LIMIT %s",
            (user_hash, feed_hash, url_hash, count),
        )
        points = [row["item_url_hash"] for row in cur.fetchall()]

    return list(dict.fromkeys(points))


def nearest(
    cur,
    user_hash: str,
    feed_hash: str,
    url_hash: str,
    vector: np.ndarray,
) -> List[Tuple[str, float]]:
    """The ``NEIGHBOR_LINKS`` articles in this feed most similar to ``vector``,
    best first, found by walking rather than scanning. Pure lookup: writes
    nothing."""
    links = config.get_int("NEIGHBOR_LINKS")
    return greedy_search(
        vector,
        _entry_points(
            cur, user_hash, feed_hash, url_hash, config.get_int("NEIGHBOR_ENTRY_POINTS")
        ),
        lambda node: _adjacency(cur, user_hash, feed_hash, node),
        lambda hashes: _fetch_vectors(cur, hashes),
        k=links,
        width=config.get_int("NEIGHBOR_SEARCH_WIDTH"),
        max_hops=config.get_int("NEIGHBOR_SEARCH_MAX_HOPS"),
        exclude=(url_hash,),
    )


def _trim(cur, user_hash: str, feed_hash: str, url_hash: str, links: int) -> None:
    """Keep only a node's best ``links`` forward edges."""
    cur.execute(
        "DELETE FROM item_neighbors d WHERE d.user_hash = %s AND d.feed_hash = %s "
        "AND d.item_url_hash = %s AND d.neighbor_url_hash NOT IN ("
        " SELECT neighbor_url_hash FROM item_neighbors"
        " WHERE user_hash = %s AND feed_hash = %s AND item_url_hash = %s"
        " ORDER BY similarity DESC, neighbor_url_hash LIMIT %s)",
        (user_hash, feed_hash, url_hash, user_hash, feed_hash, url_hash, links),
    )


def _write_links(
    cur,
    user_hash: str,
    feed_hash: str,
    url_hash: str,
    neighbors: Sequence[Tuple[str, float]],
) -> None:
    """Replace a node's links, mirror them back, and dirty what they displace.

    The reverse edges carry the same measured similarity -- cosine is
    symmetric, so there is nothing approximate about writing it in both
    directions. Trimming each neighbour afterwards is what keeps a node's list
    to its best few; marking it stale is what eventually gets it re-walked, in
    case the new arrival changed its neighbourhood by more than one link.
    """
    links = config.get_int("NEIGHBOR_LINKS")
    cur.execute(
        "DELETE FROM item_neighbors WHERE user_hash = %s AND feed_hash = %s "
        "AND item_url_hash = %s",
        (user_hash, feed_hash, url_hash),
    )
    for neighbor_hash, sim in neighbors:
        cur.execute(
            "INSERT INTO item_neighbors (user_hash, feed_hash, item_url_hash, "
            "neighbor_url_hash, similarity) VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (user_hash, feed_hash, item_url_hash, neighbor_url_hash) "
            "DO UPDATE SET similarity = EXCLUDED.similarity, linked_at = NOW()",
            (user_hash, feed_hash, url_hash, neighbor_hash, sim),
        )
        cur.execute(
            "INSERT INTO item_neighbors (user_hash, feed_hash, item_url_hash, "
            "neighbor_url_hash, similarity) VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (user_hash, feed_hash, item_url_hash, neighbor_url_hash) "
            "DO UPDATE SET similarity = EXCLUDED.similarity, linked_at = NOW()",
            (user_hash, feed_hash, neighbor_hash, url_hash, sim),
        )
        _trim(cur, user_hash, feed_hash, neighbor_hash, links)

    if neighbors:
        cur.execute(
            "UPDATE feed_items SET neighbors_stale = TRUE "
            "WHERE user_hash = %s AND feed_hash = %s AND item_url_hash = ANY(%s)",
            (user_hash, feed_hash, [n for n, _ in neighbors]),
        )


def _mark_linked(
    cur, user_hash: str, feed_hash: str, url_hash: str, model: Optional[str], done: bool
) -> None:
    """Take a node off the queue (``done``), or leave it on with its cooldown
    restarted.

    An article with no embedding yet is the second case: embedding can fail at
    ingest and be filled in later, and a node dropped from the queue for good
    would never be placed when it is.
    """
    cur.execute(
        "UPDATE feed_items SET neighbors_linked_at = NOW(), neighbors_stale = %s, "
        "neighbors_model = COALESCE(%s, neighbors_model) "
        "WHERE user_hash = %s AND feed_hash = %s AND item_url_hash = %s",
        (not done, model, user_hash, feed_hash, url_hash),
    )


def link_item(
    cur, user_hash: str, feed_hash: str, url_hash: str
) -> List[Tuple[str, float]]:
    """Place one article in one feed's graph. Returns its neighbours, best
    first."""
    vector, model = item_vector(cur, url_hash)
    if vector is None:
        _mark_linked(cur, user_hash, feed_hash, url_hash, None, done=False)
        return []

    neighbors = nearest(cur, user_hash, feed_hash, url_hash, vector)
    _write_links(cur, user_hash, feed_hash, url_hash, neighbors)
    _mark_linked(cur, user_hash, feed_hash, url_hash, model, done=True)
    return neighbors


def ensure_linked(cur, user_hash: str, url_hash: str) -> None:
    """Place an article in every one of this account's feeds that holds it and
    has not linked it yet.

    Duplicate detection reaches an article on its own schedule, which can be
    before the graph job does. Rather than wait a recheck cycle for a signal
    that is a walk away, it places the article itself; the job then finds
    nothing left to do for it.
    """
    cur.execute(
        "SELECT feed_hash FROM feed_items "
        "WHERE user_hash = %s AND item_url_hash = %s AND neighbors_linked_at IS NULL",
        (user_hash, url_hash),
    )
    for row in cur.fetchall():
        link_item(cur, user_hash, row["feed_hash"], url_hash)


def neighbor_similarities(
    cur, user_hash: str, url_hash: str
) -> List[Tuple[str, float]]:
    """Everything linked to this article anywhere in this account, best first.

    Across feeds, because duplicate groups are per account rather than per
    feed: the same story in two of your feeds is still one story. An article
    linked from both sides in different feeds keeps its highest similarity,
    which is the one that actually measured the two vectors.
    """
    cur.execute(
        "SELECT other, MAX(similarity) AS similarity FROM ("
        " SELECT neighbor_url_hash AS other, similarity FROM item_neighbors"
        "  WHERE user_hash = %s AND item_url_hash = %s"
        " UNION ALL"
        " SELECT item_url_hash AS other, similarity FROM item_neighbors"
        "  WHERE user_hash = %s AND neighbor_url_hash = %s) edges "
        "GROUP BY other ORDER BY similarity DESC",
        (user_hash, url_hash, user_hash, url_hash),
    )
    return [(row["other"], float(row["similarity"])) for row in cur.fetchall()]


def similarity_between(cur, left_hash: str, right_hash: str) -> Optional[float]:
    """Cosine similarity of two articles, measured directly.

    The graph answers "what is near this?"; this answers "how near are these
    two?", which is a different question and the one a star-shaped duplicate
    group asks -- joining a group means matching its representative, and the
    representative need not be the neighbour that led us there.
    """
    vectors = _fetch_vectors(cur, [left_hash, right_hash])
    return similarity(vectors.get(left_hash), vectors.get(right_hash))


# The queue: stale nodes, never-linked ones first, then longest since the last
# walk. Every new article dirties up to NEIGHBOR_LINKS of its neighbours, so
# without the cooldown a busy feed would re-walk the same popular nodes on
# every pass and never reach its backlog.
_PENDING_SQL = """
SELECT user_hash, feed_hash, item_url_hash
FROM feed_items
WHERE neighbors_stale
  AND (neighbors_linked_at IS NULL
       OR neighbors_linked_at < NOW() - make_interval(days => %s))
ORDER BY neighbors_linked_at ASC NULLS FIRST
LIMIT %s
"""


def neighbor_graph_job() -> None:
    """Link the articles that are due, a batch at a time.

    On an existing install the first passes are the backfill: every row starts
    stale, so the graph builds itself out over however many passes the corpus
    needs. After that a pass is mostly newly ingested articles plus whichever
    neighbours they displaced.

    Each article is its own transaction, so one unusable row costs that article
    and not the batch.
    """
    batch_size = config.get_int("NEIGHBOR_GRAPH_BATCH_SIZE")
    relink_days = config.get_int("NEIGHBOR_RELINK_DAYS")

    with get_db_con() as cur:
        cur.execute(_PENDING_SQL, (relink_days, batch_size))
        rows = cur.fetchall()

    if not rows:
        return

    # Recorded only once there is something to do: a timeline of empty passes
    # every few minutes would bury the ones that did work. System-wide, with no
    # user_hash -- the queue spans every account.
    linked = 0
    edges = 0
    with task_run(KIND_NEIGHBOR_GRAPH) as run:
        for row in rows:
            try:
                with get_db_con() as cur:
                    found = link_item(
                        cur, row["user_hash"], row["feed_hash"], row["item_url_hash"]
                    )
                linked += 1
                edges += len(found)
            except Exception as e:
                logging.exception(
                    f"Linking {row['item_url_hash']} into the neighbour graph "
                    f"failed: {e}"
                )
        run.detail = f"{linked} article(s) linked, {edges} neighbour(s) found"

    logging.info(
        f"Neighbour graph: {linked} of {len(rows)} article(s) linked, "
        f"{edges} neighbour(s) found"
    )
