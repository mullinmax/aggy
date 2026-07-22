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


class FieldExampleResponse(BaseRouteModel):
    url_hash: str
    title: Optional[str] = None
    image_url: Optional[str] = None
    source: Optional[str] = None
    excerpt: Optional[str] = None
    # substitute score minus baseline: >0 the model scores this value higher
    # than the article's own, <0 lower
    delta: float


class FieldContributionResponse(BaseRouteModel):
    field: str
    label: str
    # -1 drags the predicted score down, 0 no measurable effect, +1 pushes up
    sign: int
    # number of marks to show: 0, 1, or 2
    level: int
    # one-sentence description of what this field feeds the model
    description: str = ""
    # other articles the model scored higher / lower on this field
    better: List[FieldExampleResponse] = []
    worse: List[FieldExampleResponse] = []


class ItemExplanationResponse(BaseRouteModel):
    model_config = {"protected_namespaces": ()}

    model_name: str
    baseline_score: float
    fields: List[FieldContributionResponse]
