"""Records of what the background jobs did, and how long each pass took.

Aggy does most of its work on a scheduler, and until this existed none of it
was visible: ``ranking.progress`` tracks a training run only while it is in
flight, ``source_ingest_attempts`` records that an ingest happened but not how
long it took, and the rest left a log line at most.

Every pass opens a row here and closes it when it ends, so the tasks page can
draw a bar per run and answer what a log cannot: how often does this run, and
how long does it take.

Bookkeeping never breaks the work it describes. Every function here swallows
its own errors: failing to record a run must not turn a successful ingest into
a failed one.
"""

import logging
from contextlib import contextmanager
from typing import List, Optional

from config import config

from .base import get_db_con

# The kinds of pass worth showing. Kept as constants rather than free strings so
# the page's filter list and the recorders cannot drift apart.
KIND_FEED_TRAINING = "feed_training"
KIND_FEED_SCORING = "feed_scoring"
KIND_SOURCE_INGEST = "source_ingest"
KIND_SOURCE_RESCRAPE = "source_rescrape"
KIND_DUPLICATE_DETECTION = "duplicate_detection"
KIND_IMAGE_EMBED_BACKFILL = "image_embed_backfill"
KIND_NEIGHBOR_GRAPH = "neighbor_graph"

# Ordered for display: the ones an account owns first, then the system-wide
# passes it only observes.
TASK_KINDS = (
    KIND_FEED_TRAINING,
    KIND_FEED_SCORING,
    KIND_SOURCE_INGEST,
    KIND_SOURCE_RESCRAPE,
    KIND_DUPLICATE_DETECTION,
    KIND_IMAGE_EMBED_BACKFILL,
    KIND_NEIGHBOR_GRAPH,
)

# Passes that work a global queue rather than one account's articles. Stored
# with a NULL user_hash and labelled as system-wide when shown, because
# claiming them as the viewer's own work on a per-account page would be a lie.
SYSTEM_KINDS = frozenset(
    {KIND_DUPLICATE_DETECTION, KIND_IMAGE_EMBED_BACKFILL, KIND_NEIGHBOR_GRAPH}
)

STATUS_RUNNING = "running"
STATUS_OK = "ok"
STATUS_ERROR = "error"
TASK_STATUSES = (STATUS_RUNNING, STATUS_OK, STATUS_ERROR)

# A detail line is read in a table cell and a tooltip; a stack-trace tail or a
# quoted error page is not.
_DETAIL_MAX_CHARS = 300


def _trim(detail: Optional[str]) -> Optional[str]:
    if detail is not None and len(detail) > _DETAIL_MAX_CHARS:
        return detail[: _DETAIL_MAX_CHARS - 1] + "…"
    return detail


def start_run(
    kind: str, user_hash: Optional[str] = None, target: Optional[str] = None
) -> Optional[int]:
    """Open a run and return its id, or None if it could not be recorded.

    A None id is not an error the caller has to handle -- `finish_run` ignores
    it -- so the work goes ahead unrecorded rather than not at all.
    """
    try:
        with get_db_con() as cur:
            cur.execute(
                "INSERT INTO task_runs (user_hash, kind, target, status) "
                "VALUES (%s, %s, %s, %s) RETURNING id",
                (user_hash, kind, target, STATUS_RUNNING),
            )
            return cur.fetchone()["id"]
    except Exception as e:
        logging.error(f"Could not record the start of a {kind} run: {e}")
        return None


def finish_run(
    run_id: Optional[int], status: str = STATUS_OK, detail: Optional[str] = None
) -> None:
    """Close a run. A None id is a no-op, for the case above."""
    if run_id is None:
        return
    try:
        with get_db_con() as cur:
            cur.execute(
                "UPDATE task_runs SET status = %s, detail = %s, finished_at = NOW() "
                "WHERE id = %s",
                (status, _trim(detail), run_id),
            )
    except Exception as e:
        logging.error(f"Could not record the end of task run {run_id}: {e}")


def set_run_target(run_id: Optional[int], target: str) -> None:
    """Name what an open run is working on.

    For a pass whose subject is only known after it starts -- the ingest job
    picks its source by hash and learns the name when it reads it -- so the
    timeline can still give that source a lane of its own while the pass runs.
    """
    if run_id is None:
        return
    try:
        with get_db_con() as cur:
            cur.execute(
                "UPDATE task_runs SET target = %s WHERE id = %s", (target, run_id)
            )
    except Exception as e:
        logging.error(f"Could not set the target of task run {run_id}: {e}")


@contextmanager
def task_run(kind: str, user_hash: Optional[str] = None, target: Optional[str] = None):
    """Record one pass for as long as the block runs.

    Yields a handle whose ``detail`` the block sets, read when the block ends
    -- the interesting counts are usually only known by then::

        with task_run(KIND_SOURCE_INGEST, user.name_hash, source.name) as run:
            n = ingest()
            run.detail = f"{n} new article(s)"

    A failing block is recorded as an error with its message and the exception
    is re-raised: this observes the work, it does not handle it.
    """

    class _Run:
        detail: Optional[str] = None

    handle = _Run()
    run_id = start_run(kind, user_hash=user_hash, target=target)
    try:
        yield handle
    except Exception as e:
        finish_run(run_id, STATUS_ERROR, handle.detail or f"{type(e).__name__}: {e}")
        raise
    finish_run(run_id, STATUS_OK, handle.detail)


# A run still marked running long after it started belongs to a process that
# died without closing it (`abandon_running_runs` only tidies those at start
# up). Counting one forever would leave a manual trigger refusing to fire until
# the next restart, so the "is this already running" check ignores anything
# older than a pass could plausibly be.
_RUNNING_STALE_HOURS = 6


