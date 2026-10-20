"""A model that decides whether two articles are the same story.

Detection's content signal has one number behind it: the cosine between two
text embeddings, against a constant threshold. That constant is doing a lot of
work it cannot really do. Two write-ups of the same press release and two
columns about the same election are both "very similar text", and no single
cutoff separates them -- what separates them is everything *around* the text:
whether they came out hours or weeks apart, whether one outlet published both,
whether the headlines are the same headline reworded.

So once you have judged enough pairs (see ``dedup.labels``) those extra signals
get weighed against your answers rather than ignored, and the model's verdict
replaces the constant. Nothing else about grouping changes: candidates still
come from the neighbour walk, a new member still has to match the group's
representative, and the window and size backstops still apply. The model
decides one question -- is this pair the same story -- which is exactly the
question the constant was answering badly.

Deliberately a logistic regression over a handful of hand-built features
rather than anything larger. It has to be useful at a few dozen labels, which
is all anybody will sit and click through, and at that size a small model with
meaningful inputs beats a big one every time. Its coefficients are also worth
reading: they say which signals actually separated your answers.
"""

import math
from dataclasses import dataclass
from datetime import timezone
from typing import List, Optional, Sequence, Tuple
from urllib.parse import urlsplit

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from config import config
from db.base import get_db_con
from neighbors.search import parse_embedding, similarity

from .labels import labeled_pairs

_WORD_RE_SPLIT = " \t\n\r\f\v-_/|:;,.!?\"'()[]{}<>"


def _tokens(title: Optional[str]) -> frozenset:
    """A headline as a bag of words, lowercased and stripped of punctuation.

    Crude on purpose. The point is not to understand the headline but to
    notice that "Fed holds rates steady" and "Fed leaves rates unchanged"
    share more of it than two unrelated pieces do.
    """
    if not title:
        return frozenset()
    cleaned = title.lower()
    for ch in _WORD_RE_SPLIT:
        cleaned = cleaned.replace(ch, " ")
    return frozenset(word for word in cleaned.split() if len(word) > 2)


def _jaccard(left: frozenset, right: frozenset) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _host(url: Optional[str]) -> str:
    if not url:
        return ""
    try:
        return urlsplit(url).netloc.lower().removeprefix("www.")
    except ValueError:
        return ""


def _hours_apart(left, right) -> float:
    if left is None or right is None:
        return 0.0
    if left.tzinfo is None:
        left = left.replace(tzinfo=timezone.utc)
    if right.tzinfo is None:
        right = right.replace(tzinfo=timezone.utc)
    return abs((left - right).total_seconds()) / 3600.0


@dataclass(frozen=True)
class PairFeatures:
    """What the model is shown about one pair.

    Every field is symmetric in the two articles, because "is this the same
    story" cannot depend on which one was asked about first.
    """

    # The cosine detection used on its own. Still the strongest signal; the
    # rest are what tell a rewrite from a second piece on the same subject.
    text_similarity: float
    # Pictures are the giveaway on wire copy: the same photo on both. Zero
    # when either side has no image embedding, which the flag distinguishes
    # from a genuine zero.
    image_similarity: float
    both_images: float
    title_overlap: float
    # Log-scaled: the difference between one hour and six matters, the
    # difference between nine days and ten does not.
    log_hours_apart: float
    same_host: float
    same_author: float

    def as_row(self) -> List[float]:
        return [
            self.text_similarity,
            self.image_similarity,
            self.both_images,
            self.title_overlap,
            self.log_hours_apart,
            self.same_host,
            self.same_author,
        ]


FEATURE_NAMES = (
    "text similarity",
    "image similarity",
    "both have images",
    "headline overlap",
    "hours apart (log)",
    "same site",
    "same author",
)


def pair_features(
    left: dict, right: dict, text_similarity: Optional[float] = None
) -> PairFeatures:
    """Build a pair's features from two item rows.

    ``text_similarity`` is accepted ready-made because the detector already
    measured it during the walk and re-deriving it from the stored vectors
    would be the same number at a cost.
    """
    if text_similarity is None:
        text_similarity = (
            similarity(
                parse_embedding(left.get("embeddings")),
                parse_embedding(right.get("embeddings")),
            )
            or 0.0
        )

    left_image = parse_embedding(left.get("image_embeddings"))
    right_image = parse_embedding(right.get("image_embeddings"))
    both_images = left_image is not None and right_image is not None
    image_similarity = (
        (similarity(left_image, right_image) or 0.0) if both_images else 0.0
    )

    left_host = _host(left.get("url"))
    right_host = _host(right.get("url"))
    left_author = (left.get("author") or "").strip().lower()
    right_author = (right.get("author") or "").strip().lower()

    return PairFeatures(
        text_similarity=float(text_similarity),
        image_similarity=float(image_similarity),
        both_images=1.0 if both_images else 0.0,
        title_overlap=_jaccard(_tokens(left.get("title")), _tokens(right.get("title"))),
        log_hours_apart=math.log1p(
            _hours_apart(left.get("published"), right.get("published"))
        ),
        same_host=1.0 if left_host and left_host == right_host else 0.0,
        same_author=1.0 if left_author and left_author == right_author else 0.0,
    )


