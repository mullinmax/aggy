"""Your verdicts on whether two articles are the same story.

A label is used two ways, and the distinction matters.

As an **instruction**: a pair you rejected is never grouped again, and a pair
you confirmed is grouped whatever the cosine between them says. This is not a
hint the detector weighs up -- you looked at both articles, which is more than
any signal here can do, so your answer wins outright.

As a **training label**: enough of them and a model can learn where the line
falls for your articles instead of taking the hand-picked constant (see
``dedup.model``). That model then decides the pairs you have *not* looked at.

Pairs are unordered. Which article was on the left of the screen carries no
meaning, so every pair is normalised to sorted order before it is stored or
looked up, and ``duplicate_labels`` has a CHECK making that the only
representable form.
"""

from typing import Dict, Iterable, List, Optional, Tuple

from db.base import get_db_con


def pair_key(one: str, other: str) -> Tuple[str, str]:
    """The pair as it is stored: sorted, so the same two articles are one row
    however they were presented."""
    return (one, other) if one < other else (other, one)


def record_label(user_hash: str, one: str, other: str, is_duplicate: bool) -> None:
    """Write your verdict, replacing any earlier one on the same pair.

    Changing your mind is a correction, not a second opinion: the row is
    overwritten and ``labeled_at`` moves, so the training set holds what you
    currently think rather than a history of what you once thought.
    """
    left, right = pair_key(one, other)
    with get_db_con() as cur:
        cur.execute(
            "INSERT INTO duplicate_labels "
            "(user_hash, left_hash, right_hash, is_duplicate) "
            "VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (user_hash, left_hash, right_hash) DO UPDATE SET "
            "is_duplicate = EXCLUDED.is_duplicate, labeled_at = NOW()",
            (user_hash, left, right, is_duplicate),
        )


def label_for(cur, user_hash: str, one: str, other: str) -> Optional[bool]:
    """Your verdict on one pair, or None if you have not judged it."""
    left, right = pair_key(one, other)
    cur.execute(
        "SELECT is_duplicate FROM duplicate_labels "
        "WHERE user_hash = %s AND left_hash = %s AND right_hash = %s",
        (user_hash, left, right),
    )
    row = cur.fetchone()
    return None if row is None else bool(row["is_duplicate"])


def labels_for(
    cur, user_hash: str, pairs: Iterable[Tuple[str, str]]
) -> Dict[Tuple[str, str], bool]:
    """Your verdicts on many pairs at once, keyed by the normalised pair.

    The detector asks about every candidate a walk turned up, and the review
    queue asks about every pair it is about to offer; both would otherwise be
    a query per pair.
    """
    keys = {pair_key(one, other) for one, other in pairs}
    if not keys:
        return {}
    cur.execute(
        "SELECT left_hash, right_hash, is_duplicate FROM duplicate_labels "
        "WHERE user_hash = %s AND (left_hash, right_hash) IN "
        "(SELECT * FROM UNNEST(%s::text[], %s::text[]))",
        (user_hash, [k[0] for k in keys], [k[1] for k in keys]),
    )
    return {
        (row["left_hash"], row["right_hash"]): bool(row["is_duplicate"])
        for row in cur.fetchall()
    }


def label_count(user_hash: str) -> Tuple[int, int]:
    """How many pairs you have confirmed and rejected.

    Both numbers matter to the model rather than their total: a classifier
    needs to have seen each answer at least once, and a set that is all
    confirmations teaches it only to say yes.
    """
    with get_db_con() as cur:
        cur.execute(
            "SELECT "
            "COUNT(*) FILTER (WHERE is_duplicate) AS confirmed, "
            "COUNT(*) FILTER (WHERE NOT is_duplicate) AS rejected "
            "FROM duplicate_labels WHERE user_hash = %s",
            (user_hash,),
        )
        row = cur.fetchone() or {}
    return int(row.get("confirmed") or 0), int(row.get("rejected") or 0)


def labeled_pairs(user_hash: str) -> List[dict]:
    """Every pair you have judged, as rows the model can build features from.

    Both articles are joined in full because a pair's features are not only
    about its embeddings: when it was published, who published it and what it
    is called all separate a rewrite of the same story from two pieces that
    merely cover the same subject.
    """
    with get_db_con() as cur:
        cur.execute(
            "SELECT d.left_hash, d.right_hash, d.is_duplicate, "
            "l.title AS left_title, l.url AS left_url, "
            "l.author AS left_author, "
            "COALESCE(l.date_published, l.created_at) AS left_published, "
            "l.embeddings AS left_embeddings, "
            "l.image_embeddings AS left_image_embeddings, "
            "r.title AS right_title, r.url AS right_url, "
            "r.author AS right_author, "
            "COALESCE(r.date_published, r.created_at) AS right_published, "
            "r.embeddings AS right_embeddings, "
            "r.image_embeddings AS right_image_embeddings "
            "FROM duplicate_labels d "
            "JOIN items l ON l.url_hash = d.left_hash "
            "JOIN items r ON r.url_hash = d.right_hash "
            "WHERE d.user_hash = %s "
            "ORDER BY d.labeled_at DESC",
            (user_hash,),
        )
        return list(cur.fetchall())
