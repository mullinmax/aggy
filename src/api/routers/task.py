from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from db.task_run import (
    TASK_KINDS,
    TASK_STATUSES,
    recent_runs,
    run_summary,
)
from db.user import User
from route_models.task import (
    TaskKindSummaryResponse,
    TaskRunResponse,
    TaskRunsResponse,
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
