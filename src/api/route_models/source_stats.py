from datetime import date, datetime
from typing import List, Optional

from .base import BaseRouteModel


class HostReliabilityResponse(BaseRouteModel):
    # registrable domain the sources fetch from, e.g. "youtube.com"
    host: str
    # how many of this user's sources point at the host
    source_count: int
    # attempts that actually contacted the host -- skips are counted separately
    # so the breaker holding a dead site back doesn't flatter its error rate
    attempts: int
    successes: int
    failures: int
    skipped: int
    # failures / attempts, or null when every attempt was skipped
    error_rate: Optional[float] = None
    last_success_at: Optional[datetime] = None
    last_failure_at: Optional[datetime] = None
    last_error: Optional[str] = None
    # whether the circuit breaker is currently holding this host's sources back
    in_cooldown: bool
    cooldown_seconds_remaining: Optional[int] = None


class SourceStatsSummaryResponse(BaseRouteModel):
    host_count: int
    attempts: int
    failures: int
    skipped: int
    error_rate: Optional[float] = None
    hosts_in_cooldown: int


class AttemptTimelinePointResponse(BaseRouteModel):
    day: date
    attempts: int
    failures: int
    skipped: int
    error_rate: Optional[float] = None


class SourceStatsResponse(BaseRouteModel):
    summary: SourceStatsSummaryResponse
    hosts: List[HostReliabilityResponse]
    timeline: List[AttemptTimelinePointResponse]
    # length of the window these numbers cover, in days
    days: int