def features_from_label_row(row: dict) -> PairFeatures:
    """The same features, from a row of ``labeled_pairs``.

    That query names its columns per side, so this is only the unpacking.
    """
    left = {
        "title": row.get("left_title"),
        "url": row.get("left_url"),
        "author": row.get("left_author"),
        "published": row.get("left_published"),
        "embeddings": row.get("left_embeddings"),
        "image_embeddings": row.get("left_image_embeddings"),
    }
    right = {
        "title": row.get("right_title"),
        "url": row.get("right_url"),
        "author": row.get("right_author"),
        "published": row.get("right_published"),
        "embeddings": row.get("right_embeddings"),
        "image_embeddings": row.get("right_image_embeddings"),
    }
    return pair_features(left, right)


@dataclass
class ModelReport:
    """How well the model does on your labels, for the review page to show.

    ``accuracy`` is cross-validated rather than measured on the labels it was
    fitted to, which at a few dozen rows would read near-perfect and mean
    nothing. It is None when there are too few of either answer to hold a fold
    out honestly.
    """

    confirmed: int
    rejected: int
    accuracy: Optional[float]
    coefficients: Tuple[Tuple[str, float], ...]


class DuplicateModel:
    """Fitted on your labels; answers how likely a pair is the same story."""

    def __init__(self, estimator, report: ModelReport):
        self.estimator = estimator
        self.report = report

    def probability(self, features: PairFeatures) -> float:
        row = np.asarray([features.as_row()], dtype=float)
        return float(self.estimator.predict_proba(row)[0][1])


def _cross_validated_accuracy(X, y) -> Optional[float]:
    """Accuracy over held-out folds, or None when the labels cannot support it.

    Needs at least two folds' worth of each answer. Below that the honest
    report is that there is not enough to say, rather than a number computed
    on two rows.
    """
    counts = np.bincount(y.astype(int), minlength=2)
    folds = int(min(5, counts.min()))
    if folds < 2:
        return None
    scores = cross_val_score(
        _build_estimator(),
        X,
        y,
        cv=StratifiedKFold(n_splits=folds, shuffle=True, random_state=0),
        scoring="accuracy",
    )
    return float(scores.mean())


def _build_estimator():
    # Balanced because the two answers arrive in whatever proportion your
    # articles happen to produce, and a set that is mostly confirmations
    # should not teach the model that saying yes is usually safe.
    return make_pipeline(
        StandardScaler(),
        LogisticRegression(max_iter=1000, class_weight="balanced"),
    )


def train(rows: Sequence[dict]) -> Optional[DuplicateModel]:
    """Fit on your labelled pairs, or return None when they cannot support a
    model: too few, or all of them the same answer.

    Returning None is not a failure -- it is the normal state of a new install,
    and detection simply keeps using the hand-picked threshold until there is
    something better to use.
    """
    minimum = config.get_int("DUPLICATE_MODEL_MIN_LABELS")
    if len(rows) < minimum:
        return None

    y = np.asarray([1 if row["is_duplicate"] else 0 for row in rows], dtype=float)
    if len(set(y.tolist())) < 2:
        return None

    X = np.asarray([features_from_label_row(row).as_row() for row in rows], dtype=float)
    accuracy = _cross_validated_accuracy(X, y)

    estimator = _build_estimator()
    estimator.fit(X, y)

    # Read off the scaled coefficients, so the page can say which signals
    # actually separated the answers rather than only that a model exists.
    weights = estimator[-1].coef_[0]
    return DuplicateModel(
        estimator,
        ModelReport(
            confirmed=int(y.sum()),
            rejected=int(len(y) - y.sum()),
            accuracy=accuracy,
            coefficients=tuple(
                sorted(
                    zip(FEATURE_NAMES, (float(w) for w in weights)),
                    key=lambda pair: abs(pair[1]),
                    reverse=True,
                )
            ),
        ),
    )


# Fitting is cheap but not free, and an examination pass asks for the model
# once per article. The cache is keyed on the labels themselves -- how many
# there are and when the newest was written -- rather than invalidated by
# hand, so a label written by the API process is picked up by the pass whether
# or not they are the same process.
_cached: dict = {}


def _label_version(user_hash: str) -> tuple:
    with get_db_con() as cur:
        cur.execute(
            "SELECT COUNT(*) AS n, MAX(labeled_at) AS newest "
            "FROM duplicate_labels WHERE user_hash = %s",
            (user_hash,),
        )
        row = cur.fetchone() or {}
    return (int(row.get("n") or 0), row.get("newest"))


def model_for(user_hash: str) -> Optional[DuplicateModel]:
    """This account's duplicate model, or None while the constant still
    decides. Refits only when the labels have changed."""
    version = _label_version(user_hash)
    if version[0] == 0:
        _cached.pop(user_hash, None)
        return None

    cached = _cached.get(user_hash)
    if cached is not None and cached[0] == version:
        return cached[1]

    model = train(labeled_pairs(user_hash))
    _cached[user_hash] = (version, model)
    return model
