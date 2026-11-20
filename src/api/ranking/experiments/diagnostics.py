"""What a feed's votes look like, in numbers that explain a replay.

A replay says how well each method ordered a feed's votes. It does not say
why one feed is predictable and another is not, and that is the question a
flat 0.5 across every method leaves behind. These are the measurements that
tell the likely causes apart: articles with nothing to learn from (no
embedding, no neighbours), votes that were never individual judgements (cast
in bulk, or implied by a list), a taste that the embeddings do not see (the
most similar voted article agrees no more often than chance), or one that
moved over time.

Everything here is a count, a share or a median. No title, URL, source name,
author or vector leaves this module, and sources are only ever counted.
"""

from collections import Counter
from datetime import datetime, timezone
from typing import List, Optional, Sequence

import numpy as np

from ranking.models import ItemFeatures, _embedding_dim, _unit_or_zeros

from . import metrics

# Nearest-neighbour agreement compares every voted article with every other.
# The newest this many keeps that to a few million multiplications.
MAX_PAIRWISE = 2000

# Two articles this similar are, for the purpose of a vote, the same article.
NEAR_DUPLICATE = 0.97

# A source needs this many votes before its own upvote rate means anything.
MIN_SOURCE_VOTES = 5

# This many votes inside one minute is not somebody reading.
BURST_VOTES = 5


def _utc(moment: Optional[datetime]) -> Optional[datetime]:
    if moment is not None and moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment


def _share(count, total) -> Optional[float]:
    return round(float(count) / total, 4) if total else None


def _median(values) -> Optional[float]:
    values = [v for v in values if v is not None]
    return round(float(np.median(values)), 2) if values else None


def _coverage(labeled: Sequence[ItemFeatures]) -> dict:
    """How many of the voted articles carry each thing a model reads."""
    n = len(labeled)
    voted = {i.url_hash for i in labeled}
    return {
        "text_embedding": _share(sum(1 for i in labeled if i.embedding is not None), n),
        "image_embedding": _share(
            sum(1 for i in labeled if i.image_embedding is not None), n
        ),
        "stored_neighbors": _share(sum(1 for i in labeled if i.neighbors), n),
        # a neighbour list only helps a model if somebody voted on one of them
        "voted_neighbor": _share(
            sum(
                1
                for i in labeled
                if any(h in voted and h != i.url_hash for h, _ in i.neighbors)
            ),
            n,
        ),
        "publish_date": _share(
            sum(1 for i in labeled if i.date_published is not None), n
        ),
        "source": _share(sum(1 for i in labeled if i.source), n),
        "author": _share(sum(1 for i in labeled if i.author), n),
    }


def _sources(labeled: Sequence[ItemFeatures], up: np.ndarray) -> dict:
    """How the votes spread over sources, and whether the source alone says
    much about the vote. Sources are counted, never named."""
    counts = Counter(i.source for i in labeled if i.source)
    n = len(labeled)
    rates = []
    for source, count in counts.items():
        if count < MIN_SOURCE_VOTES:
            continue
        mask = np.asarray([i.source == source for i in labeled])
        rates.append(float(up[mask].mean()))
    return {
        "distinct": len(counts),
        "with_enough_votes": len(rates),
        "largest_share_of_votes": _share(max(counts.values(), default=0), n),
        # near zero: every source is upvoted about as often as every other,
        # so knowing the source tells a model nothing
        "upvote_rate_spread": round(float(np.std(rates)), 4)
        if len(rates) >= 2
        else None,
        "lowest_upvote_rate": round(min(rates), 4) if rates else None,
        "highest_upvote_rate": round(max(rates), 4) if rates else None,
    }


def _timing(labeled: Sequence[ItemFeatures], up: np.ndarray) -> dict:
    """When the votes were cast: over how long, in what bursts, and whether
    the share that are upvotes moved."""
    dates = [_utc(i.label_date) for i in labeled]
    known = [(d, bool(u)) for d, u in zip(dates, up) if d is not None]
    out = {
        "undated": _share(len(labeled) - len(known), len(labeled)),
        "span_days": None,
        "days_with_votes": None,
        "in_one_minute_bursts": None,
        "largest_burst_share": None,
        "upvote_rate_by_quarter": None,
    }
    if not known:
        return out
    known.sort(key=lambda pair: pair[0])
    moments = [d for d, _ in known]
    out["span_days"] = round((moments[-1] - moments[0]).total_seconds() / 86400.0, 1)
    out["days_with_votes"] = len({d.date() for d in moments})
    per_minute = Counter(d.replace(second=0, microsecond=0) for d in moments)
    out["in_one_minute_bursts"] = _share(
        sum(c for c in per_minute.values() if c >= BURST_VOTES), len(moments)
    )
    out["largest_burst_share"] = _share(max(per_minute.values()), len(moments))
    if len(known) >= 20:
        # oldest quarter of the votes first: a steady taste reads flat
        cast_up = np.asarray([u for _, u in known], dtype=float)
        out["upvote_rate_by_quarter"] = [
            round(float(part.mean()), 4) for part in np.array_split(cast_up, 4)
        ]
    return out


