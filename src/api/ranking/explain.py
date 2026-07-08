"""Explain why the recommendation model scored a single article the way it did.

The prediction models are opaque (a kNN vote, a ridge regression, a small net),
so instead of reading their internals we probe them: hold the article fixed and,
one field at a time, swap that field for many random/average values drawn from
the rest of the feed. If the article's real value scores higher than those
substitutes, that field is *pushing the recommendation up*; if lower, it's
*dragging it down*. The size of the gap becomes 0, 1, or 2 marks.

This is a per-instance permutation importance, computed on demand (it retrains
the winning model on the feed's votes), because users look at it rarely.
"""

import random
from dataclasses import dataclass, replace
from typing import List, Optional

import numpy as np

from db.base import get_db_con
from db.feed import Feed
from .engine import MIN_LABELS_TO_RANK, load_feed_features
from .models import ItemFeatures, all_models, evaluate_models

# How many substitute values to try per field. Enough to average out the
# noise of random draws without making the on-demand call slow.
_SAMPLES = 40

# |Δ score| thresholds for 0 / 1 / 2 marks. Predicted scores live in [-1, 1].
_LEVEL1 = 0.04
_LEVEL2 = 0.12

# Fields the model actually consumes, in display order, mapped to the
# ItemFeatures attribute each one perturbs. "content" is the text embedding,
# which is generated from the article's title + body together.
_FIELDS = [
    ("content", "Content", "embedding"),
    ("source", "Source", "source"),
    ("author", "Author", "author"),
    ("recency", "Recency", "date_published"),
    ("image", "Image", "has_image"),
    ("media", "Media", "has_media"),
]


@dataclass
class FieldContribution:
    field: str
    label: str
    # -1 dragging the score down, 0 no measurable effect, +1 pushing it up
    sign: int
    # 0, 1, or 2 marks
    level: int
    delta: float


@dataclass
class ItemExplanation:
    model_name: str
    baseline_score: float
    fields: List[FieldContribution]


def _winner_model(feed: Feed, labeled: List[ItemFeatures]):
    """The model currently ranking this feed, so the explanation matches the
    score the user sees. Prefer the persisted choice; fall back to evaluating."""
    chosen = None
    with get_db_con() as cur:
        cur.execute(
            "SELECT model_name FROM ranking_model_stats "
            "WHERE user_hash = %s AND feed_hash = %s AND chosen = TRUE LIMIT 1",
            (feed.user_hash, feed.name_hash),
        )
        row = cur.fetchone()
        if row:
            chosen = row["model_name"]
    if chosen is None:
        stats = evaluate_models(labeled)
        chosen = next((s.model_name for s in stats if s.chosen), None)
    if chosen is None:
        return None
    return next((m for m in all_models() if m.name == chosen), None)


def _marks(delta: float):
    magnitude = abs(delta)
    if magnitude >= _LEVEL2:
        level = 2
    elif magnitude >= _LEVEL1:
        level = 1
    else:
        level = 0
    sign = 0 if level == 0 else (1 if delta > 0 else -1)
    return sign, level


def explain_item(
    feed: Feed, item_url_hash: str, samples: int = _SAMPLES, seed: int = 0
) -> Optional[ItemExplanation]:
    """Return a per-field breakdown of what drives this item's predicted score,
    or None when the feed has too few votes / the item isn't in the feed."""
    features = load_feed_features(feed)
    labeled = [f for f in features if f.label is not None]
    if len(labeled) < MIN_LABELS_TO_RANK:
        return None

    target = next((f for f in features if f.url_hash == item_url_hash), None)
    if target is None:
        return None

    model = _winner_model(feed, labeled)
    if model is None:
        return None
    model.fit(labeled)

    # score the article and its substitutes as-of now (not vote time)
    target = replace(target, label_date=None)
    baseline = float(model.predict([target])[0][0])

    rng = random.Random(seed)
    contributions: List[FieldContribution] = []
    for field, label, attr in _FIELDS:
        population = [getattr(f, attr) for f in features]
        variations = [
            replace(target, **{attr: rng.choice(population)}) for _ in range(samples)
        ]
        substitute_scores, _ = model.predict(variations)
        delta = baseline - float(np.mean(substitute_scores))
        sign, level = _marks(delta)
        contributions.append(
            FieldContribution(
                field=field, label=label, sign=sign, level=level, delta=delta
            )
        )

    return ItemExplanation(
        model_name=model.name, baseline_score=baseline, fields=contributions
    )
