"""The duplicate review queue, as the review page works through it."""

from typing import List, Optional

from .base import BaseRouteModel
from .item import ItemResponse


class ReviewPairResponse(BaseRouteModel):
    """Two articles to judge, as the feed's own cards draw them.

    Full ``ItemResponse`` on both sides rather than a summary, because the
    question is whether these are the same story and half the answer is in the
    picture and the body. A reduced shape carrying only ``image_url`` showed
    nothing at all for an article whose picture lives in its content or in a
    media attachment, which is most of them from some sources.
    """

    # Which side detection treats as the anchor. For a collapsed pair that is
    # the group's representative, and the candidate is the member that would
    # leave if you reject it.
    anchor: ItemResponse
    candidate: ItemResponse
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
