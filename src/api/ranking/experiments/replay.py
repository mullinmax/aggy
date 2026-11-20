"""Replay a feed's votes in the order they were cast.

The live bake-off (`ranking.models.evaluate_models`) scores a model on votes
held out at random, which lets it learn from votes cast *after* the one it is
predicting. The feed never has that luxury: it is always sorted by a model
that has only seen the past. So this replays history instead. The votes are
put in the order they were cast and cut into consecutive blocks; for each
block every method is fitted on everything before it and asked to rank the
block's articles, and it is scored on whether the ones that went on to be
upvoted came out on top.

Nothing here touches the database, so a planted-taste feed can be replayed in
a test and the harness itself checked: `runner` is what loads real votes and
stores the outcome.

What comes out is aggregate only. Scores, counts and timings per method; never
a title, a URL, a source name or a vector.
"""

import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional, Sequence

import numpy as np

from ranking.models import (
    DeepMLPModel,
    GlobalMeanModel,
    GradientBoostModel,
    ItemFeatures,
    KNNEmbeddingModel,
    LogisticVoteModel,
    MLPModel,
    RandomForestModel,
    RandomModel,
    RidgeModel,
    SourceMeanModel,
    LIVE_MODEL_LADDER,
    SVRModel,
    VoteModel,
    evaluate_models,
    live_model_name,
)

from . import metrics
from .methods import experiment_models

# Methods the harness builds out of the others' predictions.
LIVE_PICKER = "live_picker"
TIME_PICKER = "time_picker"
BLEND_TOP3 = "blend_top3"
BLEND_CORE = "blend_core"
LIVE_RULE = "live_rule"
BLEND_SVR_PRIOR = "blend_svr_prior"
BLEND_STRONG = "blend_strong"
COMBINED = (
    LIVE_PICKER,
    TIME_PICKER,
    BLEND_TOP3,
    BLEND_CORE,
    LIVE_RULE,
    BLEND_SVR_PRIOR,
    BLEND_STRONG,
)

# What every other method is compared against: the model the app's old rule
# (lowest error on randomly held-out votes) would have been ranking the feed
# with at that moment. The app now ranks with `live_rule`, which is replayed
# alongside so the switch itself is checked against what it replaced.
BASELINE = LIVE_PICKER

# Live models slow enough to leave out of a quick run.
_HEAVY_LIVE = {
    "random_forest",
    "gradient_boost",
    "neural_net",
    "deep_neural_net",
}

_BLEND_CORE_MEMBERS = ("knn_embedding", "logistic", "taste_profile", "source_prior_knn")
_BLEND_SVR_PRIOR_MEMBERS = ("svr", "source_prior_knn")
_BLEND_STRONG_MEMBERS = ("svr", "source_prior_knn", "random_forest")

# Training-set size bands a block is reported under, so the result shows
# which method suits a young feed and which a mature one.
SIZE_BANDS = (("under_50", 0, 50), ("50_to_199", 50, 200), ("200_plus", 200, None))

TOP_K = 5
NDCG_K = 10


class Cancelled(Exception):
    """The run was asked to stop."""


@dataclass
class ReplayConfig:
    # votes a feed must have before the first block: below this nothing can
    # be learned and every method would be scored on noise
    warmup: int = 10
    max_blocks: int = 12
    min_block: int = 5
    quick: bool = False
    # The live picker cross-validates the whole zoo, which costs more than
    # everything else in a block put together. Re-picking on every block would
    # be faithful (the app retrains whenever a vote lands) and far too slow, so
    # it re-picks every few blocks and keeps its choice in between.
    picker_every: int = 4
    # After each fit, idle for this fraction of the time the fit took. A
    # background experiment should leave the machine room to breathe.
    rest_fraction: float = 0.25
    max_rest_seconds: float = 5.0
    # an open only counts as "left unvoted" once this long has passed
    open_grace: timedelta = timedelta(days=1)
    # An article's age is a feature, and a voted article's age is measured at
    # the moment of the vote. Handing that to a method for the very articles
    # it is predicting tells it something the feed could not have known: how
    # long each one would sit before being voted on. So the articles being
    # predicted are aged as of the start of their block instead, which is the
    # last moment the feed could have been sorted for them. A method that sets
    # `sees_vote_time` is exempt, to measure how much the difference matters.
    age_as_of_block_start: bool = True


