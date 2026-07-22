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
            _mirror_into(
                cur, user_hash, sub["feed_hash"], sub["name_hash"], url_hashes
            )

    # Recurse after committing this level so downstream feeds see the rows.
    for sub in subs:
        propagate_items(user_hash, sub["feed_hash"], url_hashes, _visited)
