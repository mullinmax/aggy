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


class RankingStatsResponse(BaseRouteModel):
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
