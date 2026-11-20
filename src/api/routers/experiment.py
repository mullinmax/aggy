from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from db.feed import Feed
from db.user import User
from ranking.experiments import runner
from route_models.acknowledge import AcknowledgeResponse
from route_models.experiment import (
    ExperimentListResponse,
    ExperimentProgressResponse,
    ExperimentResponse,
)
from routers.auth import authenticate

experiment_router = APIRouter()


def _response(row: dict) -> ExperimentResponse:
    settings = row.get("config") or {}
    progress = row.get("progress")
    return ExperimentResponse(
        experiment_id=row["id"],
        status=row["status"],
        mode=settings.get("mode", runner.MODE_QUICK),
        llm_judge=bool(settings.get("llm_judge")),
        feed_name_hash=row.get("feed_hash"),
        queued_ahead=row.get("ahead") or 0 if row["status"] == "queued" else 0,
        progress=ExperimentProgressResponse(**progress)
        if progress and row["status"] == runner.STATUS_RUNNING
        else None,
        error=row.get("error"),
        created_at=row["created_at"],
        started_at=row.get("started_at"),
        finished_at=row.get("finished_at"),
        has_result=bool(row.get("has_result")),
        result=row.get("result"),
    )


@experiment_router.post(
    "/start",
    summary="Queue a prediction experiment",
    response_model=ExperimentResponse,
)
def start_experiment(
    feed_name_hash: Optional[str] = Query(
        None, description="Replay one feed. Omit to replay every feed you have."
    ),
    mode: str = Query(
        runner.MODE_QUICK,
        description="quick skips the slow models and replays fewer blocks; "
        "full runs everything.",
    ),
    llm_judge: bool = Query(
        False,
        description="Also ask the local analysis model to judge a small sample "
        "of articles. Slow.",
    ),
    user: User = Depends(authenticate),
) -> ExperimentResponse:
    """Queue a replay of your vote history against every prediction method.

    Returns at once. Experiments are worked one at a time in the background,
    survive a restart, and never change how the feed is ranked: poll
    `/experiments/list` to follow one and read `/experiments/get` for its
    result.
    """
    if mode not in runner.MODES:
        raise HTTPException(
            status_code=422, detail=f"mode must be one of {', '.join(runner.MODES)}"
        )
    if feed_name_hash is not None and not Feed.read(
        user_hash=user.name_hash, name_hash=feed_name_hash
    ):
        raise HTTPException(status_code=404, detail="Feed not found")
    experiment_id = runner.enqueue(
        user.name_hash, feed_name_hash, mode=mode, llm_judge=llm_judge
    )
    if experiment_id is None:
        raise HTTPException(
            status_code=429,
            detail=f"You already have {runner.MAX_OPEN_PER_USER} experiments "
            "waiting. Let one finish or cancel it first.",
        )
    return _response(runner.get_experiment(user.name_hash, experiment_id))


@experiment_router.get(
    "/list",
    summary="Your prediction experiments, newest first",
    response_model=ExperimentListResponse,
)
def list_experiments(
    limit: int = Query(20, ge=1, le=100), user: User = Depends(authenticate)
) -> ExperimentListResponse:
    """Status and progress of each experiment, without the results (which are
    large): cheap enough to poll while one runs."""
    return ExperimentListResponse(
        experiments=[
            _response(row) for row in runner.list_experiments(user.name_hash, limit)
        ]
    )


@experiment_router.get(
    "/get",
    summary="One prediction experiment, with its result",
    response_model=ExperimentResponse,
)
def get_experiment(
    experiment_id: int, user: User = Depends(authenticate)
) -> ExperimentResponse:
    row = runner.get_experiment(user.name_hash, experiment_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Experiment not found")
    return _response(row)


@experiment_router.post(
    "/cancel",
    summary="Stop a waiting or running experiment",
    response_model=AcknowledgeResponse,
)
def cancel_experiment(
    experiment_id: int, user: User = Depends(authenticate)
) -> AcknowledgeResponse:
    if not runner.cancel(user.name_hash, experiment_id):
        raise HTTPException(
            status_code=404, detail="No waiting or running experiment with that id"
        )
    return AcknowledgeResponse()


@experiment_router.post(
    "/delete",
    summary="Delete a finished experiment and its result",
    response_model=AcknowledgeResponse,
)
def delete_experiment(
    experiment_id: int, user: User = Depends(authenticate)
) -> AcknowledgeResponse:
    if not runner.delete(user.name_hash, experiment_id):
        raise HTTPException(
            status_code=404,
            detail="No finished experiment with that id (cancel a running one first)",
        )
    return AcknowledgeResponse()