def _age_at_vote(labeled: Sequence[ItemFeatures], up: np.ndarray) -> dict:
    """How old articles were when voted on, upvoted against the rest. A wide
    gap means age at vote time separates the two on its own."""
    ages = [i.age_days() if i.label_date is not None else None for i in labeled]
    return {
        "median_days_upvoted": _median(a for a, u in zip(ages, up) if u),
        "median_days_other": _median(a for a, u in zip(ages, up) if not u),
    }


def _similar_votes(labeled: Sequence[ItemFeatures], up: np.ndarray) -> dict:
    """Does the most similar voted article tend to carry the same vote?

    This is the assumption every embedding method rests on. When the agreement
    is no better than two random votes would manage, there is no taste in the
    embeddings for any of them to find, however they are fitted."""
    out = {
        "compared": 0,
        "nearest_agrees": None,
        "agreement_by_chance": None,
        "median_nearest_similarity": None,
        "near_duplicate_share": None,
        "near_duplicates_voted_differently": None,
    }
    dim = _embedding_dim(labeled, "embedding")
    if not dim:
        return out
    rows, votes = [], []
    for item, is_up in zip(labeled, up):
        vector, ok = _unit_or_zeros(item.embedding, dim)
        if ok:
            rows.append(vector)
            votes.append(bool(is_up))
    rows, votes = rows[-MAX_PAIRWISE:], np.asarray(votes[-MAX_PAIRWISE:])
    if len(rows) < 10:
        return out
    matrix = np.asarray(rows, dtype=np.float32)
    similarity = matrix @ matrix.T
    np.fill_diagonal(similarity, -np.inf)
    nearest = similarity.argmax(axis=1)
    closeness = similarity[np.arange(len(rows)), nearest]
    agrees = votes == votes[nearest]
    rate = float(votes.mean())
    twins = closeness >= NEAR_DUPLICATE
    out.update(
        {
            "compared": len(rows),
            "nearest_agrees": round(float(agrees.mean()), 4),
            "agreement_by_chance": round(rate * rate + (1 - rate) * (1 - rate), 4),
            "median_nearest_similarity": round(float(np.median(closeness)), 4),
            "near_duplicate_share": round(float(twins.mean()), 4),
            "near_duplicates_voted_differently": round(
                float((~agrees[twins]).mean()), 4
            )
            if twins.any()
            else None,
        }
    )
    return out


def _label_origin(labeled: Sequence[ItemFeatures], origins: Optional[dict]) -> dict:
    """Where the labels came from. An article added to a list counts as an
    upvote without anyone having voted on it, and a feed whose "upvotes" are
    mostly that is being asked a different question."""
    if origins is None:
        return {}
    n = len(labeled)
    rows = [origins.get(i.url_hash) for i in labeled]
    rows = [r for r in rows if r is not None]
    return {
        "list_only": _share(sum(1 for r in rows if r["vote"] is None), n),
        "vote_and_list": _share(
            sum(1 for r in rows if r["vote"] is not None and r["listed"]), n
        ),
        "vote_only": _share(sum(1 for r in rows if not r["listed"]), n),
    }


def diagnose(
    labeled: Sequence[ItemFeatures], origins: Optional[dict] = None
) -> Optional[dict]:
    """Every measurement above for one feed's voted articles.

    `origins` maps an article's hash to `{"vote": score or None, "listed":
    bool}` when the caller knows how each label came about.
    """
    labeled: List[ItemFeatures] = sorted(
        labeled,
        key=lambda i: _utc(i.label_date) or datetime.min.replace(tzinfo=timezone.utc),
    )
    if not labeled:
        return None
    up = metrics.is_upvote(np.asarray([float(i.label) for i in labeled]))
    return {
        "coverage": _coverage(labeled),
        "label_origin": _label_origin(labeled, origins),
        "sources": _sources(labeled, up),
        "timing": _timing(labeled, up),
        "age_at_vote": _age_at_vote(labeled, up),
        "similar_votes": _similar_votes(labeled, up),
    }
