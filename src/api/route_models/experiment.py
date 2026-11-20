from datetime import datetime
from typing import List, Optional

from .base import BaseRouteModel


class ExperimentProgressResponse(BaseRouteModel):
    """Where a running experiment has got to."""

    feed: int
    feeds: int
    block: int
    blocks: int
    # the method being fitted right now
    method: Optional[str] = None
    # 0..1 over the whole run
    fraction: float = 0.0


class ExperimentResponse(BaseRouteModel):
    experiment_id: int
    # queued, running, done, error or cancelled
    status: str
    # quick or full
    mode: str
    llm_judge: bool = False
    # None for a run over every feed
    feed_name_hash: Optional[str] = None
    # experiments waiting ahead of this one (they run one at a time)
    queued_ahead: int = 0
    progress: Optional[ExperimentProgressResponse] = None
    error: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    has_result: bool = False
    # Aggregate scores only: no titles, URLs, source names or embeddings, so it
    # can be copied out of the app. Only present on `/experiments/get`.
    result: Optional[dict] = None


class ExperimentListResponse(BaseRouteModel):
    experiments: List[ExperimentResponse]


class ItemOpenResponse(BaseRouteModel):
    open_id: int
