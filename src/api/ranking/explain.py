"""Explain why the recommendation model scored a single article the way it did.

The prediction models are opaque (a kNN vote, a ridge regression, a small net),
so instead of reading their internals we ablate them: hold the article fixed
and, one field at a time, blank that field out (null the embedding, drop the
source, forget the date …) and re-score. If removing a field lowers the score,
that field was *pushing the recommendation up*; if the score rises without it,
the field was *dragging it down*. The size of the change becomes 0, 1, or 2
marks.

That's one evaluation per field against the article's own real data — cheap,
and it measures each field's actual contribution rather than how it compares to
random substitutes. Tapping a field also shows a preview of exactly what was
being evaluated for it (this article's text, its thumbnail, its source, …).

Computed on demand (it retrains the winning model on the feed's votes), because
users look at it rarely.
"""

import re
from dataclasses import dataclass, replace
from datetime import datetime
from typing import List, Optional

from db.base import get_db_con
from db.feed import Feed
from .engine import MIN_LABELS_TO_RANK, load_feed_features
from .models import ItemFeatures, all_models, evaluate_models

# Marks rank the fields against each other rather than against a fixed Δ scale,
# so one field can't run away with a huge number while the rest read as nothing.
# A field counts as "used" once blanking it moves the predicted score (in
# [-1, 1]) by at least this much; below it the model effectively ignored the
# field and it reads as no-effect (·).
_USED_FLOOR = 0.01
# Among the used fields, one whose effect is this many times the median used
# field's stands out and earns two marks; the rest get one. So a field that
# genuinely mattered almost always shows at least one mark, and two marks are
# reserved for a real standout.
_STRONG_MULTIPLE = 1.3

# Fields the model consumes, in display order. Each is scored by blanking it out
# and re-evaluating, so text and image are measured independently. Entries are:
#   (field id, label, {attr: null-value to blank}, what-is-scored blurb)
# The image field blanks both its embedding and the has-image flag, so the whole
# picture is removed rather than half of it.
_FIELDS = [
    (
        "text",
        "Text",
        {"embedding": None},
        "The article's title and body text, embedded and compared against the "
        "posts you've voted on — the image is scored separately.",
    ),
    (
        "image",
        "Image",
        {"image_embedding": None, "has_image": False},
        "The preview image — its embedding when a vision model is configured, "
        "otherwise just whether one is present.",
    ),
    (
        "source",
        "Source",
        {"source": None},
        "The source or subreddit the article came from.",
    ),
    (
        "author",
        "Author",
        {"author": None},
        "Who wrote or posted the article.",
    ),
    (
        "recency",
        "Recency",
        {"date_published": None},
        "How recently the article was published.",
    ),
    (
        "media",
        "Media",
        {"has_media": False},
        "Whether the article has playable video or audio attached.",
    ),
]


@dataclass
class FieldPreview:
    """A preview of exactly what this article contributed to the field being
    scored — the real data the ablation blanked out. The UI shows only the one
    piece relevant to the field (its text, its thumbnail, its source, …)."""

    text: Optional[str]
    image_url: Optional[str]
    source: Optional[str]
    author: Optional[str]
    date_published: Optional[datetime]
    has_image: bool
    has_media: bool
    # True when this article's image is scored by a real vision embedding, not
    # just the has-image presence flag.
    image_embedded: bool


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
    # this article's own value for the field, so you can see what was evaluated
    preview: FieldPreview


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


