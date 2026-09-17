"""Find the duplicate group an item belongs to, and keep the table current.

Matching is **per account**. Two users holding the same article are never
compared against each other, and every group contains only items one account
holds. That boundary is deliberate: a shared group would let one account's data
change another's feed (a widely-held article would fill DUPLICATE_MAX_GROUP
with strangers' copies, and your own two copies would stop being grouped), and
the text and image signals still to come compare article *content*, which is
exactly the comparison that must not cross accounts.

Which member of a group is *shown* is then a per-feed decision made at query
time, because the prediction it is decided by lives on ``feed_items`` -- see
``Feed.query_items_with_sources``.

Groups are a star, not a transitive closure. Each group has one representative
and a new item joins only if it matches *that*, never merely some member.
A~B and B~C does not make A~C, and taking the closure is exactly how a
400-item mega-group happens. ``DUPLICATE_MAX_GROUP`` is a second backstop
behind that; an item that would overflow a group is simply left ungrouped,
because an uncollapsed duplicate is a much cheaper mistake than a wrong
collapse.

The representative is only the anchor that makes a group exist -- it is the
member that was published first, and carries no other meaning. The member the
feed actually shows is whichever the current model scores highest, so it
changes as the model does.
"""

import logging
from dataclasses import dataclass
from typing import Optional

from config import config
from db.base import AggyBaseModel, get_db_con
from db.propagation import inherit_votes_from_duplicates
from db.task_run import KIND_DUPLICATE_DETECTION, task_run

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

    user_hash: str
    group_hash: str
    signal: str
    confidence: float
    members: tuple = ()

    @property
    def rows(self) -> tuple:
        """Every item this match puts in the group, representative first and
        without repeats."""
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
    """The group this item belongs to for this account, or None if it is the
    only copy the account holds.

    ``row`` needs ``user_hash``, ``url_hash``, ``canonical_url_hash`` and
    ``published``.

    Prefers an established group's representative. Failing that, another of
    this account's items with the same canonical URL starts one, the earlier
    published of the two being the representative.

    Every candidate query is scoped to ``user_hash``: an item another account
    holds is not a candidate, however identical it is.

    Pure lookup: the returned ``group_hash`` can name an item that has no group
    yet, which is why the match carries every row to write rather than just the
    joining one. ``record_membership`` does the writing.
    """
    canonical_hash = row.get("canonical_url_hash")
    if not canonical_hash:
        return None

    user_hash = row["user_hash"]
    window_days = config.get_int("DUPLICATE_WINDOW_DAYS")
    max_group = config.get_int("DUPLICATE_MAX_GROUP")
    window = _window_params(row["published"], window_days)

    # Already in a group for this account. Worth checking because pairing two
    # ungrouped items writes both of them, so an item can be grouped before the
    # job reaches it -- and looking for a second group for it is how one set of
    # duplicates ends up split across two.
    cur.execute(
        "SELECT 1 FROM item_duplicates "
        "WHERE user_hash = %s AND item_url_hash = %s AND group_hash IS NOT NULL",
        (user_hash, row["url_hash"]),
    )
    if cur.fetchone():
        return None

    # An established group of this account's, matched against its
    # representative only. A NULL group_hash never satisfies the
    # representative test, so ungrouped rows are skipped here.
    cur.execute(
        "SELECT d.group_hash, (SELECT COUNT(*) FROM item_duplicates m"
        "  WHERE m.user_hash = d.user_hash"
        "   AND m.group_hash = d.group_hash) AS group_size "
        "FROM item_duplicates d "
        "JOIN items i ON i.url_hash = d.item_url_hash "
        "WHERE d.user_hash = %s AND d.item_url_hash = d.group_hash "
        "AND i.canonical_url_hash = %s AND i.url_hash <> %s" + _WINDOW_SQL + " "
        f"ORDER BY {_PUBLISHED} ASC, i.url_hash LIMIT 1",
        (user_hash, canonical_hash, row["url_hash"]) + window,
    )
    existing = cur.fetchone()
    if existing:
        if existing["group_size"] >= max_group:
            # the backstop: leave it visible rather than grow the group
            return None
        return DuplicateMatch(
            user_hash=user_hash,
            group_hash=existing["group_hash"],
            signal=SIGNAL_CANONICAL_URL,
            confidence=CANONICAL_URL_CONFIDENCE,
            members=(row["url_hash"],),
        )

    # No group yet, so look for another of this account's items to start one
    # with -- one that is either unexamined or examined and still ungrouped.
    cur.execute(
        "SELECT i.url_hash, " + _PUBLISHED + " AS published "
        "FROM feed_items c "
        "JOIN items i ON i.url_hash = c.item_url_hash "
        "LEFT JOIN item_duplicates d ON d.user_hash = c.user_hash"
        " AND d.item_url_hash = c.item_url_hash "
        "WHERE c.user_hash = %s "
        "AND i.canonical_url_hash = %s AND i.url_hash <> %s "
        "AND d.group_hash IS NULL" + _WINDOW_SQL + " "
        f"ORDER BY {_PUBLISHED} ASC, i.url_hash LIMIT 1",
        (user_hash, canonical_hash, row["url_hash"]) + window,
    )
    peer = cur.fetchone()
    if not peer:
        return None

    # The earlier published of the pair anchors the group, so the group's
    # identity does not depend on which of the two the job reached first.
    pair = sorted(
        ((row["published"], row["url_hash"]), (peer["published"], peer["url_hash"])),
    )
    return DuplicateMatch(
        user_hash=user_hash,
        group_hash=pair[0][1],
        signal=SIGNAL_CANONICAL_URL,
        confidence=CANONICAL_URL_CONFIDENCE,
        members=(pair[1][1],),
    )