@dataclass
class Block:
    feed: int
    train_n: int
    labels: np.ndarray
    predictions: Dict[str, np.ndarray] = field(default_factory=dict)
    seconds: Dict[str, float] = field(default_factory=dict)
    # the model the old lowest-error rule had picked when this block was
    # predicted, and the one the fixed rule picks: counted in the result
    live_choice: Optional[str] = None
    rule_choice: Optional[str] = None


def live_models(quick: bool = False) -> List[VoteModel]:
    """The zoo the app's old picker chose from, built so it cannot take every
    core. Kept as it was when the picker ranked feeds, so `live_picker` stays
    the same yardstick from one round of experiments to the next."""
    models: List[VoteModel] = [
        RandomModel(),
        GlobalMeanModel(),
        SourceMeanModel(),
        KNNEmbeddingModel(),
        RidgeModel(),
        LogisticVoteModel(),
        SVRModel(),
        RandomForestModel(n_jobs=1),
        GradientBoostModel(),
        MLPModel(),
        DeepMLPModel(),
    ]
    return [m for m in models if not (quick and m.name in _HEAVY_LIVE)]


def build_methods(
    quick: bool = False, extra: Optional[Sequence[VoteModel]] = None
) -> List[VoteModel]:
    """Every method a run fits: the live zoo, then the new candidates."""
    candidates = [
        m for m in experiment_models() if not (quick and getattr(m, "heavy", False))
    ]
    return live_models(quick) + candidates + list(extra or [])


def is_calibrated(model: VoteModel) -> bool:
    return bool(getattr(model, "calibrated", True))


def _utc(moment: Optional[datetime]) -> Optional[datetime]:
    if moment is not None and moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment


def _standardise(scores: np.ndarray) -> np.ndarray:
    spread = scores.std()
    return (
        (scores - scores.mean()) / spread if spread > 1e-12 else np.zeros(len(scores))
    )


def _prior_auc(blocks: Sequence[Block], names: Sequence[str]) -> Dict[str, float]:
    """Each method's ranking AUC over the blocks already replayed for this
    feed. This is all a method that picks or blends is allowed to know: how the
    others did on votes that are, at this point in the replay, in the past."""
    out: Dict[str, float] = {}
    for name in names:
        total = weight = 0.0
        for block in blocks:
            scores = block.predictions.get(name)
            if scores is None or np.isnan(scores).any():
                continue
            value = metrics.auc(scores, block.labels)
            if value is None:
                continue
            pairs = metrics.pair_count(block.labels)
            total += value * pairs
            weight += pairs
        if weight:
            out[name] = total / weight
    return out


