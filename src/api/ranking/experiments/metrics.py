"""Scores for one block of predictions.

Everything here answers a version of one question: had the feed been sorted by
these predictions, would the articles you went on to upvote have been on top?

A block is a run of consecutive votes that a method predicted without having
seen any of them. Ranking metrics are computed inside a block and never across
blocks: each block comes from a separate fit, and nothing makes one fit's 0.3
comparable to another's.
"""

from typing import Optional

import numpy as np

# How the UI already splits a predicted score into "upvote / neutral /
# downvote" bands (see predictionBand in app.js); the three-way accuracy uses
# the same lines so it measures the labels the feed would actually show.
BAND_EDGE = 0.5


def is_upvote(labels: np.ndarray) -> np.ndarray:
    return np.asarray(labels, dtype=float) > 0


def auc(scores: np.ndarray, labels: np.ndarray) -> Optional[float]:
    """Chance that an upvoted article outranks one that was not upvoted.

    Ties count half, so a method that gives every article the same score lands
    on exactly 0.5 rather than on whatever order the rows happened to be in.
    None when the block holds only upvotes or none at all: there is no pair to
    compare.
    """
    positive = is_upvote(labels)
    n_pos = int(positive.sum())
    n_neg = int(len(positive) - n_pos)
    if n_pos == 0 or n_neg == 0:
        return None
    scores = np.asarray(scores, dtype=float)
    order = np.argsort(scores, kind="mergesort")
    ranks = np.empty(len(scores))
    sorted_scores = scores[order]
    # average rank within each run of equal scores
    i = 0
    while i < len(scores):
        j = i
        while j + 1 < len(scores) and sorted_scores[j + 1] == sorted_scores[i]:
            j += 1
        ranks[order[i : j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    rank_sum = ranks[positive].sum()
    return float((rank_sum - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg))


def pair_count(labels: np.ndarray) -> int:
    positive = is_upvote(labels)
    return int(positive.sum()) * int(len(positive) - positive.sum())


def _ranking(scores: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Indices best first, with ties broken at random.

    Without the shuffle a constant predictor would be scored on the order the
    votes were cast in, which is not a prediction it made.
    """
    scores = np.asarray(scores, dtype=float)
    shuffled = rng.permutation(len(scores))
    return shuffled[np.argsort(-scores[shuffled], kind="mergesort")]


def top_k_hit_rate(scores, labels, k: int, rng: np.random.Generator) -> float:
    """Share of the k highest-ranked articles that were upvoted."""
    top = _ranking(scores, rng)[: min(k, len(scores))]
    return float(is_upvote(labels)[top].mean())


def ndcg(scores, labels, k: int, rng: np.random.Generator) -> Optional[float]:
    """Graded ranking quality over the top k: an upvote is worth 2, a neutral
    1 and a downvote 0, discounted by position. Unlike the hit rate this gives
    credit for putting a "meh" above a downvote. None when every article in the
    block has the same grade, since then every order is equally good."""
    gains = np.clip(np.asarray(labels, dtype=float) + 1.0, 0.0, 2.0)
    if np.allclose(gains, gains[0]):
        return None
    k = min(k, len(gains))
    discounts = 1.0 / np.log2(np.arange(2, k + 2))
    got = float((gains[_ranking(scores, rng)[:k]] * discounts).sum())
    best = float((np.sort(gains)[::-1][:k] * discounts).sum())
    return got / best if best > 0 else None


def _band(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    return np.where(values >= BAND_EDGE, 1, np.where(values <= -BAND_EDGE, -1, 0))


def three_way_accuracy(scores, labels) -> float:
    """How often the predicted band (up / neutral / down) is the vote cast."""
    return float(np.mean(_band(scores) == _band(labels)))


def mae(scores, labels) -> float:
    return float(np.mean(np.abs(np.asarray(scores) - np.asarray(labels))))
