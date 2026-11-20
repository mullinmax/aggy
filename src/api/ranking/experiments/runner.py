"""The stored queue of prediction experiments, and the job that works it.

An experiment replays a feed's whole vote history against a couple of dozen
methods. That is minutes of work, sometimes many, so asking for one only
queues it. A background job takes them one at a time, oldest first, and writes
the outcome back to the row it came from. Nothing about a run lives in memory
that matters: a page refresh reads the row, and a restart puts a half-finished
run back in the queue to start again.

It is also deliberately gentle. One experiment runs at a time for the whole
server, on one low-priority thread, and it idles for a while after every fit.
It is a curiosity the feed is not waiting on, and must never be the reason the
app feels slow.

Experiments read votes and write only their own row. They do not touch the
predictions the feed is sorted by, or the model it was last trained with.
"""

import logging
import os
from collections import Counter
import threading
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

from psycopg2.extras import Json

from config import config
from db.base import get_db_con
from db.feed import Feed
from db.item_open import engagement_summary, first_opens
from db.task_run import KIND_PREDICTION_EXPERIMENT, task_run
from ranking import engine
from ranking.models import ItemFeatures

from . import diagnostics, replay
from .llm_judge import LLMJudgeModel

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_ERROR = "error"
STATUS_CANCELLED = "cancelled"
OPEN_STATUSES = (STATUS_QUEUED, STATUS_RUNNING)

MODE_QUICK = "quick"
MODE_FULL = "full"
MODES = (MODE_QUICK, MODE_FULL)

# Bumped when the shape of a stored result changes, so a result pasted out of
# an old run can be told apart from a new one.
RESULT_FORMAT = 2

# An account may have this many experiments waiting or running. They are
# worked one at a time, so a longer queue is only a longer wait.
MAX_OPEN_PER_USER = 5

# The newest votes a feed is replayed over. Fits grow with the vote count
# (some of them quadratically), and a taste from thousands of votes ago says
# little about what to show next.
MAX_LABELS_PER_FEED = 3000
# The same cap on the votes borrowed from the account's other feeds.
MAX_ACCOUNT_LABELS = 5000

# How much lower than everything else the worker thread is scheduled.
NICENESS = 15

_PROGRESS_EVERY_SECONDS = 2.0
_CANCEL_CHECK_SECONDS = 3.0

_NOTES = [
    "Scores come from replaying votes in the order they were cast: each method "
    "is fitted on the votes before a block and ranks the block's articles.",
    "auc: chance that an upvoted article is ranked above one that was not. "
    "0.5 is a coin flip, 1.0 is perfect.",
    "top5_hit_rate: share of a block's 5 highest-ranked articles that were "
    "upvoted. top5_lift divides that by the block's overall upvote rate.",
    "ndcg10: graded ranking quality over the top 10 (upvote 2, neutral 1, downvote 0).",
    "three_way_accuracy and mae are only given for methods whose scores are on "
    "the vote scale.",
    "vs_baseline compares a method with live_picker on exactly the same "
    "predictions. Ranges are 95% over resampled blocks.",
    "live_picker: the app's old rule, lowest error on randomly held-out votes. "
    "live_rule: the rule the app ranks with now (svr from 12 votes, "
    "source_prior_knn from 6, knn_embedding below). picker_choices counts the "
    "blocks each rule ranked with each model.",
    "time_picker: best ranking on the feed's earlier blocks. blend_*: averages "
    "of several methods' rankings.",
    "From format 2, the articles being predicted are aged as of the start of "
    "their block, not as of their own vote, which the feed could not have "
    "known. svr_vote_time_age is the svr given the vote-time age anyway: the "
    "gap between it and svr is how much that difference is worth, and how far "
    "format 1 scores were flattered by it.",
    "feeds[].diagnostics describes each feed's votes in counts and shares "
    "only. similar_votes.nearest_agrees against agreement_by_chance says "
    "whether similar articles get similar votes at all.",
]


# ---------------------------------------------------------------------------
# the queue


