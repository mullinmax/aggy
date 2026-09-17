from datetime import datetime
from typing import List, Optional

from .base import BaseRouteModel


class TaskRunResponse(BaseRouteModel):
    """One pass of a background job.

    ``duration_seconds`` is measured to now while a pass is still running, so a
    live bar grows rather than having no length at all.
    """

    run_id: int
    kind: str
    # what the pass worked on: a feed name, a source name. Absent for a
    # system-wide pass, which works no single thing.
    target: Optional[str] = None
    status: str
    detail: Optional[str] = None
    started_at: datetime
    finished_at: Optional[datetime] = None
    duration_seconds: float
    # True for a pass that works a global queue rather than this account's
    # articles, so the page can say so instead of implying it ran for you.
    system_wide: bool


class TaskKindSummaryResponse(BaseRouteModel):
    kind: str
    runs: int
    errors: int
    running: int
    system_wide: bool
    last_started_at: Optional[datetime] = None
    # The median rather than the mean: one pathological pass (a source behind a
    # timeout, a first-ever training run on a big feed) drags an average well
    # away from what a typical pass costs.
    median_seconds: Optional[float] = None
    max_seconds: Optional[float] = None


class TaskRunsResponse(BaseRouteModel):
    runs: List[TaskRunResponse]
    kinds: List[TaskKindSummaryResponse]
    total_runs: int
    total_errors: int
    total_running: int
    # The window the rows cover, echoed back so the timeline can scale its axis
    # without having to guess from the rows it happened to get.
    hours: int
    window_start: datetime
    window_end: datetime
    # True when the row limit cut the result short, so the page can say the
    # timeline is incomplete rather than quietly showing part of the window.
    truncated: bool