def _assign_marks(deltas: List[float]) -> List[tuple]:
    """Turn the fields' raw Δs into (sign, level) marks, normalized across the
    fields so the display always reads sensibly:

    - a field's *level* (0/1/2) is judged relative to the other fields, not on
      an absolute Δ. Every field the model actually used (Δ over the floor) gets
      at least one mark, and a mark of two is reserved for a field whose effect
      clearly stands out from the median — so it's unusual for a used field to
      read as nothing, and unusual for one field to hog a huge number;
    - a field's *sign* is the direction of its own Δ (removing it lowered the
      score → it was helping → +; removing it raised the score → −).

    Because a positive article's helpful fields carry the signal, its marks skew
    +; a neutral article's signal is split, so its marks come out roughly
    balanced."""
    magnitudes = [abs(d) for d in deltas]
    used = sorted(m for m in magnitudes if m >= _USED_FLOOR)
    if used:
        mid = len(used) // 2
        median = (
            used[mid] if len(used) % 2 else (used[mid - 1] + used[mid]) / 2.0
        )
    else:
        median = 0.0

    marks = []
    for delta, magnitude in zip(deltas, magnitudes):
        if magnitude < _USED_FLOOR:
            level = 0
        elif magnitude >= _STRONG_MULTIPLE * median:
            level = 2
        else:
            level = 1
        sign = 0 if level == 0 else (1 if delta > 0 else -1)
        marks.append((sign, level))
    return marks


# Display data for the field previews; the ML features don't carry the title,
# image URL or body text, so we pull them for the one item being explained.
_ITEM_DISPLAY_SQL = (
    "SELECT i.title, i.image_url, i.excerpt, i.content, ("
    " SELECT s.name FROM source_items si"
    " JOIN sources s ON s.user_hash = si.user_hash"
    "  AND s.feed_hash = si.feed_hash AND s.name_hash = si.source_hash"
    " WHERE si.user_hash = c.user_hash AND si.feed_hash = c.feed_hash"
    "  AND si.item_url_hash = c.item_url_hash LIMIT 1) AS source_name "
    "FROM feed_items c "
    "JOIN items i ON i.url_hash = c.item_url_hash "
    "WHERE c.user_hash = %s AND c.feed_hash = %s AND c.item_url_hash = %s"
)

_TAG_RE = re.compile(r"<[^>]+>")


def _load_item_display(feed: Feed, url_hash: str) -> dict:
    with get_db_con() as cur:
        cur.execute(_ITEM_DISPLAY_SQL, (feed.user_hash, feed.name_hash, url_hash))
        return cur.fetchone() or {}


def _preview_text(row: dict) -> Optional[str]:
    """Title plus a body snippet, mirroring what's embedded for the text field
    (the embedding covers the title *and* the article content, not just the
    headline). Body prefers the clean excerpt, falling back to tag-stripped
    content."""
    title = row.get("title")
    body = row.get("excerpt")
    if not body and row.get("content"):
        body = _TAG_RE.sub(" ", row["content"])
        body = " ".join(body.split())[:500]
    return "\n\n".join(part for part in (title, body) if part) or None


def explain_item(
    feed: Feed, item_url_hash: str
) -> Optional[ItemExplanation]:
    """Return a per-field breakdown of what drives this item's predicted score,
    or None when the feed has too few votes / the item isn't in the feed.

    Each field is scored by blanking it out on the article and re-evaluating:
    the drop (or rise) versus the full-article baseline is its contribution."""
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

    # score the article as-of now (not vote time)
    target = replace(target, label_date=None)
    baseline = float(model.predict([target])[0][0])

    row = _load_item_display(feed, item_url_hash)
    preview = FieldPreview(
        text=_preview_text(row),
        image_url=row.get("image_url"),
        source=row.get("source_name") or target.source,
        author=target.author,
        date_published=target.date_published,
        has_image=target.has_image,
        has_media=target.has_media,
        image_embedded=target.image_embedding is not None,
    )

    # Score every single-field ablation first, then assign marks from the whole
    # set so they're normalized against each other (see _assign_marks).
    deltas = []
    for _field, _label, null_map, _description in _FIELDS:
        ablated = replace(target, **null_map)
        score = float(model.predict([ablated])[0][0])
        # removing a helpful field lowers the score, so baseline - score > 0
        deltas.append(baseline - score)

    marks = _assign_marks(deltas)
    contributions = [
        FieldContribution(
            field=field,
            label=label,
            sign=sign,
            level=level,
            delta=delta,
            description=description,
            preview=preview,
        )
        for (field, label, _null_map, description), delta, (sign, level) in zip(
            _FIELDS, deltas, marks
        )
    ]

    return ItemExplanation(
        model_name=model.name, baseline_score=baseline, fields=contributions
    )