def enqueue(
    user_hash: str,
    feed_hash: Optional[str] = None,
    mode: str = MODE_QUICK,
    llm_judge: bool = False,
) -> Optional[int]:
    """Queue an experiment. None when the account's queue is already full."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {', '.join(MODES)}")
    with get_db_con() as cur:
        cur.execute(
            "SELECT COUNT(*) AS n FROM ranking_experiments "
            "WHERE user_hash = %s AND status = ANY(%s)",
            (user_hash, list(OPEN_STATUSES)),
        )
        if cur.fetchone()["n"] >= MAX_OPEN_PER_USER:
            return None
        cur.execute(
            "INSERT INTO ranking_experiments (user_hash, feed_hash, config) "
            "VALUES (%s, %s, %s) RETURNING id",
            (user_hash, feed_hash, Json({"mode": mode, "llm_judge": bool(llm_judge)})),
        )
        return cur.fetchone()["id"]


_LIST_COLUMNS = (
    "id, feed_hash, config, status, progress, error, created_at, started_at, "
    "finished_at, result IS NOT NULL AS has_result"
)


def list_experiments(user_hash: str, limit: int = 20) -> List[dict]:
    """Newest first, without the results themselves (see `get_experiment`)."""
    with get_db_con() as cur:
        cur.execute(
            f"SELECT {_LIST_COLUMNS}, (SELECT COUNT(*) FROM ranking_experiments q "
            " WHERE q.status = 'queued' AND q.id < e.id) AS ahead "
            "FROM ranking_experiments e WHERE user_hash = %s "
            "ORDER BY id DESC LIMIT %s",
            (user_hash, limit),
        )
        return cur.fetchall()


def get_experiment(user_hash: str, experiment_id: int) -> Optional[dict]:
    with get_db_con() as cur:
        cur.execute(
            f"SELECT {_LIST_COLUMNS}, result, 0 AS ahead FROM ranking_experiments "
            "WHERE user_hash = %s AND id = %s",
            (user_hash, experiment_id),
        )
        return cur.fetchone()


def cancel(user_hash: str, experiment_id: int) -> bool:
    """Stop a waiting or running experiment. A running one notices within a
    few seconds, at its next check between fits."""
    with get_db_con() as cur:
        cur.execute(
            "UPDATE ranking_experiments SET status = %s, finished_at = NOW() "
            "WHERE user_hash = %s AND id = %s AND status = ANY(%s)",
            (STATUS_CANCELLED, user_hash, experiment_id, list(OPEN_STATUSES)),
        )
        return cur.rowcount > 0


def delete(user_hash: str, experiment_id: int) -> bool:
    """Forget a finished experiment. One still waiting or running has to be
    cancelled first, so a run cannot be deleted out from under its worker."""
    with get_db_con() as cur:
        cur.execute(
            "DELETE FROM ranking_experiments WHERE user_hash = %s AND id = %s "
            "AND NOT (status = ANY(%s))",
            (user_hash, experiment_id, list(OPEN_STATUSES)),
        )
        return cur.rowcount > 0


def requeue_interrupted() -> int:
    """Put experiments a dead process left running back in the queue.

    Called at start up. The whole point of the queue is that asking for an
    experiment is fire-and-forget, and a deploy in the middle of one should
    cost a restart of that run, not the run."""
    try:
        with get_db_con() as cur:
            cur.execute(
                "UPDATE ranking_experiments SET status = %s, started_at = NULL, "
                "progress = NULL WHERE status = %s",
                (STATUS_QUEUED, STATUS_RUNNING),
            )
            if cur.rowcount:
                logging.info(
                    f"Re-queued {cur.rowcount} prediction experiment(s) "
                    "interrupted by a restart"
                )
            return cur.rowcount
    except Exception as e:
        logging.error(f"Could not re-queue interrupted experiments: {e}")
        return 0


def _claim_next() -> Optional[dict]:
    """Take the oldest waiting experiment, unless one is already running."""
    with get_db_con() as cur:
        cur.execute(
            "UPDATE ranking_experiments SET status = %s, started_at = NOW() "
            "WHERE id = (SELECT id FROM ranking_experiments WHERE status = %s "
            " ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED) "
            "AND NOT EXISTS (SELECT 1 FROM ranking_experiments WHERE status = %s) "
            "RETURNING id, user_hash, feed_hash, config",
            (STATUS_RUNNING, STATUS_QUEUED, STATUS_RUNNING),
        )
        return cur.fetchone()


def _status(experiment_id: int) -> Optional[str]:
    with get_db_con() as cur:
        cur.execute(
            "SELECT status FROM ranking_experiments WHERE id = %s", (experiment_id,)
        )
        row = cur.fetchone()
    return row["status"] if row else None


def _finish(experiment_id: int, status: str, result=None, error=None) -> None:
    # Only a run still marked running is finished: one cancelled while its last
    # fit was in flight stays cancelled.
    with get_db_con() as cur:
        cur.execute(
            "UPDATE ranking_experiments SET status = %s, result = %s, error = %s, "
            "finished_at = NOW() WHERE id = %s AND status = %s",
            (
                status,
                Json(result) if result is not None else None,
                error,
                experiment_id,
                STATUS_RUNNING,
            ),
        )


# ---------------------------------------------------------------------------
# reading what an experiment learns from


def _newest(items: List[ItemFeatures], limit: int) -> List[ItemFeatures]:
    if len(items) <= limit:
        return items
    epoch = datetime.min.replace(tzinfo=timezone.utc)

    def cast_at(item: ItemFeatures) -> datetime:
        moment = item.label_date
        if moment is None:
            return epoch
        return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)

    return sorted(items, key=cast_at)[-limit:]


def _load_labeled(feed: Feed) -> List[ItemFeatures]:
    labeled = engine.load_feed_features(feed, labeled_only=True)
    return _newest([f for f in labeled if f.label is not None], MAX_LABELS_PER_FEED)


def _load_origins(feed: Feed) -> Dict[str, dict]:
    """How each of the feed's labels came about: a vote, a list, or both.
    The features only carry the label the two fold into."""
    with get_db_con() as cur:
        cur.execute(
            "SELECT c.item_url_hash, v.score AS vote, EXISTS ("
            " SELECT 1 FROM list_items li WHERE li.user_hash = c.user_hash"
            "  AND li.item_url_hash = c.item_url_hash) AS listed "
            "FROM feed_items c "
            "LEFT JOIN user_item_votes v ON v.user_hash = c.user_hash "
            " AND v.item_url_hash = c.item_url_hash "
            "WHERE c.user_hash = %s AND c.feed_hash = %s" + engine._LABELED_ONLY_SQL,
            (feed.user_hash, feed.name_hash),
        )
        return {
            row["item_url_hash"]: {"vote": row["vote"], "listed": bool(row["listed"])}
            for row in cur.fetchall()
        }


def _diagnose(feed: Feed, labeled: List[ItemFeatures]) -> Optional[dict]:
    """The feed's diagnostics, or a note that they failed. They explain a
    result; they are not worth losing one over."""
    try:
        return diagnostics.diagnose(labeled, _load_origins(feed))
    except Exception as e:
        logging.exception(f"Experiment diagnostics failed: {e}")
        return {"error": "diagnostics could not be computed"}


def _picker_choices(blocks) -> dict:
    """How many blocks each rule ranked with each model."""
    return {
        "live_picker": dict(Counter(b.live_choice or "none" for b in blocks)),
        "live_rule": dict(Counter(b.rule_choice or "none" for b in blocks)),
    }


def _load_opened(feed: Feed) -> List[ItemFeatures]:
    """The articles opened in this feed, as features dated by their first open
    and labelled neutral: what the opens-as-neutral methods are handed."""
    opens = {
        row["item_url_hash"]: row["opened_at"]
        for row in first_opens(feed.user_hash, feed.name_hash)
    }
    if not opens:
        return []
    with get_db_con() as cur:
        cur.execute(
            engine._FEED_ITEMS_SQL + " AND c.item_url_hash = ANY(%s)",
            (feed.user_hash, feed.name_hash, list(opens)),
        )
        rows = cur.fetchall()
        neighbors = engine._load_neighbors(cur, feed, [r["url_hash"] for r in rows])
    items = []
    for row in rows:
        item = engine._row_to_features(row, neighbors)
        item.label = 0.0
        item.label_date = opens[item.url_hash]
        items.append(item)
    return items


def _load_texts(feed: Feed, url_hashes: List[str]) -> Dict[str, tuple]:
    """Titles and excerpts, for the language-model judge only. They are shown
    to the local model and never written anywhere."""
    if not url_hashes:
        return {}
    with get_db_con() as cur:
        cur.execute(
            "SELECT url_hash, title, excerpt FROM items WHERE url_hash = ANY(%s)",
            (url_hashes,),
        )
        return {r["url_hash"]: (r["title"], r["excerpt"]) for r in cur.fetchall()}


# ---------------------------------------------------------------------------
# running one


class _Progress:
    """Writes where the run has got to, at most every couple of seconds, and
    notices when the run has been cancelled."""

    def __init__(self, experiment_id: int, feed_count: int):
        self.experiment_id = experiment_id
        self.feed_count = feed_count
        self.feed_index = 0
        self._written = 0.0
        self._checked = time.monotonic()
        self._stopped = False

    def report(self, block: int, blocks: int, method: str, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._written < _PROGRESS_EVERY_SECONDS:
            return
        self._written = now
        done = self.feed_index + (block / blocks if blocks else 0.0)
        try:
            with get_db_con() as cur:
                cur.execute(
                    "UPDATE ranking_experiments SET progress = %s WHERE id = %s",
                    (
                        Json(
                            {
                                "feed": self.feed_index + 1,
                                "feeds": self.feed_count,
                                "block": block + 1,
                                "blocks": blocks,
                                "method": method,
                                "fraction": round(done / max(self.feed_count, 1), 4),
                            }
                        ),
                        self.experiment_id,
                    ),
                )
        except Exception as e:  # a progress bar is not worth failing a run for
            logging.debug(f"Could not write experiment progress: {e}")

    def should_stop(self) -> bool:
        if self._stopped:
            return True
        now = time.monotonic()
        if now - self._checked >= _CANCEL_CHECK_SECONDS:
            self._checked = now
            self._stopped = _status(self.experiment_id) != STATUS_RUNNING
        return self._stopped


def _feed_summary(index: int, labeled, blocks, rows, diagnosis=None) -> dict:
    labels = [float(i.label) for i in labeled]
    by_method = {r["method"]: r["auc"] for r in rows}
    summary = {
        # a number, never the name: the result is meant to be copied out
        "feed": f"Feed {index + 1}",
        "labels": len(labels),
        "upvotes": sum(1 for v in labels if v > 0),
        "neutral": sum(1 for v in labels if v == 0),
        "downvotes": sum(1 for v in labels if v < 0),
        "blocks": len(blocks),
        "auc_by_method": by_method,
        "picker_choices": _picker_choices(blocks),
        "diagnostics": diagnosis,
    }
    if not blocks:
        summary["skipped"] = "too few dated votes to replay"
    return summary


def run_experiment(
    experiment_id: int,
    user_hash: str,
    feed_hash: Optional[str],
    settings: dict,
    replay_config: Optional[replay.ReplayConfig] = None,
) -> dict:
    """Replay the feeds an experiment covers and build its result."""
    began = time.monotonic()
    started_at = datetime.now(timezone.utc)
    quick = settings.get("mode", MODE_QUICK) == MODE_QUICK
    use_llm = bool(settings.get("llm_judge"))
    replay_config = replay_config or replay.ReplayConfig(
        quick=quick, max_blocks=6 if quick else 12
    )

    every_feed = Feed.read_all(user_hash)
    labeled_by_feed = {feed.name_hash: _load_labeled(feed) for feed in every_feed}
    targets = [f for f in every_feed if feed_hash is None or f.name_hash == feed_hash]
    # most votes first, so "Feed 1" is always the feed with the most to say
    targets.sort(key=lambda f: -len(labeled_by_feed[f.name_hash]))

    # every vote the account has cast, once, for the cross-feed methods
    seen: set = set()
    account_items: List[ItemFeatures] = []
    for items in labeled_by_feed.values():
        for item in items:
            if item.url_hash not in seen:
                seen.add(item.url_hash)
                account_items.append(item)
    account_items = _newest(account_items, MAX_ACCOUNT_LABELS)

    progress = _Progress(experiment_id, len(targets))
    all_blocks: List[replay.Block] = []
    calibrated: Dict[str, bool] = {name: False for name in replay.COMBINED}
    feeds_out = []

    for index, feed in enumerate(targets):
        progress.feed_index = index
        labeled = labeled_by_feed[feed.name_hash]
        extra = []
        if use_llm:
            texts = _load_texts(feed, [i.url_hash for i in labeled])
            extra.append(LLMJudgeModel(texts))
        # built fresh per feed: a method carries what it learned from the last
        # one, and must not carry it into the next
        methods = replay.build_methods(quick=quick, extra=extra)
        for method in methods:
            calibrated[method.name] = replay.is_calibrated(method)
        blocks = replay.replay_feed(
            labeled,
            methods,
            replay_config,
            feed_index=index,
            account_items=account_items,
            opened_items=_load_opened(feed),
            on_progress=progress.report,
            should_stop=progress.should_stop,
        )
        all_blocks.extend(blocks)
        feeds_out.append(
            _feed_summary(
                index,
                labeled,
                blocks,
                replay.summarize(blocks, calibrated, n_boot=0),
                _diagnose(feed, labeled),
            )
        )

    methods_out = replay.summarize(all_blocks, calibrated)
    ran = {row["method"] for row in methods_out}
    return {
        "format": RESULT_FORMAT,
        "app_version": config.get("BUILD_VERSION", default="unknown"),
        "mode": MODE_QUICK if quick else MODE_FULL,
        "llm_judge": use_llm,
        "scope": "one feed" if feed_hash is not None else "all feeds",
        "started_at": started_at.isoformat(),
        "seconds": round(time.monotonic() - began, 1),
        "baseline": replay.BASELINE,
        "blocks": len(all_blocks),
        "predictions": int(sum(len(b.labels) for b in all_blocks)),
        "methods": methods_out,
        "not_run": sorted(name for name in calibrated if name not in ran),
        "picker_choices": _picker_choices(all_blocks),
        "feeds": feeds_out,
        "engagement": engagement_summary(
            user_hash, None if feed_hash is None else [feed_hash]
        ),
        "notes": _NOTES,
    }


def _lower_priority() -> None:
    """Make this thread the last thing the machine schedules. On Linux a
    thread has a nice value of its own, so this does not slow the API down."""
    try:
        os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), NICENESS)
    except Exception as e:
        logging.debug(f"Could not lower the experiment thread's priority: {e}")


def _work(row: dict) -> None:
    experiment_id = row["id"]
    _lower_priority()
    target = "one feed" if row["feed_hash"] else "all feeds"
    try:
        with task_run(KIND_PREDICTION_EXPERIMENT, row["user_hash"], target) as run:
            try:
                result = run_experiment(
                    experiment_id,
                    row["user_hash"],
                    row["feed_hash"],
                    row["config"] or {},
                )
            except replay.Cancelled:
                run.detail = "cancelled"
                return
            _finish(experiment_id, STATUS_DONE, result=result)
            run.detail = (
                f"{len(result['methods'])} method(s) over {result['blocks']} "
                f"block(s) of votes"
            )
    except Exception as e:
        logging.exception(f"Prediction experiment {experiment_id} failed: {e}")
        _finish(experiment_id, STATUS_ERROR, error=str(e)[:500])


def experiment_job() -> None:
    """Work the queue until it is empty, one experiment at a time.

    Scheduled with a single instance, and `_claim_next` refuses while anything
    is marked running, so two experiments never overlap. Each runs on a thread
    of its own: the priority it lowers is that thread's, and the scheduler's
    pooled threads go on to do other work at full speed.
    """
    while True:
        try:
            row = _claim_next()
        except Exception as e:
            logging.error(f"Could not read the experiment queue: {e}")
            return
        if row is None:
            return
        worker = threading.Thread(
            target=_work, args=(row,), name="prediction-experiment", daemon=True
        )
        worker.start()
        worker.join()
