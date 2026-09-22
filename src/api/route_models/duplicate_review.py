"""The duplicate review queue, as the review page works through it."""

from datetime import datetime
from typing import List, Optional

from pydantic import HttpUrl

from .base import BaseRouteModel


class ReviewArticleResponse(BaseRouteModel):
    """One side of a pair: enough to recognise an article without opening it."""

    item_hash: str
    item_url: HttpUrl
    item_title: Optional[str] = None
    item_excerpt: Optional[str] = None
    item_author: Optional[str] = None
    item_source_name: Optional[str] = None
    item_image_url: Optional[str] = None
    item_date_published: Optional[datetime] = None


class ReviewPairResponse(BaseRouteModel):
    # Which side detection treats as the anchor. For a collapsed pair that is
    # the group's representative, and the candidate is the member that would
    # leave if you reject it.
    anchor: ReviewArticleResponse
    candidate: ReviewArticleResponse
    # True when the feed is already collapsing these two, so the page can ask
    # the right question: "was this right?" rather than "are these the same?"
    grouped: bool
    # What put them in a group, when something did: canonical_url, text
    # embedding, or your own earlier confirmation.
    signal: Optional[str] = None
    similarity: float


class DuplicateModelResponse(BaseRouteModel):
    """Where the model stands, which is mostly a count until it exists."""

    confirmed: int
    rejected: int
    # How many labels before a model replaces the hand-picked threshold.
    needed: int
    trained: bool
    # Cross-validated, so it is a claim about pairs the model has not seen.
    # Null when there are too few of either answer to hold a fold out.
    accuracy: Optional[float] = None
    # Which signals actually separated your answers, strongest first. Scaled
    # coefficients, so they are comparable to each other.
    coefficients: List[List] = []


class DuplicateReviewResponse(BaseRouteModel):
    pairs: List[ReviewPairResponse]
    model: DuplicateModelResponse


class DuplicateVerdictResponse(BaseRouteModel):
    # What the verdict did to the feed: split, grouped, or unchanged.
    outcome: str
    model: DuplicateModelResponse
