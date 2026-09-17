"""Mirror items from a feed into every feed that subscribes to it.

A *feed source* is a source row whose ``source_feed_hash`` points at another of
the user's feeds. When an item lands in the referenced ("origin") feed it must
also appear in every feed that lists the origin as a source, exactly as if that
subscriber had ingested it directly. ``propagate_items`` performs that fan-out,
following chains of feed sources and guarding against cycles.

Mirroring writes both the subscriber's ``source_items`` row (so the item shows
up under the feed-source badge and can be filtered by it) and its ``feed_items``
row (so it appears in the feed and gets ranked). Existing rows are left
untouched — a mirror never resets a score a real ingest already set.
"""

from typing import Iterable, List, Optional, Set

from .base import get_db_con


def subscriber_sources(cur, user_hash: str, origin_feed_hash: str) -> List[dict]:
    """Feed-source rows (feed_hash, name_hash) that mirror ``origin_feed_hash``."""
    cur.execute(
        "SELECT feed_hash, name_hash FROM sources "
        "WHERE user_hash = %s AND source_feed_hash = %s",
        (user_hash, origin_feed_hash),
    )
    return cur.fetchall()


def _mirror_into(
    cur, user_hash: str, feed_hash: str, source_hash: str, url_hashes: List[str]
) -> None:
    for url_hash in url_hashes:
        cur.execute(
            "INSERT INTO source_items "
            "(user_hash, feed_hash, source_hash, item_url_hash, score) "
            "VALUES (%s, %s, %s, %s, 0) ON CONFLICT DO NOTHING",
            (user_hash, feed_hash, source_hash, url_hash),
        )
        cur.execute(
            "INSERT INTO feed_items (user_hash, feed_hash, item_url_hash, score) "
            "VALUES (%s, %s, %s, 0) ON CONFLICT DO NOTHING",
            (user_hash, feed_hash, url_hash),
        )


def propagate_items(
    user_hash: str,
    origin_feed_hash: str,
    url_hashes: Iterable[str],
    _visited: Optional[Set[str]] = None,
) -> None:
    """Mirror ``url_hashes`` into every feed that sources ``origin_feed_hash``.

    Recurses through chains of feed sources (feed C sources B sources A) and
    uses ``_visited`` to stop cycles from looping forever.
    """
    url_hashes = [h for h in url_hashes if h]
    if not url_hashes:
        return

    if _visited is None:
        _visited = set()
    if origin_feed_hash in _visited:
        return
    _visited.add(origin_feed_hash)

    with get_db_con() as cur:
        subs = subscriber_sources(cur, user_hash, origin_feed_hash)
        for sub in subs:
            _mirror_into(cur, user_hash, sub["feed_hash"], sub["name_hash"], url_hashes)

    # Recurse after committing this level so downstream feeds see the rows.
    for sub in subs:
        propagate_items(user_hash, sub["feed_hash"], url_hashes, _visited)


# --- Votes across a duplicate group -----------------------------------------
#
# A vote is about the content, not about the particular copy of it the user
# happened to be shown. Votes are already shared across feeds (the
# ``user_item_votes`` view), but they are keyed on ``item_url_hash``, so the
# same article stored under two URLs is two items and a vote on one says
# nothing about the other.
#
# That matters because which member of a duplicate group is shown is decided by
# the model's prediction, and a retrain reshuffles those. Downvote a story,
# retrain, and a different member of its group wins and the story is back --
# unvoted, unread, looking like a bug. Spreading the vote across the group is
# what stops that.
#
# Groups are per account (see dedup/detect), and every query below is scoped to
# one ``user_hash`` on both sides of the join, so a vote never travels to
# another account's copy of an article and another account's vote never arrives
# on yours.
#
# A member that the user has already voted on is never touched: an explicit
# judgement on this copy outranks an inherited one. A row that exists only
# because the item was marked read keeps its ``is_read``; just the score is
# filled in.

