from datetime import datetime
from typing import List, Optional

from .base import BaseRouteModel


class ModelStatsResponse(BaseRouteModel):
    # "model_name" trips pydantic's protected "model_" namespace; allow it
    model_config = {"protected_namespaces": ()}

    model_name: str
    n_labels: int
    mae: Optional[float] = None
    rmse: Optional[float] = None
    sign_accuracy: Optional[float] = None
    chosen: bool = False
    computed_at: Optional[datetime] = None


class TrainingProgressResponse(BaseRouteModel):
    """A training run in flight, or the one that just finished."""

    model_config = {"protected_namespaces": ()}

    # running, done or error
    status: str
    # evaluating (cross-validating the zoo), training (fitting the winner on
    # every vote) or predicting (writing its scores back to the feed)
    phase: str
    # the model being worked on right now, when there is one
    model_name: Optional[str] = None
    step: int
    total_steps: int
    elapsed_seconds: float = 0.0
    error: Optional[str] = None


class TrainingStatusResponse(BaseRouteModel):
    """Everything the UI needs to describe the state of a feed's models
    without pulling the full per-model stats table."""

    model_config = {"protected_namespaces": ()}

    # null when no run has happened (or finished) recently
    training: Optional[TrainingProgressResponse] = None
    last_trained_at: Optional[datetime] = None
    # the model the last training run picked, and how many votes it learned from
    trained_model: Optional[str] = None
    trained_labels: int = 0
    # votes cast since that run — how far behind the live predictions are
    votes_since_training: int = 0


class RankingStatsResponse(TrainingStatusResponse):
    models: List[ModelStatsResponse]
    up_votes: int
    down_votes: int
    neutral_votes: int
    total_items: int
    predicted_items: int


class FieldPreviewResponse(BaseRouteModel):
    # this article's own value for the field, so the UI can show exactly what
    # was evaluated (only the piece relevant to the field is displayed)
    text: Optional[str] = None
    image_url: Optional[str] = None
    source: Optional[str] = None
    author: Optional[str] = None
    date_published: Optional[datetime] = None
    has_image: bool = False
    has_media: bool = False
    # whether the image is scored by a real vision embedding vs presence only
    image_embedded: bool = False


class FieldContributionResponse(BaseRouteModel):
    field: str
    label: str
    # -1 drags the predicted score down, 0 no measurable effect, +1 pushes up
    sign: int
    # number of marks to show: 0, 1, or 2
    level: int
    # one-sentence description of what this field feeds the model
    description: str = ""
    # this article's own value for the field (what was evaluated)
    preview: Optional[FieldPreviewResponse] = None


class ItemExplanationResponse(BaseRouteModel):
    model_config = {"protected_namespaces": ()}

    model_name: str
    baseline_score: float
    fields: List[FieldContributionResponse]
