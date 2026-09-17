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
    # articles whose preview image the embedder has given up on after repeated
    # failed fetches -- the part of the image-embedding gap that will not close
    # on its own, as opposed to the part still queued up
    image_embed_failed: int
    with_text_embedding: int
    with_media: int
    with_content: int
    with_excerpt: int
    with_author: int
    with_date_published: int
    up_votes: int
    down_votes: int
    neutral_votes: int
    # articles that are one of several copies of the same content the user has
    # collected -- counted only where they hold two or more copies, since
    # detection is global and a group often has members in nobody else's feeds
    in_duplicate_group: int
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
    # Group-level duplicate numbers, which are summary-only: copies are grouped
    # by canonical URL and can arrive under different hosts, so a group does not
    # belong to any one base domain and these cannot be folded up per domain.
    #
    # duplicated_articles counts every copy; redundant_articles is how many of
    # them the feed collapses away, which is the number that says whether
    # duplicate detection is earning its keep.
    duplicate_groups: int
    duplicated_articles: int
    redundant_articles: int
    largest_duplicate_group: int


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
