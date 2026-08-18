from fastapi import APIRouter, Depends, Query

from db.source_attempt import source_stats
from db.stats import article_stats
from db.user import User
from route_models.source_stats import (
    AttemptTimelinePointResponse,
    HostReliabilityResponse,
    SourceStatsResponse,
    SourceStatsSummaryResponse,
)
from route_models.stats import (
    ArticleStatsResponse,
    ArticleStatsSummaryResponse,
    ArticleTimelinePointResponse,
    DomainStatsResponse,
)
from routers.auth import authenticate

stats_router = APIRouter()


@stats_router.get(
    "/articles",
    summary="Summary stats for every article the user has collected",
    response_model=ArticleStatsResponse,
)
def get_article_stats(
    timeline_days: int = Query(
        30, ge=1, le=365, description="Length of the daily timeline, in days"
    ),
    user: User = Depends(authenticate),
) -> ArticleStatsResponse:
    stats = article_stats(user.name_hash, timeline_days=timeline_days)
    return ArticleStatsResponse(
        summary=ArticleStatsSummaryResponse(**stats["summary"]),
        domains=[DomainStatsResponse(**row) for row in stats["domains"]],
        timeline=[ArticleTimelinePointResponse(**row) for row in stats["timeline"]],
    )


@stats_router.get(
    "/sources",
    summary="How reliably each site has been answering this user's sources",
    response_model=SourceStatsResponse,
)
def get_source_stats(
    days: int = Query(
        7, ge=1, le=90, description="Length of the window to report on, in days"
    ),
    user: User = Depends(authenticate),
) -> SourceStatsResponse:
    stats = source_stats(user.name_hash, days=days)
    return SourceStatsResponse(
        summary=SourceStatsSummaryResponse(**stats["summary"]),
        hosts=[HostReliabilityResponse(**row) for row in stats["hosts"]],
        timeline=[AttemptTimelinePointResponse(**row) for row in stats["timeline"]],
        days=stats["days"],
    )
