"""Train/evaluate vote-prediction models for a feed and cache predictions.

`rank_feed` is the entry point: it cross-validates every model on the feed's
votes, persists the per-model stats (for the stats UI), then trains the best
model on all labels and writes a predicted score + confidence to every item
in the feed. `feed/items` sorts read straight from those cached columns.
"""

import json
import logging
from typing import List, Optional

import numpy as np

from db.base import get_db_con
from db.feed import Feed
from utils import is_playable_media_url
from . import progress
from .models import (
    ItemFeatures,
    ModelStats,
    all_models,
    evaluate_models,
)

MIN_LABELS_TO_RANK = 3


def _parse_embedding(embeddings) -> Optional[np.ndarray]:
    """items.embeddings is a JSONB dict of {model_name: vector}; use the
    first vector present (only one embedding model runs per deployment)."""
    if not embeddings:
        return None
    if isinstance(embeddings, str):
        try:
            embeddings = json.loads(embeddings)
        except (TypeError, ValueError):
            return None
    for vector in embeddings.values():
        if vector:
            return np.asarray(vector, dtype=float)
    return None


def _effective_label(vote, list_added_at):
    """Fold list membership into the training label.

    Adding an item to a list counts as an extra positive vote: it lifts the
    label by one upvote (clamped to the +1..-1 vote scale). An unvoted but
    listed item therefore reads as an upvote; a downvoted-but-listed one lands
    back at neutral.
    """
    if list_added_at is None:
        return vote
    base = 0.0 if vote is None else float(vote)
    return max(-1.0, min(1.0, base + 1.0))


def _row_to_features(row) -> ItemFeatures:
    media = row.get("media")
    if isinstance(media, str):
        try:
            media = json.loads(media)
        except (TypeError, ValueError):
            media = None
    list_added_at = row.get("list_added_at")
    # YouTube links and direct video files play inline in the UI without a
    # stored media entry, so count them as media for scoring too.
    has_media = bool(media) or is_playable_media_url(row.get("url"))
    return ItemFeatures(
        url_hash=row["url_hash"],
        embedding=_parse_embedding(row.get("embeddings")),
        image_embedding=_parse_embedding(row.get("image_embeddings")),
        source=row.get("source_name"),
        author=row.get("author"),
        date_published=row.get("date_published"),
        has_image=bool(row.get("image_url")),
        has_media=has_media,
        label=_effective_label(row.get("vote"), list_added_at),
        # an unvoted-but-listed item is labelled as of when it was listed
        label_date=row.get("vote_date") or list_added_at,
    )


# Votes are shared across feeds: the label for an item comes from the user's
# latest vote on it in *any* feed (the user_item_votes view), not just this
# feed. So an upvote cast in one feed trains every feed the item appears in.
_FEED_ITEMS_SQL = (
    "SELECT i.url_hash, i.url, i.author, i.date_published, i.image_url, i.media, "
    "i.embeddings, i.image_embeddings, v.score AS vote, v.score_date AS vote_date, ("
    " SELECT s.name FROM source_items si"
    " JOIN sources s ON s.user_hash = si.user_hash"
    "  AND s.feed_hash = si.feed_hash AND s.name_hash = si.source_hash"
    " WHERE si.user_hash = c.user_hash AND si.feed_hash = c.feed_hash"
    "  AND si.item_url_hash = c.item_url_hash LIMIT 1) AS source_name, ("
    # earliest time this item was added to any of the user's lists; a listed
    # item counts as an extra positive vote (see _effective_label)
    " SELECT MIN(li.added_at) FROM list_items li"
    " WHERE li.user_hash = c.user_hash"
    "  AND li.item_url_hash = c.item_url_hash) AS list_added_at "
    "FROM feed_items c "
    "JOIN items i ON i.url_hash = c.item_url_hash "
    "LEFT JOIN user_item_votes v ON v.user_hash = c.user_hash "
    " AND v.item_url_hash = c.item_url_hash "
    "WHERE c.user_hash = %s AND c.feed_hash = %s"
)


def load_feed_features(feed: Feed) -> List[ItemFeatures]:
    with get_db_con() as cur:
        cur.execute(_FEED_ITEMS_SQL, (feed.user_hash, feed.name_hash))
        rows = cur.fetchall()
    return [_row_to_features(row) for row in rows]


def save_model_stats(feed: Feed, stats: List[ModelStats]) -> None:
    with get_db_con() as cur:
        for s in stats:
            cur.execute(
                "INSERT INTO ranking_model_stats (user_hash, feed_hash, "
                "model_name, n_labels, mae, rmse, sign_accuracy, chosen, "
                "computed_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW()) "
                "ON CONFLICT (user_hash, feed_hash, model_name) DO UPDATE SET "
                "n_labels = EXCLUDED.n_labels, mae = EXCLUDED.mae, "
                "rmse = EXCLUDED.rmse, sign_accuracy = EXCLUDED.sign_accuracy, "
                "chosen = EXCLUDED.chosen, computed_at = EXCLUDED.computed_at",
                (
                    feed.user_hash,
                    feed.name_hash,
                    s.model_name,
                    s.n_labels,
                    s.mae,
                    s.rmse,
                    s.sign_accuracy,
                    s.chosen,
                ),
            )


