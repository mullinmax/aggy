from .base import BaseRouteModel
from typing import Dict


class FeedFromTemplate(BaseRouteModel):
    feed_template_name_hash: str
    category_hash: str
    feed_name: str
    parameters: Dict[str, str]

    model_config = {
        "json_schema_extra": {
            "example": {
                "feed_template_name_hash": "example_hash_123",
                "category_hash": "category_hash_456",
                "feed_name": "Example Feed Name",
                "parameters": {"parameter_name": "value"},
            }
        }
    }