def _combine(
    block: Block,
    earlier: Sequence[Block],
    rankable: Sequence[str],
    live_choice: Optional[str],
) -> None:
    """Add the methods that are made of other methods' predictions."""
    available = [
        name
        for name in rankable
        if name in block.predictions and not np.isnan(block.predictions[name]).any()
    ]
    if not available:
        return

    block.live_choice = live_choice
    if live_choice in block.predictions:
        block.predictions[LIVE_PICKER] = block.predictions[live_choice]

    # The rule the app ranks with now: a fixed model for the number of votes,
    # handing over to the next rung when that model could not be fitted.
    first = live_model_name(block.train_n)
    if first is not None:
        rungs = LIVE_MODEL_LADDER[LIVE_MODEL_LADDER.index(first) :]
        block.rule_choice = next((name for name in rungs if name in available), None)
        if block.rule_choice is not None:
            block.predictions[LIVE_RULE] = block.predictions[block.rule_choice]

    for combined, members in (
        (BLEND_SVR_PRIOR, _BLEND_SVR_PRIOR_MEMBERS),
        (BLEND_STRONG, _BLEND_STRONG_MEMBERS),
    ):
        # all of its members or nothing: a blend missing one is a different
        # method, and averaging the two under one name would muddy both
        if all(name in available for name in members):
            block.predictions[combined] = np.mean(
                [_standardise(block.predictions[name]) for name in members], axis=0
            )

    history = _prior_auc(earlier, available)
    ranked = sorted(history, key=history.get, reverse=True)

    # Choose the single method that ordered this feed's earlier votes best.
    if ranked:
        block.predictions[TIME_PICKER] = block.predictions[ranked[0]]
    elif "knn_embedding" in available:
        block.predictions[TIME_PICKER] = block.predictions["knn_embedding"]

    core = [name for name in _BLEND_CORE_MEMBERS if name in available]
    if core:
        block.predictions[BLEND_CORE] = np.mean(
            [_standardise(block.predictions[name]) for name in core], axis=0
        )

    members = ranked[:3] if len(ranked) >= 3 else core
    if members:
        block.predictions[BLEND_TOP3] = np.mean(
            [_standardise(block.predictions[name]) for name in members], axis=0
        )


