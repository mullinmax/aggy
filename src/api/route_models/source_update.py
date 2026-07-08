from typing import Dict, Optional

from .base import BaseRouteModel


class SourceUpdate(BaseRouteModel):
    feed_name_hash: str
    source_name_hash: str
    source_name: str
    # Manual sources: a new feed URL. Ignored for template sources.
    source_url: Optional[str] = None
    # Template sources: new parameter values; the URL is rebuilt from the
    # source's template.
    parameters: Optional[Dict[str, str]] = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "feed_name_hash": "feed_hash_456",
                "source_name_hash": "source_hash_789",
                "source_name": "Example Source Name",
                "source_url": "https://example.com/rss.xml",
                "parameters": {"parameter_name": "value"},
            }
        }
    }
