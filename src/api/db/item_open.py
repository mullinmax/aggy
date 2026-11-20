"""What was opened, when, and for how long (see V27).

A vote says what you thought of an article. An open says you looked, and how
long you stayed, which is the only evidence there is about the far larger
number of articles that never get a vote.

Nothing ranks on this yet. The prediction experiments read it, in aggregate, to
find out which of these signals actually goes with an upvote.
"""

from typing import List, Optional

from .base import get_db_con

SURFACE_READER = "reader"
SURFACE_LINK = "link"
SURFACES = (SURFACE_READER, SURFACE_LINK)

# A reader left open overnight is not eight hours of reading. The page stops
# its own clock while hidden; this is the backstop for a clock that lied.
MAX_SECONDS = 60 * 60

# Reading-time bands the engagement report groups opens into.
DWELL_BANDS = (
    ("under_5s", 0, 5),
    ("5s_to_30s", 5, 30),
    ("30s_to_2m", 30, 120),
    ("over_2m", 120, None),
)


def record_open(
    user_hash: str, feed_hash: str, item_url_hash: str, surface: str
) -> int:
    with get_db_con() as cur:
        cur.execute(
            "INSERT INTO item_opens (user_hash, feed_hash, item_url_hash, surface) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (user_hash, feed_hash, item_url_hash, surface),
        )
        return cur.fetchone()["id"]


def record_seconds(user_hash: str, open_id: int, seconds: float) -> bool:
    """Set how long an open lasted. Reported more than once as the reader stays
    open (so a closed tab still leaves the last figure behind), hence GREATEST:
    a late, smaller report must not shorten what is already known."""
    seconds = max(0.0, min(float(seconds), MAX_SECONDS))
    with get_db_con() as cur:
        cur.execute(
            "UPDATE item_opens SET seconds = GREATEST(COALESCE(seconds, 0), %s) "
            "WHERE id = %s AND user_hash = %s",
            (seconds, open_id, user_hash),
        )
        return cur.rowcount > 0


def first_opens(user_hash: str, feed_hash: str) -> List[dict]:
    """Each article opened in this feed, with the first time it was."""
    with get_db_con() as cur:
        cur.execute(
            "SELECT item_url_hash, MIN(opened_at) AS opened_at FROM item_opens "
            "WHERE user_hash = %s AND feed_hash = %s GROUP BY item_url_hash",
            (user_hash, feed_hash),
        )
        return cur.fetchall()


def _outcome_columns(prefix: str = "") -> str:
    return (
        f"COUNT(*) AS {prefix}opens, "
        f"COUNT(*) FILTER (WHERE v.score > 0) AS {prefix}upvoted, "
        f"COUNT(*) FILTER (WHERE v.score = 0) AS {prefix}neutral, "
        f"COUNT(*) FILTER (WHERE v.score < 0) AS {prefix}downvoted, "
        f"COUNT(*) FILTER (WHERE v.score IS NULL) AS {prefix}unvoted"
    )


def engagement_summary(user_hash: str, feed_hashes: Optional[List[str]] = None) -> dict:
    """Counts relating opens to votes. Aggregate only: no article is named.

    Answers the questions that decide whether opens are worth learning from.
    How much of what is opened never gets a vote? Does a longer read go with an
    upvote? Does following the link out?
    """
    where = "o.user_hash = %s"
    params: list = [user_hash]
    if feed_hashes is not None:
        where += " AND o.feed_hash = ANY(%s)"
        params.append(list(feed_hashes))
    # one row per (article, way it was opened): the longest stay counts, and an
    # article opened five times is still one article with one vote
    opened = (
        "SELECT o.item_url_hash, o.surface, MAX(o.seconds) AS seconds, "
        "MIN(o.opened_at) AS opened_at FROM item_opens o "
        f"WHERE {where} GROUP BY o.item_url_hash, o.surface"
    )
    join = (
        f" FROM ({opened}) o LEFT JOIN user_item_votes v "
        "ON v.user_hash = %s AND v.item_url_hash = o.item_url_hash"
    )
    out: dict = {"by_surface": {}, "by_reading_time": {}}
    with get_db_con() as cur:
        cur.execute(
            f"SELECT COUNT(*) AS opens, MIN(o.opened_at) AS since FROM item_opens o "
            f"WHERE {where}",
            params,
        )
        row = cur.fetchone()
        out["opens_recorded"] = row["opens"]
        out["recording_since"] = row["since"].isoformat() if row["since"] else None

        cur.execute(
            f"SELECT o.surface, {_outcome_columns()}{join} GROUP BY o.surface",
            params + [user_hash],
        )
        for row in cur.fetchall():
            out["by_surface"][row["surface"]] = {
                key: row[key]
                for key in ("opens", "upvoted", "neutral", "downvoted", "unvoted")
            }

        for name, low, high in DWELL_BANDS:
            band = " WHERE o.surface = %s AND o.seconds >= %s"
            band_params = params + [user_hash, SURFACE_READER, low]
            if high is not None:
                band += " AND o.seconds < %s"
                band_params.append(high)
            cur.execute(f"SELECT {_outcome_columns()}{join}{band}", band_params)
            row = cur.fetchone()
            out["by_reading_time"][name] = {
                key: row[key]
                for key in ("opens", "upvoted", "neutral", "downvoted", "unvoted")
            }
    return out