def record_membership(cur, match: DuplicateMatch) -> None:
    """Write ``match``'s rows, creating the group if it does not exist yet.

    The representative's own row is what makes a group exist (its
    ``item_url_hash`` equals its ``group_hash``), so it goes first.

    The upsert only ever fills in a group on a row that has none, so an item
    already in a group is never moved into another one -- which is what keeps
    groups from drifting as the re-sweep revisits their neighbours.
    """
    for url_hash in match.rows:
        cur.execute(
            "INSERT INTO item_duplicates "
            "(user_hash, item_url_hash, group_hash, signal, confidence) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (user_hash, item_url_hash) DO UPDATE SET "
            "group_hash = EXCLUDED.group_hash, signal = EXCLUDED.signal, "
            "confidence = EXCLUDED.confidence, checked_at = NOW() "
            "WHERE item_duplicates.group_hash IS NULL",
            (
                match.user_hash,
                url_hash,
                match.group_hash,
                match.signal,
                match.confidence,
            ),
        )


def record_examined(cur, user_hash: str, url_hash: str) -> None:
    """Note that this item was examined for this account and is not a duplicate
    of anything the account holds.

    These rows are the re-sweep's queue, not bookkeeping for its own sake: an
    item becomes a duplicate later when a second copy arrives, and without a
    record of having looked there is no way to tell "unique" from "not yet
    examined". ``checked_at`` moves so the sweep works oldest-first.
    """
    cur.execute(
        "INSERT INTO item_duplicates (user_hash, item_url_hash) VALUES (%s, %s) "
        "ON CONFLICT (user_hash, item_url_hash) DO UPDATE SET checked_at = NOW() "
        "WHERE item_duplicates.group_hash IS NULL",
        (user_hash, url_hash),
    )


def group_members(user_hash: str, group_hash: str) -> list:
    """Every item in one of this account's groups, representative included."""
    with get_db_con() as cur:
        cur.execute(
            "SELECT item_url_hash, group_hash, signal, confidence, checked_at "
            "FROM item_duplicates "
            "WHERE user_hash = %s AND group_hash = %s ORDER BY item_url_hash",
            (user_hash, group_hash),
        )
        return cur.fetchall()


