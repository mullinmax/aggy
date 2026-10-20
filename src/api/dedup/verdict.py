"""What clicking the check or the x actually does.

A verdict is recorded either way -- that is the training label, and the
instruction detection obeys from then on (see ``dedup.labels``). What varies is
what happens to the grouping in front of you, and the rule is that the click
does what it looks like it does: reject a collapse and the hidden article comes
back, confirm a pair the feed is showing twice and it stops showing it twice.

The one thing a verdict will not do is merge two established groups. You judged
one pair; a merge would assert that every member of one group is the same story
as every member of the other, which is the transitive closure the star topology
exists to prevent (see V21). The label is still recorded, so detection will act
on that pair the moment the star rule is satisfied honestly.
"""

import logging
from typing import Optional

from db.base import get_db_con
from db.propagation import inherit_votes_from_duplicates

from .detect import DuplicateMatch, record_membership
from .labels import record_label

# A group built from your own verdict rather than from a signal. Its confidence
# is a flat 1.0 for the same reason the canonical-URL signal's is: you looked
# at both articles, and there is no measurement here to be uncertain about.
SIGNAL_CONFIRMED = "confirmed"
CONFIRMED_CONFIDENCE = 1.0


def _membership(cur, user_hash: str, url_hash: str) -> Optional[str]:
    cur.execute(
        "SELECT group_hash FROM item_duplicates "
        "WHERE user_hash = %s AND item_url_hash = %s",
        (user_hash, url_hash),
    )
    row = cur.fetchone()
    return None if row is None else row["group_hash"]


def _published(cur, url_hash: str):
    cur.execute(
        "SELECT COALESCE(date_published, created_at) AS published "
        "FROM items WHERE url_hash = %s",
        (url_hash,),
    )
    row = cur.fetchone()
    return None if row is None else row["published"]


def _split_out(cur, user_hash: str, url_hash: str) -> None:
    """Take one article out of its group.

    It becomes "examined, and not a duplicate of anything", which is what
    ``item_duplicates`` has always meant by a NULL group_hash -- so it reappears
    in the feed and stays in the re-sweep queue like any other single article.
    Its checked_at moves so the re-sweep does not pick it straight back up.

    The votes it inherited while grouped are left alone. A vote is a fact about
    an article you now say is its own article, and quietly withdrawing it would
    change your own ranking as a side effect of a correction about something
    else.
    """
    cur.execute(
        "UPDATE item_duplicates "
        "SET group_hash = NULL, signal = NULL, confidence = NULL, checked_at = NOW() "
        "WHERE user_hash = %s AND item_url_hash = %s",
        (user_hash, url_hash),
    )


def apply_verdict(
    user_hash: str, candidate_hash: str, anchor_hash: str, is_duplicate: bool
) -> str:
    """Record your verdict on a pair and make the feed agree with it.

    Returns what it did, so the page can say so: ``split``, ``grouped``,
    ``unchanged``.
    """
    record_label(user_hash, candidate_hash, anchor_hash, is_duplicate)

    with get_db_con() as cur:
        candidate_group = _membership(cur, user_hash, candidate_hash)
        anchor_group = _membership(cur, user_hash, anchor_hash)

        if not is_duplicate:
            if candidate_group is None or candidate_group != anchor_group:
                # A near-miss you agreed was a near-miss. Nothing was
                # collapsed, so there is nothing to undo.
                return "unchanged"
            # The queue only ever offers a member against its own group's
            # representative, so the one to take out is the candidate. Taking
            # out a representative would leave its group without the row that
            # makes it exist.
            if candidate_hash == candidate_group:
                logging.warning(
                    "Refusing to split a group's representative out of itself "
                    f"({candidate_hash[:12]})"
                )
                return "unchanged"
            _split_out(cur, user_hash, candidate_hash)
            return "split"

        if candidate_group is not None and candidate_group == anchor_group:
            return "unchanged"  # already collapsed; the label just confirms it

        if candidate_group is not None and anchor_group is not None:
            # Two established groups. See the module docstring: one pair is not
            # grounds for asserting every cross-pair between them.
            return "unchanged"

        joiner, group = (
            (candidate_hash, anchor_group)
            if anchor_group is not None
            else (anchor_hash, candidate_group)
            if candidate_group is not None
            else (None, None)
        )
        if group is not None:
            # Joining an existing group means matching its representative, and
            # you judged this pair, not that one. When the article you compared
            # against is the representative those are the same statement; when
            # it is a member, they are not, so the label is left to detection
            # to act on once the star rule is genuinely satisfied.
            other = anchor_hash if joiner == candidate_hash else candidate_hash
            if other != group:
                return "unchanged"
            match = DuplicateMatch(
                user_hash=user_hash,
                group_hash=group,
                signal=SIGNAL_CONFIRMED,
                confidence=CONFIRMED_CONFIDENCE,
                members=(joiner,),
            )
        else:
            # Neither is grouped, so the two of them start one, anchored by
            # whichever was published first -- the same rule both signals use,
            # so a group's identity never depends on the order things happened.
            pair = sorted(
                (
                    (_published(cur, candidate_hash), candidate_hash),
                    (_published(cur, anchor_hash), anchor_hash),
                ),
                key=lambda entry: (entry[0] is None, entry[0], entry[1]),
            )
            match = DuplicateMatch(
                user_hash=user_hash,
                group_hash=pair[0][1],
                signal=SIGNAL_CONFIRMED,
                confidence=CONFIRMED_CONFIDENCE,
                members=(pair[1][1],),
            )

        record_membership(cur, match)

    # A vote is about the content, so it covers every copy of it. Every row the
    # match wrote is newly grouped and can inherit, which for a group the two
    # of them just started means both of them. Done after the transaction
    # above, like the detector's own path, so a failure here cannot undo the
    # grouping.
    for url_hash in match.rows:
        inherit_votes_from_duplicates(user_hash, url_hash)
    return "grouped"
