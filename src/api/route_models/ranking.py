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
