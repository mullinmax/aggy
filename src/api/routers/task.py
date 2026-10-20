from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Path, Query

from config import config
from db.item import reset_failed_image_embeds
from db.task_run import (
    KIND_IMAGE_EMBED_BACKFILL,
    KIND_NEIGHBOR_GRAPH,
    KIND_SOURCE_INGEST,
    KIND_SOURCE_RESCRAPE,
    TASK_KINDS,
    TASK_STATUSES,
    recent_runs,
    run_summary,
    running_runs,
)
from db.user import User
from neighbors.graph import neighbor_graph_job
from ingest.jobs import (
    ALL_SOURCES_TARGET,
    backfill_image_embeddings_job,
    ingest_user_sources,
    rescrape_user_sources,
)
from route_models.task import (
    TaskKindSummaryResponse,
    TaskRunResponse,
    TaskRunsResponse,
    TaskTriggerResponse,
)
from routers.auth import authenticate

task_router = APIRouter()

# The backstop on a busy install: a source per ingest cycle over a week is a
# lot of rows, and a timeline cannot draw more bars than a screen has pixels.
# The response says when this bit so the page can admit the view is partial.
RUN_LIMIT = 2000


def _parse_csv(value: Optional[str], allowed, name: str):
    """A comma-separated filter, validated against what exists.

    An unknown value is a 422 rather than silently empty: a typo'd filter that
    returns nothing looks exactly like a quiet period, which is the one thing
    this page must not get wrong.
    """
    if value is None:
        return None
    picked = [v.strip() for v in value.split(",") if v.strip()]
    unknown = [v for v in picked if v not in allowed]
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown {name} '{unknown[0]}'")
    return picked


@task_router.get(
    "/runs",
    summary="Recent background task runs for this account",
    response_model=TaskRunsResponse,
)
def get_task_runs(
    hours: int = Query(
        24, ge=1, le=24 * 30, description="How far back to report, in hours"
    ),
    kinds: Optional[str] = Query(
        None,
        description="Comma-separated task kinds to keep: "
        + ", ".join(TASK_KINDS)
        + ". Omit for all.",
    ),
    statuses: Optional[str] = Query(
        None,
        description="Comma-separated statuses to keep: "
        + ", ".join(TASK_STATUSES)
        + ". Omit for all.",
    ),
    user: User = Depends(authenticate),
) -> TaskRunsResponse:
    """What the background jobs have been doing for this account.

    Includes the system-wide passes (duplicate detection, the image-embedding
    backfill), which work a global queue rather than this account's articles and
    are flagged ``system_wide`` so the page can label them rather than imply
    they ran for you.

    The per-kind summary is computed over the whole window regardless of the
    row limit, so the counts stay true even when the timeline is truncated.
    """
    kind_filter = _parse_csv(kinds, set(TASK_KINDS), "task kind")
    status_filter = _parse_csv(statuses, set(TASK_STATUSES), "status")

    runs = recent_runs(
        user.name_hash,
        hours=hours,
        kinds=kind_filter,
        statuses=status_filter,
        limit=RUN_LIMIT,
    )
    summary = run_summary(user.name_hash, hours=hours)

    now = datetime.now(timezone.utc)
    return TaskRunsResponse(
        runs=[
            TaskRunResponse(
                run_id=row["id"],
                kind=row["kind"],
                target=row["target"],
                status=row["status"],
                detail=row["detail"],
                started_at=row["started_at"],
                finished_at=row["finished_at"],
                duration_seconds=float(row["duration_seconds"] or 0.0),
                system_wide=row["system_wide"],
            )
            for row in runs
        ],
        kinds=[
            TaskKindSummaryResponse(
                kind=row["kind"],
                runs=row["runs"],
                errors=row["errors"],
                running=row["running"],
                system_wide=row["system_wide"],
                last_started_at=row["last_started_at"],
                median_seconds=(
                    float(row["median_seconds"])
                    if row["median_seconds"] is not None
                    else None
                ),
                max_seconds=(
                    float(row["max_seconds"])
                    if row["max_seconds"] is not None
                    else None
                ),
            )
            for row in summary["kinds"]
        ],
        total_runs=summary["total_runs"],
        total_errors=summary["total_errors"],
        total_running=summary["total_running"],
        hours=hours,
        window_start=now - timedelta(hours=hours),
        window_end=now,
        truncated=len(runs) >= RUN_LIMIT,
    )