_INHERIT_CONFLICT_SQL = (
    " ON CONFLICT (user_hash, feed_hash, item_url_hash) DO UPDATE SET"
    "  score = EXCLUDED.score, score_date = EXCLUDED.score_date"
)


def propagate_vote_to_duplicates(user_hash: str, item_url_hash: str) -> int:
    """Copy this user's vote on ``item_url_hash`` to the rest of its duplicate
    group. Returns the number of item_states rows written.

    A no-op for an item that is not in a group for this user, or has no vote
    to spread.
    """
    with get_db_con() as cur:
        cur.execute(
            "SELECT group_hash FROM item_duplicates "
            "WHERE user_hash = %s AND item_url_hash = %s "
            "AND group_hash IS NOT NULL",
            (user_hash, item_url_hash),
        )
        group = cur.fetchone()
        if not group:
            return 0

        cur.execute(
            "SELECT score, score_date FROM user_item_votes "
            "WHERE user_hash = %s AND item_url_hash = %s",
            (user_hash, item_url_hash),
        )
        vote = cur.fetchone()
        if not vote:
            return 0

        # Every feed of this user holding another member of the group. The
        # NOT EXISTS is what protects a copy the user has judged themselves.
        cur.execute(
            "INSERT INTO item_states "
            "(user_hash, feed_hash, item_url_hash, score, score_date) "
            "SELECT c.user_hash, c.feed_hash, c.item_url_hash, %s, %s "
            "FROM feed_items c "
            "JOIN item_duplicates d ON d.user_hash = c.user_hash "
            " AND d.item_url_hash = c.item_url_hash "
            "WHERE c.user_hash = %s AND d.group_hash = %s "
            "AND c.item_url_hash <> %s "
            "AND NOT EXISTS (SELECT 1 FROM user_item_votes v "
            " WHERE v.user_hash = c.user_hash "
            "  AND v.item_url_hash = c.item_url_hash)" + _INHERIT_CONFLICT_SQL,
            (
                vote["score"],
                vote["score_date"],
                user_hash,
                group["group_hash"],
                item_url_hash,
            ),
        )
        return cur.rowcount


def inherit_votes_from_duplicates(user_hash: str, url_hash: str) -> int:
    """Give a newly grouped item the votes its twins already carry.

    The other direction of ``propagate_vote_to_duplicates``: an item that
    joins a group after the user voted on the story would otherwise arrive
    unvoted and resurface it. Returns the number of item_states rows written.

    ``DISTINCT ON`` resolves twins that disagree the same way the
    ``user_item_votes`` view does -- the most recent vote wins -- and is also
    what keeps a single conflicting row from being updated twice in one
    statement.
    """
    with get_db_con() as cur:
        cur.execute(
            "INSERT INTO item_states "
            "(user_hash, feed_hash, item_url_hash, score, score_date) "
            "SELECT DISTINCT ON (c.user_hash, c.feed_hash) "
            " c.user_hash, c.feed_hash, c.item_url_hash, v.score, v.score_date "
            "FROM feed_items c "
            "JOIN item_duplicates mine ON mine.user_hash = c.user_hash "
            " AND mine.item_url_hash = c.item_url_hash "
            "JOIN item_duplicates sib ON sib.user_hash = mine.user_hash "
            " AND sib.group_hash = mine.group_hash "
            " AND sib.item_url_hash <> c.item_url_hash "
            "JOIN user_item_votes v ON v.user_hash = c.user_hash "
            " AND v.item_url_hash = sib.item_url_hash "
            "WHERE c.user_hash = %s AND c.item_url_hash = %s "
            "AND mine.group_hash IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM user_item_votes uv "
            " WHERE uv.user_hash = c.user_hash "
            "  AND uv.item_url_hash = c.item_url_hash) "
            "ORDER BY c.user_hash, c.feed_hash, v.score_date DESC NULLS LAST"
            + _INHERIT_CONFLICT_SQL,
            (user_hash, url_hash),
        )
        return cur.rowcount
