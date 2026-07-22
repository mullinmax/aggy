"""Explain why the recommendation model scored a single article the way it did.

The prediction models are opaque (a kNN vote, a ridge regression, a small net),
so instead of reading their internals we probe them: hold the article fixed and,
one field at a time, swap that field for many random/average values drawn from
the rest of the feed. If the article's real value scores higher than those
substitutes, that field is *pushing the recommendation up*; if lower, it's
*dragging it down*. The size of the gap becomes 0, 1, or 2 marks.

The same swap also yields concrete evidence: substituting *one real article's*
value at a time tells us which of the other posts' images/text/sources the model
would have scored higher or lower than this one's. Those become the "scored
better / scored worse" examples the UI shows when a field is tapped, so the
opaque marks are backed by articles the user can actually look at.

This is a per-instance permutation importance, computed on demand (it retrains
the winning model on the feed's votes), because users look at it rarely.
"""

import random
from dataclasses import dataclass, replace
from typing import Dict, List, Optional

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

# How many "scored better" / "scored worse" example articles to surface per
# field, and the smallest score gap that counts as a real difference.
_EXAMPLES_PER_SIDE = 3
_EXAMPLE_EPS = 1e-3

# Fields the model actually consumes, in display order. Each entry is
# (field id, label, ItemFeatures attribute perturbed, what-is-scored blurb).
# "content" is the text embedding, generated from title + body together; the
# image/media fields are currently presence flags (a real thumbnail embedding
# slots into the same probe once image embeddings are ingested).
_FIELDS = [
    (
        "content",
        "Content",
        "embedding",
        "The article's title and body text, turned into an embedding and "
        "compared against the posts you've voted on.",
    ),
    (
        "source",
        "Source",
        "source",
        "Which source or subreddit the article came from.",
    ),
    (
        "author",
        "Author",
        "author",
        "Who wrote or posted the article.",
    ),
    (
        "recency",
        "Recency",
        "date_published",
        "How recently the article was published.",
    ),
    (
        "image",
        "Image",
        "has_image",
        "Whether the article carries a preview image.",
    ),
    (
        "media",
        "Media",
        "has_media",
        "Whether the article has playable video or audio attached.",
    ),
]

# Fields whose swap value is a distinct per-item quantity (an embedding, a
# timestamp): every article is its own example. The rest (source/author/flags)
# repeat across items, so examples are de-duplicated by the value itself.
_PER_ITEM_FIELDS = {"embedding", "image_embedding", "date_published"}


@dataclass
class FieldExample:
    """One article whose value for a field the model scored differently from
    the target's, used as concrete evidence behind the marks."""

    url_hash: str
    title: Optional[str]
    image_url: Optional[str]
    source: Optional[str]
    excerpt: Optional[str]
    # substitute score minus baseline: >0 the model likes this value more than
    # the article's own, <0 less.
    delta: float


@dataclass
class FieldContribution:
    field: str
    label: str
    # -1 dragging the score down, 0 no measurable effect, +1 pushing it up
    sign: int
    # 0, 1, or 2 marks
    level: int
    delta: float
    # what this field feeds the model, in one sentence
    description: str
    # other articles whose value the model scored higher / lower than this one's
    better: List[FieldExample]
    worse: List[FieldExample]


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


# Display metadata for the example cards; the ML features don't carry titles or
# image URLs, so we pull them separately keyed by url_hash.
_DISPLAY_META_SQL = (
    "SELECT i.url_hash, i.title, i.image_url, i.excerpt, ("
    " SELECT s.name FROM source_items si"
    " JOIN sources s ON s.user_hash = si.user_hash"
    "  AND s.feed_hash = si.feed_hash AND s.name_hash = si.source_hash"
    " WHERE si.user_hash = c.user_hash AND si.feed_hash = c.feed_hash"
    "  AND si.item_url_hash = c.item_url_hash LIMIT 1) AS source_name "
    "FROM feed_items c "
    "JOIN items i ON i.url_hash = c.item_url_hash "
    "WHERE c.user_hash = %s AND c.feed_hash = %s"
)


def _load_display_meta(feed: Feed) -> Dict[str, dict]:
    with get_db_con() as cur:
        cur.execute(_DISPLAY_META_SQL, (feed.user_hash, feed.name_hash))
        return {row["url_hash"]: row for row in cur.fetchall()}


def _field_examples(
    model,
    target: ItemFeatures,
    features: List[ItemFeatures],
    attr: str,
    baseline: float,
    meta: Dict[str, dict],
) -> tuple:
    """Score the target with every other article's value for `attr` swapped in,
    then return the articles that scored best and worst versus the baseline.

    This is the same permutation probe used for the marks, but keeping each
    real article attached so the UI can show the actual images/text the model
    was effectively weighing when it decided this field helps or hurts."""
    others = [f for f in features if f.url_hash != target.url_hash]
    if not others:
        return [], []
    variations = [replace(target, **{attr: getattr(f, attr)}) for f in others]
    scores, _ = model.predict(variations)

    seen = set()
    entries = []
    for f, score in zip(others, scores):
        key = f.url_hash if attr in _PER_ITEM_FIELDS else getattr(f, attr)
        if key in seen:
            continue
        seen.add(key)
        row = meta.get(f.url_hash, {})
        entries.append(
            FieldExample(
                url_hash=f.url_hash,
                title=row.get("title"),
                image_url=row.get("image_url"),
                source=row.get("source_name"),
                excerpt=row.get("excerpt"),
                delta=float(score) - baseline,
            )
        )

    entries.sort(key=lambda e: e.delta, reverse=True)
    better = [e for e in entries if e.delta > _EXAMPLE_EPS][:_EXAMPLES_PER_SIDE]
    worse = [e for e in entries if e.delta < -_EXAMPLE_EPS][-_EXAMPLES_PER_SIDE:]
    worse.reverse()  # most-negative first, mirroring `better`
    return better, worse


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
    meta = _load_display_meta(feed)

    rng = random.Random(seed)
    contributions: List[FieldContribution] = []
    for field, label, attr, description in _FIELDS:
        population = [getattr(f, attr) for f in features]
        variations = [
            replace(target, **{attr: rng.choice(population)}) for _ in range(samples)
        ]
        substitute_scores, _ = model.predict(variations)
        delta = baseline - float(np.mean(substitute_scores))
        sign, level = _marks(delta)
        better, worse = _field_examples(
            model, target, features, attr, baseline, meta
        )
        contributions.append(
            FieldContribution(
                field=field,
                label=label,
                sign=sign,
                level=level,
                delta=delta,
                description=description,
                better=better,
                worse=worse,
            )
        )

    return ItemExplanation(
        model_name=model.name, baseline_score=baseline, fields=contributions
    )
