from datetime import date, datetime
from typing import List, Optional

from .base import BaseRouteModel


class ArticleCountsResponse(BaseRouteModel):
    """Coverage counts shared by the per-domain rows and the overall summary.

    Counts rather than percentages: the client renders the percentages it wants
    and can still show "17 of 240" underneath them.
    """

    with_preview_image: int
    with_image_embedding: int
    with_text_embedding: int
    with_media: int
    with_content: int
    with_excerpt: int
    with_author: int
    with_date_published: int
    up_votes: int
    down_votes: int
    neutral_votes: int
    # average body length in characters (tags stripped), over the articles
    # that have a body at all
    avg_content_chars: Optional[int] = None
    first_added_at: Optional[datetime] = None
    last_added_at: Optional[datetime] = None


class DomainStatsResponse(ArticleCountsResponse):
    # base domain of the article's own link, e.g. "reddit.com"
    domain: str
    article_count: int


class ArticleStatsSummaryResponse(ArticleCountsResponse):
    total_articles: int
    domain_count: int


class ArticleTimelinePointResponse(BaseRouteModel):
    day: date
    article_count: int
    with_preview_image: int
    with_text_embedding: int
    with_image_embedding: int


class ArticleStatsResponse(BaseRouteModel):
    summary: ArticleStatsSummaryResponse
    domains: List[DomainStatsResponse]
    timeline: List[ArticleTimelinePointResponse]
