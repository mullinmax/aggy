from fastapi import APIRouter, Depends, Query

from db.stats import article_stats
from db.user import User
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