# The background work a person can ask for by hand, and what each one means.
#
# Everything here is work the scheduler already does on an interval; a trigger
# only says "now", because waiting an hour to find out whether a fix worked is
# how a fix goes unverified. Deliberately a fixed list rather than "run any
# job": these are the passes it makes sense to ask for, with an account's own
# work scoped to that account.
#
# `system` marks a pass over a global queue, which is nobody's in particular --
# those are checked for "already running" across the whole install, since a
# second pass over the same queue is only duplicated work. An account's own
# passes are checked against a batch of theirs (`target`), so a manual sweep
# isn't refused because the scheduler happens to be ingesting one source.
_TRIGGERS = {
    "image_embed_retry": {
        "kind": KIND_IMAGE_EMBED_BACKFILL,
        "system": True,
        "label": "image embedding retry",
    },
    "neighbor_graph": {
        "kind": KIND_NEIGHBOR_GRAPH,
        "system": True,
        "label": "similar-article linking and duplicate detection",
    },
    "ingest_sources": {
        "kind": KIND_SOURCE_INGEST,
        "system": False,
        "target": ALL_SOURCES_TARGET,
        "label": "source ingest",
    },
    "rescrape_sources": {
        "kind": KIND_SOURCE_RESCRAPE,
        "system": False,
        "target": ALL_SOURCES_TARGET,
        "label": "source re-scrape",
    },
}

TRIGGERS = tuple(_TRIGGERS)


@task_router.post(
    "/run/{task}",
    summary="Run a background task now",
    response_model=TaskTriggerResponse,
)
def run_task_now(
    background_tasks: BackgroundTasks,
    task: str = Path(
        ...,
        description="Which task to run: " + ", ".join(TRIGGERS),
    ),
    user: User = Depends(authenticate),
) -> TaskTriggerResponse:
    """Ask a background task to start now rather than at its next interval.

    Answers as soon as the work is queued, not when it finishes -- a re-scrape
    of every source runs for as long as it runs. Watch the timeline for the
    run this produces; it appears under the kind named in the response.

    A pass that is already running is not started a second time: the response
    comes back with ``started`` false and says so, rather than stacking two
    passes over one queue.
    """
    trigger = _TRIGGERS.get(task)
    if trigger is None:
        raise HTTPException(status_code=404, detail=f"Unknown task '{task}'")

    kind = trigger["kind"]
    running = running_runs(
        kind,
        user_hash=None if trigger["system"] else user.name_hash,
        target=trigger.get("target"),
    )
    if running:
        return TaskTriggerResponse(
            task=task,
            kind=kind,
            started=False,
            detail=f"A {trigger['label']} pass is already running.",
        )

    if task == "image_embed_retry":
        if config.get("IMAGE_EMBED_HOST", None) is None:
            # The backfill no-ops without the service, so queueing it would be
            # a button reporting work it knows will not happen.
            return TaskTriggerResponse(
                task=task,
                kind=kind,
                started=False,
                detail="The image embedding service is not configured, "
                "so there are no pictures to embed.",
            )

        # Done here rather than in the background task so the answer can say
        # how much work was just re-queued -- it is one UPDATE, and a person
        # pressing a button deserves a number back.
        requeued, gone = reset_failed_image_embeds()
        background_tasks.add_task(backfill_image_embeddings_job)
        # The "gone" count is said out loud rather than quietly skipped: a
        # button that re-queued nothing and a library whose pictures no longer
        # exist look identical otherwise.
        gone_note = (
            f" {gone} more will not be retried: their hosts say the picture is gone."
            if gone
            else ""
        )
        detail = (
            f"Re-queued {requeued} item(s) whose image embedding failed; "
            "embedding them now."
            if requeued
            else "No failed image embeddings to retry; "
            "embedding anything still missing."
        ) + gone_note
    elif task == "neighbor_graph":
        background_tasks.add_task(neighbor_graph_job)
        detail = (
            "Linking articles to the ones most like them, and grouping the "
            "duplicates that finds, now."
        )
    elif task == "ingest_sources":
        background_tasks.add_task(ingest_user_sources, user.name_hash)
        detail = "Fetching new articles from every one of your sources now."
    else:
        background_tasks.add_task(rescrape_user_sources, user.name_hash)
        detail = (
            "Re-scraping every article of every source you have. "
            "This one takes a while."
        )

    return TaskTriggerResponse(task=task, kind=kind, started=True, detail=detail)
