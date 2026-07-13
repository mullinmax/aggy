from enum import Enum
from typing import Dict, List, Optional

from .base import BaseRouteModel


class ImportPlatform(str, Enum):
    reddit = "reddit"
    youtube = "youtube"
    opml = "opml"
    bluesky = "bluesky"


class ImportParseRequest(BaseRouteModel):
    platform: ImportPlatform
    # Export-file content or pasted text (reddit/youtube/opml).
    data: Optional[str] = None
    # Account handle (bluesky).
    username: Optional[str] = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "platform": "reddit",
                "data": "r/selfhosted\nr/alligators",
            }
        }
    }


class ImportCandidateResponse(BaseRouteModel):
    name: str
    url: Optional[str] = None
    group: Optional[str] = None
    template_name_hash: Optional[str] = None
    template_parameters: Optional[Dict[str, str]] = None
    error: Optional[str] = None


class ImportParseResponse(BaseRouteModel):
    candidates: List[ImportCandidateResponse]
    warnings: List[str] = []


class BulkSourceRequest(BaseRouteModel):
    feed_name_hash: str
    source_name: str
    # Either a raw URL or a template reference (template wins when both set).
    source_url: Optional[str] = None
    template_name_hash: Optional[str] = None
    template_parameters: Optional[Dict[str, str]] = None


class BulkCreateRequest(BaseRouteModel):
    sources: List[BulkSourceRequest]

    model_config = {
        "json_schema_extra": {
            "example": {
                "sources": [
                    {
                        "feed_name_hash": "feed_hash_456",
                        "source_name": "r/selfhosted",
                        "template_name_hash": "template_hash_123",
                        "template_parameters": {"subreddit": "selfhosted"},
                    }
                ]
            }
        }
    }


class BulkCreateResultStatus(str, Enum):
    created = "created"
    duplicate = "duplicate"
    error = "error"


class BulkCreateResult(BaseRouteModel):
    source_name: str
    feed_name_hash: str
    status: BulkCreateResultStatus
    detail: Optional[str] = None


class BulkCreateResponse(BaseRouteModel):
    results: List[BulkCreateResult]
    created: int
    duplicates: int
    errors: int
