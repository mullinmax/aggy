"""Find the duplicate group an item belongs to, and keep the table current.

Detection is item-level and user-independent: two items either are or are not
the same content. Which member of a group is *shown* is a per-user, per-feed
decision made at query time, because the prediction it is decided by lives on
``feed_items`` -- see ``Feed.query_items_with_sources``.

Groups are a star, not a transitive closure. Each group has one representative
and a new item joins only if it matches *that*, never merely some member.
A~B and B~C does not make A~C, and taking the closure is exactly how a
400-item mega-group happens. ``DUPLICATE_MAX_GROUP`` is a second backstop
behind that; an item that would overflow a group is simply left ungrouped,
because an uncollapsed duplicate is a much cheaper mistake than a wrong
collapse.

The representative is only the anchor that makes a group exist -- it is the
member that was stored first, and carries no other meaning. The member the
feed actually shows is whichever the current model scores highest, so it
changes as the model does.
"""

import logging
from dataclasses import dataclass
from typing import Optional

from config import config
from db.base import AggyBaseModel, get_db_con
from db.propagation import inherit_votes_from_duplicates

from .canonical import canonical_url

# The signals a group can be built from. Only the canonical URL so far: two
# items whose URLs reduce to the same string are the same article, which is as
# close to certain as duplicate detection gets.
SIGNAL_CANONICAL_URL = "canonical_url"
CANONICAL_URL_CONFIDENCE = 1.0


@dataclass
class DuplicateMatch:
    """The group an item should join, and what put it there.

    ``members`` is every item to write into the group. Joining an established
    group that is just the new item; when two so-far-ungrouped items pair up it
    is both of them, because the group does not exist until they are written.
    """

    group_hash: str
    signal: str
    confidence: float
    members: tuple = ()

    @property
    def rows(self) -> tuple:
        """Every item_duplicates row this match implies, representative first
        and without repeats."""
        return tuple(dict.fromkeys((self.group_hash,) + tuple(self.members)))


def canonical_columns(url) -> tuple:
    """``(canonical_url, canonical_url_hash)`` for an item's URL.

    Both are None for a URL with no canonical form (not http(s), unparseable,
    a redirector loop), which reads as "no canonical-URL signal for this item".
    """
    canonical = canonical_url(url)
    if canonical is None:
        return None, None
    return canonical, AggyBaseModel.__insecure_hash__(canonical)


# Only items published near each other are candidates. The same story
# republished months later is not a duplicate worth hiding, and the window is
# also what keeps the candidate set small enough to compare at all. Items with
# no publish date fall back to when they were stored, which is the same
# fallback the feed's own date filter uses.
_PUBLISHED = "COALESCE(i.date_published, i.created_at)"
_WINDOW_SQL = (
    f" AND {_PUBLISHED} >= %s::timestamptz - make_interval(days => %s)"
    f" AND {_PUBLISHED} <= %s::timestamptz + make_interval(days => %s)"
)


def _window_params(published, window_days) -> tuple:
    return (published, window_days, published, window_days)


def find_duplicate_group(cur, row: dict) -> Optional[DuplicateMatch]:
    """The group this item belongs to, or None if it is the only one of itself.

    ``row`` needs ``url_hash``, ``canonical_url_hash`` and ``published``.

    Prefers an existing group's representative. Failing that, an ungrouped
    item with the same canonical URL starts one, the older of the two being
    the representative -- it was stored first, so it is the original.

    Pure lookup: the returned ``group_hash`` can name an item that is not in
    ``item_duplicates`` yet, which is why the match carries every row to write
    rather than just the joining one. ``record_membership`` does the writing.
    """
    canonical_hash = row.get("canonical_url_hash")
    if not canonical_hash:
        return None

    # Already in a group. Worth checking because pairing two ungrouped items
    # writes both of them, so an item can be grouped before the job reaches
    # it -- and looking for a second group for it is how one set of duplicates
    # ends up split across two.
    cur.execute(
        "SELECT 1 FROM item_duplicates WHERE item_url_hash = %s",
        (row["url_hash"],),
    )
    if cur.fetchone():
        return None

    window_days = config.get_int("DUPLICATE_WINDOW_DAYS")
    max_group = config.get_int("DUPLICATE_MAX_GROUP")
    window = _window_params(row["published"], window_days)

    # An established group, matched against its representative only.
    cur.execute(
        "SELECT d.group_hash, (SELECT COUNT(*) FROM item_duplicates m"
        "  WHERE m.group_hash = d.group_hash) AS group_size "
        "FROM item_duplicates d "
        "JOIN items i ON i.url_hash = d.item_url_hash "
        "WHERE d.item_url_hash = d.group_hash "
        "AND i.canonical_url_hash = %s AND i.url_hash <> %s" + _WINDOW_SQL + " "
        f"ORDER BY {_PUBLISHED} ASC, i.url_hash LIMIT 1",
        (canonical_hash, row["url_hash"]) + window,
    )
    existing = cur.fetchone()
    if existing:
        if existing["group_size"] >= max_group:
            # the backstop: leave it visible rather than grow the group
            return None
        return DuplicateMatch(
            group_hash=existing["group_hash"],
            signal=SIGNAL_CANONICAL_URL,
            confidence=CANONICAL_URL_CONFIDENCE,
            members=(row["url_hash"],),
        )

    # No group yet, so look for a peer to start one with.
    cur.execute(
        "SELECT i.url_hash, " + _PUBLISHED + " AS published FROM items i "
        "LEFT JOIN item_duplicates d ON d.item_url_hash = i.url_hash "
        "WHERE i.canonical_url_hash = %s AND i.url_hash <> %s "
        "AND d.item_url_hash IS NULL" + _WINDOW_SQL + " "
        f"ORDER BY {_PUBLISHED} ASC, i.url_hash LIMIT 1",
        (canonical_hash, row["url_hash"]) + window,
    )
    peer = cur.fetchone()
    if not peer:
        return None

    # The older of the pair anchors the group, so the group's identity does not
    # depend on which of the two the job happened to reach first.
    pair = sorted(
        ((row["published"], row["url_hash"]), (peer["published"], peer["url_hash"])),
    )
    return DuplicateMatch(
        group_hash=pair[0][1],
        signal=SIGNAL_CANONICAL_URL,
        confidence=CANONICAL_URL_CONFIDENCE,
        members=(pair[1][1],),
    )


