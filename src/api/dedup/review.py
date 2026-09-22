"""The pairs of articles worth asking you about.

Detection's content signal is a cosine against a constant, and the constant was
picked by hand. Asking you to confirm what it collapsed would produce a pile of
labels that are almost all "yes" -- it only collapses pairs it is already sure
about -- and a model trained on those learns nothing about where the line
belongs, because it never sees a pair near it.

So the queue holds two kinds of pair, and the mix is the point:

  * **collapsed** pairs, each a member against its group's representative.
    These are the calls detection actually made, and rejecting one puts an
    article back in your feed.
  * **near-misses**, neighbours whose similarity falls between
    ``DUPLICATE_CANDIDATE_FLOOR`` and the threshold: pairs detection looked at
    and declined. Nothing about them is visible in the feed today, which is
    exactly why nobody would ever find them to correct.

They come back ordered by how close each pair sits to the current decision
point, nearest first. A pair the constant is confident about teaches a model
very little whichever way you answer it; a pair sitting on the line teaches it
where the line is.

A pair you have already judged is never offered again -- that verdict is
already doing its work in ``dedup.detect``.
"""

from typing import List

from config import config
from db.base import get_db_con

from .labels import labels_for, pair_key

# One row per (member, representative) pair in a feed's groups. The
# representative is the member whose item_url_hash is its own group_hash, so
# the join to it is the group_hash itself.
_COLLAPSED_SQL = """
SELECT d.item_url_hash AS candidate_hash,
       d.group_hash    AS anchor_hash,
       d.signal,
       d.confidence
FROM item_duplicates d
JOIN feed_items f
  ON f.user_hash = d.user_hash AND f.item_url_hash = d.item_url_hash
WHERE d.user_hash = %s
  AND f.feed_hash = %s
  AND d.group_hash IS NOT NULL
  AND d.group_hash <> d.item_url_hash
ORDER BY d.confidence ASC
LIMIT %s
"""

# Neighbour pairs in the band detection declines. Ordered on the edge rather
# than deduplicated in SQL: an edge and its mirror both appear, and the caller
# folds them by normalised pair.
_NEAR_MISS_SQL = """
SELECT n.item_url_hash     AS candidate_hash,
       n.neighbor_url_hash AS anchor_hash,
       n.similarity
FROM item_neighbors n
LEFT JOIN item_duplicates a
  ON a.user_hash = n.user_hash AND a.item_url_hash = n.item_url_hash
LEFT JOIN item_duplicates b
  ON b.user_hash = n.user_hash AND b.item_url_hash = n.neighbor_url_hash
WHERE n.user_hash = %s
  AND n.feed_hash = %s
  AND n.similarity >= %s
  AND n.similarity < %s
  -- already in the same group, so it is a collapsed pair, not a near-miss
  AND (a.group_hash IS NULL OR b.group_hash IS NULL OR a.group_hash <> b.group_hash)
ORDER BY n.similarity DESC
LIMIT %s
"""

# Everything the page needs to show one article: enough to recognise it
# without opening it.
_ARTICLE_SQL = """
SELECT i.url_hash, i.url, i.title, i.author, i.image_url, i.excerpt,
       COALESCE(i.date_published, i.created_at) AS published, (
  SELECT s.name FROM source_items si
  JOIN sources s ON s.user_hash = si.user_hash
   AND s.feed_hash = si.feed_hash AND s.name_hash = si.source_hash
  WHERE si.user_hash = %s AND si.feed_hash = %s
   AND si.item_url_hash = i.url_hash LIMIT 1) AS source_name
FROM items i
WHERE i.url_hash = ANY(%s)
"""


def review_pairs(user_hash: str, feed_hash: str, limit: int = 20) -> List[dict]:
    """The next pairs to ask about, most uncertain first.

    Each returned pair carries both articles in full, which side detection
    treats as the anchor, what it decided and how sure it was -- the page shows
    a verdict to agree or disagree with, not a blind comparison.
    """
    threshold = config.get_float("DUPLICATE_SIMILARITY_THRESHOLD")
    floor = min(config.get_float("DUPLICATE_CANDIDATE_FLOOR"), threshold)
    # Over-fetch both kinds: the labels you have already given are filtered out
    # below, and mirrored neighbour edges fold in pairs.
    fetch = max(limit * 4, 40)

    with get_db_con() as cur:
        cur.execute(_COLLAPSED_SQL, (user_hash, feed_hash, fetch))
        collapsed = cur.fetchall()
        cur.execute(_NEAR_MISS_SQL, (user_hash, feed_hash, floor, threshold, fetch))
        near_misses = cur.fetchall()

        candidates = {}
        for row in collapsed:
            key = pair_key(row["candidate_hash"], row["anchor_hash"])
            # confidence is the similarity for the embedding signal and a flat
            # 1.0 for a canonical-URL match, which is what makes a URL match
            # sort last: there is nothing to learn from confirming one.
            candidates.setdefault(
                key,
                {
                    "candidate_hash": row["candidate_hash"],
                    "anchor_hash": row["anchor_hash"],
                    "grouped": True,
                    "signal": row["signal"],
                    "similarity": float(row["confidence"] or 0.0),
                },
            )
        for row in near_misses:
            key = pair_key(row["candidate_hash"], row["anchor_hash"])
            candidates.setdefault(
                key,
                {
                    "candidate_hash": row["candidate_hash"],
                    "anchor_hash": row["anchor_hash"],
                    "grouped": False,
                    "signal": None,
                    "similarity": float(row["similarity"]),
                },
            )

        judged = labels_for(cur, user_hash, candidates.keys())
        pending = [pair for key, pair in candidates.items() if key not in judged]
        # Closest to the decision point first: a pair the constant is sure
        # about teaches a model little whichever way it is answered.
        pending.sort(key=lambda pair: abs(pair["similarity"] - threshold))
        pending = pending[:limit]
        if not pending:
            return []

        wanted = {pair["candidate_hash"] for pair in pending}
        wanted |= {pair["anchor_hash"] for pair in pending}
        cur.execute(_ARTICLE_SQL, (user_hash, feed_hash, list(wanted)))
        articles = {row["url_hash"]: row for row in cur.fetchall()}

    out = []
    for pair in pending:
        candidate = articles.get(pair["candidate_hash"])
        anchor = articles.get(pair["anchor_hash"])
        # An article can leave the feed between the two queries, and half a
        # pair is not a question anyone can answer.
        if candidate is None or anchor is None:
            continue
        out.append({**pair, "candidate": candidate, "anchor": anchor})
    return out