# The pending queue: (account, item) pairs nobody has examined yet. An item in
# several of one account's feeds is one candidate, hence the DISTINCT.
#
# Deliberately unordered. Pairing is symmetric -- whichever of two copies is
# examined first pairs with the other -- and the representative is chosen from
# the pair's publish dates rather than from processing order, so the outcome
# does not depend on which rows come back. Letting Postgres stop at the limit
# instead of sorting the whole anti-join is what keeps the first pass over a
# large existing corpus affordable.
_PENDING_SQL = """
SELECT DISTINCT c.user_hash, i.url_hash, i.url, i.canonical_url_hash,
       COALESCE(i.date_published, i.created_at) AS published
FROM feed_items c
JOIN items i ON i.url_hash = c.item_url_hash
LEFT JOIN item_duplicates d
    ON d.user_hash = c.user_hash AND d.item_url_hash = c.item_url_hash
WHERE d.item_url_hash IS NULL
LIMIT %s
"""

# The re-sweep queue: examined, still ungrouped, and not looked at recently.
# This is what makes detection cover articles it has already seen -- an item is
# only unique until a second copy of it arrives, and the item that arrived
# first has already been examined by then.
_RECHECK_SQL = """
SELECT d.user_hash, i.url_hash, i.url, i.canonical_url_hash,
       COALESCE(i.date_published, i.created_at) AS published
FROM item_duplicates d
JOIN items i ON i.url_hash = d.item_url_hash
WHERE d.group_hash IS NULL
  AND d.checked_at < NOW() - make_interval(days => %s)
ORDER BY d.checked_at ASC
LIMIT %s
"""


def duplicate_detection_job() -> None:
    """Examine the (account, item) pairs that are due, and group what matches.

    Two queues, worked in order of value:

    1. Pairs nobody has looked at yet. On an existing install that is the whole
       corpus, which is what backfills it -- a batch per pass rather than one
       long transaction.
    2. Pairs examined before and found unique, re-examined once they are older
       than DUPLICATE_RECHECK_DAYS. Being unique is not permanent: a second copy
       arrives later, or a threshold changes, and the copy that arrived first
       has already been examined by then.

    Each item is its own transaction, so one unusable URL costs that item and
    not the batch. ``canonical_url`` is filled in for rows that have none, which
    is pure CPU over a URL already stored and so needs no pass of its own.
    """
    batch_size = config.get_int("DUPLICATE_DETECTION_BATCH_SIZE")
    recheck_days = config.get_int("DUPLICATE_RECHECK_DAYS")

    with get_db_con() as cur:
        cur.execute(_PENDING_SQL, (batch_size,))
        rows = cur.fetchall()

    # Only sweep once the backlog is clear, and only up to the batch size, so a
    # busy install always spends its budget on articles it has never examined.
    rechecked = 0
    if len(rows) < batch_size:
        with get_db_con() as cur:
            cur.execute(_RECHECK_SQL, (recheck_days, batch_size - len(rows)))
            recheck_rows = cur.fetchall()
        rechecked = len(recheck_rows)
        rows = rows + recheck_rows

    if not rows:
        return

    # Recorded only once there is something to examine: a pass with an empty
    # queue returned above, and a timeline of empty passes every half hour
    # would bury the ones that did work. System-wide, with no user_hash --
    # the queue spans every account, so calling it any one account's work
    # would be a lie.
    grouped = 0
    with task_run(KIND_DUPLICATE_DETECTION) as run:
        for row in rows:
            try:
                grouped += _detect_one(row)
            except Exception as e:
                logging.exception(f"Duplicate detection for {row['url']} failed: {e}")
        run.detail = (
            f"{len(rows)} examined ({rechecked} re-examined), {grouped} grouped"
        )

    logging.info(
        f"Duplicate detection: {len(rows)} item(s) examined "
        f"({rechecked} re-examined), {grouped} added to a group"
    )


def _detect_one(row: dict) -> int:
    """Examine one (account, item) pair. Returns 1 if it joined a group."""
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
        if match is None:
            record_examined(cur, row["user_hash"], row["url_hash"])
        else:
            record_membership(cur, match)

    if match is None:
        return 0

    # A vote is about the content, so it covers every copy of it -- including
    # one that only just arrived. Every item this match wrote is newly grouped,
    # so every one of them can inherit. Done after the transaction above so a
    # failure here cannot undo the grouping.
    for url_hash in match.rows:
        inherit_votes_from_duplicates(match.user_hash, url_hash)
    return 1