def load_model_stats(feed: Feed) -> List[dict]:
    with get_db_con() as cur:
        cur.execute(
            "SELECT model_name, n_labels, mae, rmse, sign_accuracy, chosen, "
            "computed_at FROM ranking_model_stats "
            "WHERE user_hash = %s AND feed_hash = %s ORDER BY mae ASC NULLS LAST",
            (feed.user_hash, feed.name_hash),
        )
        return cur.fetchall()


def training_summary(feed: Feed) -> dict:
    """When this feed's models were last trained, on how many votes, with
    which model — and how many votes have been cast since.

    A count above zero means the live predictions are behind the user's
    votes; the scheduled ranking job picks that up on its next pass, and the
    stats UI shows it so a retrain is an informed choice rather than a guess.
    """
    with get_db_con() as cur:
        cur.execute(
            "SELECT MAX(computed_at) AS last_trained_at, MAX(n_labels) AS n_labels, "
            "MAX(model_name) FILTER (WHERE chosen) AS chosen_model "
            "FROM ranking_model_stats WHERE user_hash = %s AND feed_hash = %s",
            (feed.user_hash, feed.name_hash),
        )
        row = cur.fetchone() or {}
        last_trained_at = row.get("last_trained_at")
        # Shared votes again: a vote cast on this item in another feed trains
        # this one too, so it counts as new here as well.
        cur.execute(
            "SELECT COUNT(*) AS n FROM feed_items c "
            "JOIN user_item_votes v ON v.user_hash = c.user_hash "
            " AND v.item_url_hash = c.item_url_hash "
            "WHERE c.user_hash = %s AND c.feed_hash = %s "
            "AND (%s::timestamptz IS NULL OR v.score_date > %s::timestamptz)",
            (feed.user_hash, feed.name_hash, last_trained_at, last_trained_at),
        )
        votes_since = cur.fetchone()["n"]
    return {
        "last_trained_at": last_trained_at,
        "trained_model": row.get("chosen_model"),
        "trained_labels": row.get("n_labels") or 0,
        "votes_since_training": votes_since,
    }


def _write_predictions(
    feed: Feed, items: List[ItemFeatures], scores, confs, model_name: str
) -> None:
    with get_db_con() as cur:
        for item, score, conf in zip(items, scores, confs):
            cur.execute(
                "UPDATE feed_items SET predicted_score = %s, "
                "predicted_confidence = %s, predicted_model = %s, "
                "predicted_at = NOW() "
                "WHERE user_hash = %s AND feed_hash = %s AND item_url_hash = %s",
                (
                    float(score),
                    float(conf),
                    model_name,
                    feed.user_hash,
                    feed.name_hash,
                    item.url_hash,
                ),
            )


def training_steps() -> int:
    """Steps a full training run reports: one per model evaluated, plus
    fitting the winner and writing its predictions."""
    return len(all_models()) + 2


def rank_feed(feed: Feed) -> List[ModelStats]:
    """Evaluate all models on this feed's votes, persist their stats, then
    predict a vote for every item with the winner. Returns the stats.

    Progress is reported to `ranking.progress` as it goes; that is a no-op
    unless a run was registered for this feed (see `train_feed`), so calling
    this directly stays a plain synchronous operation.
    """
    features = load_feed_features(feed)
    labeled = [f for f in features if f.label is not None]

    def report_model(index: int, total: int, model_name: str) -> None:
        progress.update(
            feed.user_hash,
            feed.name_hash,
            step=index,
            phase=progress.PHASE_EVALUATING,
            model_name=model_name,
        )

    stats = evaluate_models(labeled, on_model=report_model)
    save_model_stats(feed, stats)

    if len(labeled) < MIN_LABELS_TO_RANK:
        return stats

    winner_name = next((s.model_name for s in stats if s.chosen), None)
    if winner_name is None:
        return stats
    winner = next(m for m in all_models() if m.name == winner_name)

    progress.update(
        feed.user_hash,
        feed.name_hash,
        step=training_steps() - 2,
        phase=progress.PHASE_TRAINING,
        model_name=winner_name,
    )
    winner.fit(labeled)
    # candidate items get fresh predictions; labeled ones too, so the
    # "include read" view still sorts sensibly
    for f in features:
        f.label_date = None  # predict ages as-of now
    scores, confs = winner.predict(features)
    progress.update(
        feed.user_hash,
        feed.name_hash,
        step=training_steps() - 1,
        phase=progress.PHASE_PREDICTING,
        model_name=winner_name,
    )
    _write_predictions(feed, features, scores, confs, winner_name)
    logging.info(
        f"Ranked feed {feed.name} with model '{winner_name}' "
        f"({len(labeled)} labels, {len(features)} items)"
    )
    return stats