def replay_feed(
    labeled: Sequence[ItemFeatures],
    methods: Sequence[VoteModel],
    config: Optional[ReplayConfig] = None,
    feed_index: int = 0,
    account_items: Optional[Sequence[ItemFeatures]] = None,
    opened_items: Optional[Sequence[ItemFeatures]] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
) -> List[Block]:
    """Replay one feed. Returns a block per stretch of votes predicted.

    `labeled` is the feed's voted articles. `account_items` is the voted
    articles of every feed the account has, for the methods that learn across
    feeds. `opened_items` is the articles opened here, each with `label_date`
    set to when it was opened, for the methods that read an unvoted open as a
    quiet neutral.

    A feed with too few dated votes for even one block returns nothing.
    """
    config = config or ReplayConfig()
    undated = [i for i in labeled if i.label_date is None]
    dated = sorted(
        (i for i in labeled if i.label_date is not None),
        key=lambda i: _utc(i.label_date),
    )
    n = len(dated)
    if n < config.warmup + config.min_block:
        return []
    n_blocks = int(min(config.max_blocks, (n - config.warmup) // config.min_block))
    edges = np.linspace(config.warmup, n, n_blocks + 1).astype(int)

    feed_hashes = {i.url_hash for i in labeled}
    # this feed's own copy of an article wins: it carries this feed's
    # neighbours and source
    pool = list(labeled) + [
        i for i in (account_items or []) if i.url_hash not in feed_hashes
    ]
    rankable = [m.name for m in methods if m.rankable]

    blocks: List[Block] = []
    live_choice: Optional[str] = None

    def rest(elapsed: float) -> None:
        pause = min(elapsed * config.rest_fraction, config.max_rest_seconds)
        if pause > 0:
            time.sleep(pause)

    for index in range(n_blocks):
        start, end = int(edges[index]), int(edges[index + 1])
        train = undated + dated[:start]
        test = dated[start:end]
        cutoff = _utc(test[0].label_date)
        test_hashes = {i.url_hash for i in test}
        train_hashes = {i.url_hash for i in train}
        test_blind = (
            [replace(i, label_date=cutoff) for i in test]
            if config.age_as_of_block_start
            else test
        )
        block = Block(
            feed=feed_index,
            train_n=len(train),
            labels=np.asarray([float(i.label) for i in test]),
        )

        for model in methods:
            if should_stop is not None and should_stop():
                raise Cancelled()
            if on_progress is not None:
                on_progress(index, n_blocks, model.name)

            fit_on = train
            if getattr(model, "scope", "feed") == "account":
                fit_on = [
                    i
                    for i in pool
                    if i.url_hash not in test_hashes
                    and (i.label_date is None or _utc(i.label_date) < cutoff)
                ]
            if getattr(model, "uses_opens", False):
                # Opened long enough ago to have been voted on, and still
                # unvoted at this point in the replay. One that gets a vote
                # later is deliberately kept: at the time, the feed could not
                # have known.
                quiet = [
                    i
                    for i in (opened_items or [])
                    if i.url_hash not in train_hashes
                    and _utc(i.label_date) < cutoff - config.open_grace
                ]
                if len(quiet) < getattr(model, "min_opens", 1):
                    continue
                model.extra_items = quiet
            if len(fit_on) < max(model.min_labels, 2):
                continue
            only_last = getattr(model, "last_blocks", None)
            if only_last is not None and index < n_blocks - only_last:
                continue

            began = time.monotonic()
            try:
                model.fit(fit_on)
                shown = test if getattr(model, "sees_vote_time", False) else test_blind
                scores, _ = model.predict(shown)
                scores = np.asarray(scores, dtype=float)
            except Exception:
                continue
            elapsed = time.monotonic() - began
            if len(scores) != len(test) or np.isinf(scores).any():
                continue
            block.predictions[model.name] = scores
            block.seconds[model.name] = elapsed
            rest(elapsed)

        if index % config.picker_every == 0:
            if should_stop is not None and should_stop():
                raise Cancelled()
            if on_progress is not None:
                on_progress(index, n_blocks, LIVE_PICKER)
            began = time.monotonic()
            try:
                stats = evaluate_models(train, models=live_models(config.quick))
                live_choice = next((s.model_name for s in stats if s.chosen), None)
            except Exception:
                live_choice = None
            elapsed = time.monotonic() - began
            block.seconds[LIVE_PICKER] = elapsed
            rest(elapsed)

        _combine(block, blocks, rankable, live_choice)
        blocks.append(block)

    return blocks


# ---------------------------------------------------------------------------
# turning blocks into a report


def _block_scores(scores, labels, calibrated: bool, rng) -> dict:
    return {
        "n": len(labels),
        "pairs": metrics.pair_count(labels),
        "auc": metrics.auc(scores, labels),
        "top": metrics.top_k_hit_rate(scores, labels, TOP_K, rng),
        "base": float(metrics.is_upvote(labels).mean()),
        "ndcg": metrics.ndcg(scores, labels, NDCG_K, rng),
        "acc3": metrics.three_way_accuracy(scores, labels) if calibrated else None,
        "mae": metrics.mae(scores, labels) if calibrated else None,
    }


def _mean(rows: Sequence[dict], key: str, weight: str) -> Optional[float]:
    total = mass = 0.0
    for row in rows:
        if row[key] is None or not row[weight]:
            continue
        total += row[key] * row[weight]
        mass += row[weight]
    return total / mass if mass else None


def _interval(rows, statistic, n_boot: int, rng) -> Optional[List[float]]:
    """95% range of a statistic over resampled blocks. Blocks, not votes: the
    votes inside a block share one fit and are not independent of each other."""
    if len(rows) < 2:
        return None
    draws = []
    for _ in range(n_boot):
        sample = [rows[i] for i in rng.integers(0, len(rows), len(rows))]
        value = statistic(sample)
        if value is not None:
            draws.append(value)
    if len(draws) < 10:
        return None
    low, high = np.percentile(draws, [2.5, 97.5])
    return [round(float(low), 4), round(float(high), 4)]


def _round(value: Optional[float], digits: int = 4) -> Optional[float]:
    return None if value is None else round(float(value), digits)


def _band_of(train_n: int) -> str:
    for name, low, high in SIZE_BANDS:
        if train_n >= low and (high is None or train_n < high):
            return name
    return SIZE_BANDS[-1][0]


def summarize(
    blocks: Sequence[Block],
    calibrated: Dict[str, bool],
    baseline: str = BASELINE,
    n_boot: int = 200,
    seed: int = 0,
) -> List[dict]:
    """One row per method, best ranking AUC first.

    Every method is also compared with the baseline on exactly the predictions
    both made: same blocks, same articles. That pairing is what makes a small
    difference readable, since the hard blocks are hard for both.
    """
    rng = np.random.default_rng(seed)
    names: List[str] = []
    for block in blocks:
        for name in block.predictions:
            if name not in names:
                names.append(name)

    rows_out = []
    for name in names:
        is_cal = calibrated.get(name, False)
        own: List[dict] = []
        paired: List[dict] = []
        for block in blocks:
            scores = block.predictions.get(name)
            if scores is None:
                continue
            mask = ~np.isnan(scores)
            if mask.sum() < 2:
                continue
            labels = block.labels[mask]
            row = _block_scores(scores[mask], labels, is_cal, rng)
            row["train_n"] = block.train_n
            row["seconds"] = block.seconds.get(name)
            own.append(row)

            base = block.predictions.get(baseline)
            if base is None or name == baseline or np.isnan(base[mask]).any():
                continue
            other = _block_scores(base[mask], labels, False, rng)
            if row["auc"] is None or other["auc"] is None:
                continue
            paired.append(
                {
                    "pairs": row["pairs"],
                    "n": row["n"],
                    "auc_diff": row["auc"] - other["auc"],
                    "top_diff": row["top"] - other["top"],
                }
            )
        if not own:
            continue

        hit = _mean(own, "top", "n")
        base_rate = _mean(own, "base", "n")
        timed = [r["seconds"] for r in own if r["seconds"] is not None]
        out = {
            "method": name,
            "blocks": len(own),
            "predictions": int(sum(r["n"] for r in own)),
            "auc": _round(_mean(own, "auc", "pairs")),
            "auc_range": _interval(
                own, lambda s: _mean(s, "auc", "pairs"), n_boot, rng
            ),
            "top5_hit_rate": _round(hit),
            "top5_hit_range": _interval(
                own, lambda s: _mean(s, "top", "n"), n_boot, rng
            ),
            "upvote_base_rate": _round(base_rate),
            "top5_lift": _round(hit / base_rate)
            if hit is not None and base_rate
            else None,
            "ndcg10": _round(_mean(own, "ndcg", "n")),
            "three_way_accuracy": _round(_mean(own, "acc3", "n")),
            "mae": _round(_mean(own, "mae", "n")),
            "seconds_per_fit": _round(float(np.mean(timed)), 3) if timed else None,
            "by_training_size": {},
            "vs_baseline": None,
        }
        for band, _, _ in SIZE_BANDS:
            subset = [r for r in own if _band_of(r["train_n"]) == band]
            if subset:
                out["by_training_size"][band] = {
                    "blocks": len(subset),
                    "auc": _round(_mean(subset, "auc", "pairs")),
                    "top5_hit_rate": _round(_mean(subset, "top", "n")),
                }
        if paired:
            diff = _mean(paired, "auc_diff", "pairs")
            spread = _interval(
                paired, lambda s: _mean(s, "auc_diff", "pairs"), n_boot, rng
            )
            wins = float(
                np.mean(
                    [
                        1.0 if r["auc_diff"] > 0 else 0.5 if r["auc_diff"] == 0 else 0.0
                        for r in paired
                    ]
                )
            )
            if spread is None:
                verdict = "too few blocks to say"
            elif spread[0] > 0:
                verdict = "better"
            elif spread[1] < 0:
                verdict = "worse"
            else:
                verdict = "no clear difference"
            out["vs_baseline"] = {
                "blocks": len(paired),
                "auc_diff": _round(diff),
                "auc_diff_range": spread,
                "top5_hit_diff": _round(_mean(paired, "top_diff", "n")),
                "block_win_rate": _round(wins),
                "verdict": verdict,
            }
        rows_out.append(out)

    rows_out.sort(key=lambda r: (r["auc"] is None, -(r["auc"] or 0.0)))
    return rows_out