def running_runs(
    kind: str, user_hash: Optional[str] = None, target: Optional[str] = None
) -> int:
    """How many passes of this kind are in flight right now.

    Used to answer a manual trigger with "it is already running" rather than
    starting a second pass over the same queue. ``user_hash`` scopes the count
    to one account (pass None for the system-wide kinds, which are recorded
    with no owner) and ``target`` narrows it further, so a manual "all sources"
    batch is only blocked by another batch rather than by whichever single
    source the scheduler happens to be ingesting.

    Counts nothing on a database error: refusing a trigger because the check
    itself broke is worse than letting a second pass start.
    """
    clauses = ["kind = %s", "status = %s"]
    params: list = [kind, STATUS_RUNNING]

    if user_hash is None:
        clauses.append("user_hash IS NULL")
    else:
        clauses.append("user_hash = %s")
        params.append(user_hash)

    if target is not None:
        clauses.append("target = %s")
        params.append(target)

    clauses.append("started_at >= NOW() - make_interval(hours => %s)")
    params.append(_RUNNING_STALE_HOURS)

    try:
        with get_db_con() as cur:
            cur.execute(
                "SELECT COUNT(*) AS running FROM task_runs WHERE "
                + " AND ".join(clauses),
                tuple(params),
            )
            return cur.fetchone()["running"]
    except Exception as e:
        logging.error(f"Could not check for running {kind} runs: {e}")
        return 0


def abandon_running_runs() -> int:
    """Close runs left open by a process that died, and say so.

    Called at start up. A row still marked running from a previous process is
    not running -- nothing will ever finish it -- and leaving it would show the
    page a task that has been going since the last restart.
    """
    try:
        with get_db_con() as cur:
            cur.execute(
                "UPDATE task_runs SET status = %s, finished_at = NOW(), "
                "detail = COALESCE(detail, 'interrupted by a restart') "
                "WHERE status = %s",
                (STATUS_ERROR, STATUS_RUNNING),
            )
            if cur.rowcount:
                logging.info(
                    f"Closed {cur.rowcount} task run(s) left open by a restart"
                )
            return cur.rowcount
    except Exception as e:
        logging.error(f"Could not close interrupted task runs: {e}")
        return 0


def prune_runs(days: Optional[int] = None) -> int:
    """Drop runs older than the retention window. Returns rows deleted."""
    if days is None:
        days = config.get_int("TASK_RUN_HISTORY_DAYS")
    try:
        with get_db_con() as cur:
            cur.execute(
                "DELETE FROM task_runs "
                "WHERE started_at < NOW() - make_interval(days => %s)",
                (days,),
            )
            return cur.rowcount
    except Exception as e:
        logging.error(f"Could not prune task runs: {e}")
        return 0


# One account's runs plus the system-wide ones. A system pass is everybody's to
# see and nobody's to own, so it is included for every account and marked as
# such by its NULL user_hash rather than by its kind -- the caller does not have
# to know which kinds are system-wide to render it.
_RUNS_SQL = """
SELECT id, kind, target, status, detail, started_at, finished_at,
       user_hash IS NULL AS system_wide,
       EXTRACT(EPOCH FROM (COALESCE(finished_at, NOW()) - started_at))
           AS duration_seconds
FROM task_runs
WHERE (user_hash = %s OR user_hash IS NULL)
  AND started_at >= NOW() - make_interval(hours => %s)
"""


def recent_runs(
    user_hash: str,
    hours: int = 24,
    kinds: Optional[List[str]] = None,
    statuses: Optional[List[str]] = None,
    limit: int = 2000,
) -> List[dict]:
    """This account's runs over a window, newest first.

    ``kinds`` and ``statuses`` are applied in SQL rather than in the page, so a
    narrow filter over a long window does not pull every row to drop most of
    them. The limit is a backstop on a busy install; the page says when it bites.
    """
    sql = _RUNS_SQL
    params: tuple = (user_hash, hours)

    if kinds:
        sql += " AND kind = ANY(%s)"
        params = params + (list(kinds),)
    if statuses:
        sql += " AND status = ANY(%s)"
        params = params + (list(statuses),)

    sql += " ORDER BY started_at DESC LIMIT %s"
    params = params + (limit,)

    with get_db_con() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def run_summary(user_hash: str, hours: int = 24) -> dict:
    """Per-kind totals over the window: how many passes, how many failed, and
    how long they take.

    The median matters more than the mean here. One pathological pass (a source
    behind a timeout, a first-ever training run on a big feed) drags an average
    far from what a typical pass costs.
    """
    with get_db_con() as cur:
        cur.execute(
            "SELECT kind, "
            " COUNT(*) AS runs, "
            " COUNT(*) FILTER (WHERE status = %s) AS errors, "
            " COUNT(*) FILTER (WHERE status = %s) AS running, "
            " bool_or(user_hash IS NULL) AS system_wide, "
            " MAX(started_at) AS last_started_at, "
            " PERCENTILE_CONT(0.5) WITHIN GROUP ("
            "  ORDER BY EXTRACT(EPOCH FROM (finished_at - started_at))"
            " ) AS median_seconds, "
            " MAX(EXTRACT(EPOCH FROM (finished_at - started_at))) AS max_seconds "
            "FROM task_runs "
            "WHERE (user_hash = %s OR user_hash IS NULL) "
            " AND started_at >= NOW() - make_interval(hours => %s) "
            "GROUP BY kind ORDER BY kind",
            (STATUS_ERROR, STATUS_RUNNING, user_hash, hours),
        )
        kinds = cur.fetchall()

    return {
        "kinds": kinds,
        "total_runs": sum(row["runs"] for row in kinds),
        "total_errors": sum(row["errors"] for row in kinds),
        "total_running": sum(row["running"] for row in kinds),
    }