def record_membership(cur, match: DuplicateMatch) -> None:
    """Write ``match``'s rows, creating the group if it does not exist yet.

    The representative's own row is what makes a group exist (its
    ``item_url_hash`` equals its ``group_hash``), so it goes first. Every write
    is idempotent: an established group already has its representative, and an
    item keeps the group it is already in.
    """
    for url_hash in match.rows:
        cur.execute(
            "INSERT INTO item_duplicates "
            "(item_url_hash, group_hash, signal, confidence) "
            "VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (item_url_hash) DO NOTHING",
            (url_hash, match.group_hash, match.signal, match.confidence),
        )


def group_members(group_hash: str) -> list:
    """Every item in a group, representative included."""
    with get_db_con() as cur:
        cur.execute(
            "SELECT item_url_hash, group_hash, signal, confidence, detected_at "
            "FROM item_duplicates WHERE group_hash = %s ORDER BY item_url_hash",
            (group_hash,),
        )
        return cur.fetchall()


def duplicate_detection_job() -> None:
    """Group the items that have not been looked at yet.

    Works a batch at a time and stamps ``dedup_computed_at`` as it goes, so the
    pass is restartable and an install with a large backlog catches up over
    several runs rather than in one long transaction. Each item is its own
    transaction: one unusable URL then costs that item, not the batch.

    It also fills in ``canonical_url`` for rows that have none, which is what
    backfills an existing install -- the column is pure CPU over a URL that is
    already stored, so there is nothing to fetch and no reason to make it a
    separate pass.
    """
    batch_size = config.get_int("DUPLICATE_DETECTION_BATCH_SIZE")
    with get_db_con() as cur:
        cur.execute(
            "SELECT url_hash, url, canonical_url_hash, "
            "COALESCE(date_published, created_at) AS published "
            "FROM items WHERE dedup_computed_at IS NULL "
            "ORDER BY created_at ASC LIMIT %s",
            (batch_size,),
        )
        rows = cur.fetchall()

    if not rows:
        return

    grouped = 0
    for row in rows:
        try:
            grouped += _detect_one(row)
        except Exception as e:
            logging.exception(f"Duplicate detection for {row['url']} failed: {e}")

    logging.info(
        f"Duplicate detection: {len(rows)} item(s) examined, "
        f"{grouped} added to a group"
    )


def _detect_one(row: dict) -> int:
    """Group one item. Returns 1 if it joined a group, 0 otherwise."""
    with get_db_con() as cur:
        if row["canonical_url_hash"] is None:
            canonical, canonical_hash = canonical_columns(row["url"])
            cur.execute(
                "UPDATE items SET canonical_url = %s, canonical_url_hash = %s "
                "WHERE url_hash = %s",
                (canonical, canonical_hash, row["url_hash"]),
            )
            row = dict(row, canonical_url_hash=canonical_hash)

        match = find_duplicate_group(cur, row)
        if match is not None:
            record_membership(cur, match)

        cur.execute(
            "UPDATE items SET dedup_computed_at = NOW() WHERE url_hash = %s",
            (row["url_hash"],),
        )

    if match is None:
        return 0

    # A vote is about the content, so it covers every copy of it -- including
    # one that only just arrived. Every item this match wrote is newly grouped,
    # so every one of them can inherit. Done after the transaction above so a
    # failure here cannot undo the grouping.
    for url_hash in match.rows:
        inherit_votes_from_duplicates(url_hash)
    return 1