def start_training(feed: Feed) -> bool:
    """Claim this feed for a training run, so the UI can show it as running
    the moment it is asked for. False when one is already in flight — a second
    click, or the scheduler reaching a feed the user just asked to retrain.

    The caller must then call `run_training`, on this thread or another.
    """
    return progress.start(feed.user_hash, feed.name_hash, training_steps())


def run_training(feed: Feed) -> List[ModelStats]:
    """Do the training claimed by `start_training`, reporting its progress."""
    try:
        stats = rank_feed(feed)
    except Exception as e:
        progress.finish(feed.user_hash, feed.name_hash, error=str(e))
        raise
    progress.finish(feed.user_hash, feed.name_hash)
    return stats


def train_feed(feed: Feed) -> Optional[List[ModelStats]]:
    """`rank_feed` with progress tracking, for anything the UI can watch.
    Returns None when a run for this feed is already in flight."""
    if not start_training(feed):
        return None
    return run_training(feed)


def feeds_needing_rank() -> List[Feed]:
    """Feeds with at least one label — an explicit vote or a listed item, since
    list membership counts as a vote — where a label or item is newer than the
    latest prediction (or no prediction exists yet).

    Votes are shared: a label counts if the user voted on an item *in this
    feed* from any feed (via user_item_votes), so voting in one feed schedules
    every feed the item appears in for re-ranking."""
    with get_db_con() as cur:
        cur.execute(
            "SELECT f.user_hash, f.name FROM feeds f WHERE ("
            " EXISTS (SELECT 1 FROM feed_items c"
            "  JOIN user_item_votes v ON v.user_hash = c.user_hash"
            "   AND v.item_url_hash = c.item_url_hash"
            "  WHERE c.user_hash = f.user_hash AND c.feed_hash = f.name_hash)"
            " OR EXISTS (SELECT 1 FROM feed_items c"
            "  JOIN list_items li ON li.user_hash = c.user_hash"
            "   AND li.item_url_hash = c.item_url_hash"
            "  WHERE c.user_hash = f.user_hash AND c.feed_hash = f.name_hash)"
            ") AND ("
            " EXISTS (SELECT 1 FROM feed_items c"
            "  WHERE c.user_hash = f.user_hash AND c.feed_hash = f.name_hash"
            "   AND c.predicted_at IS NULL)"
            " OR GREATEST("
            "  COALESCE((SELECT MAX(v.score_date) FROM feed_items c"
            "   JOIN user_item_votes v ON v.user_hash = c.user_hash"
            "    AND v.item_url_hash = c.item_url_hash"
            "   WHERE c.user_hash = f.user_hash AND c.feed_hash = f.name_hash),"
            "   'epoch'),"
            "  COALESCE((SELECT MAX(li.added_at) FROM feed_items c"
            "   JOIN list_items li ON li.user_hash = c.user_hash"
            "    AND li.item_url_hash = c.item_url_hash"
            "   WHERE c.user_hash = f.user_hash AND c.feed_hash = f.name_hash),"
            "   'epoch')"
            " ) > COALESCE((SELECT MAX(c.predicted_at) FROM feed_items c"
            "  WHERE c.user_hash = f.user_hash AND c.feed_hash = f.name_hash),"
            "  'epoch'))",
        )
        rows = cur.fetchall()
    return [Feed(user_hash=row["user_hash"], name=row["name"]) for row in rows]


def feed_ranking_job() -> None:
    """Scheduled job: re-rank every feed whose votes or items changed.

    Goes through `train_feed` so a scheduled retrain shows up in the UI's
    training progress exactly like one the user asked for.
    """
    for feed in feeds_needing_rank():
        try:
            train_feed(feed)
        except Exception as e:
            logging.exception(f"Ranking feed {feed.name} failed: {e}")


def label_counts(feed: Feed) -> dict:
    with get_db_con() as cur:
        # Shared votes: count each item in this feed the user has voted on in
        # any feed (one row per item via user_item_votes).
        cur.execute(
            "SELECT COUNT(*) FILTER (WHERE v.score > 0) AS up, "
            "COUNT(*) FILTER (WHERE v.score < 0) AS down, "
            "COUNT(*) FILTER (WHERE v.score = 0) AS neutral "
            "FROM feed_items c "
            "JOIN user_item_votes v ON v.user_hash = c.user_hash "
            " AND v.item_url_hash = c.item_url_hash "
            "WHERE c.user_hash = %s AND c.feed_hash = %s",
            (feed.user_hash, feed.name_hash),
        )
        counts = cur.fetchone()
        cur.execute(
            "SELECT COUNT(*) AS total, "
            "COUNT(*) FILTER (WHERE predicted_score IS NOT NULL) AS predicted "
            "FROM feed_items WHERE user_hash = %s AND feed_hash = %s",
            (feed.user_hash, feed.name_hash),
        )
        items = cur.fetchone()
    return {
        "up": counts["up"],
        "down": counts["down"],
        "neutral": counts["neutral"],
        "total_items": items["total"],
        "predicted_items": items["predicted"],
    }
