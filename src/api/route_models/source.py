from pydantic import HttpUrl

from db.source import Source
from .base import BaseRouteModel


class SourceRouteModel(BaseRouteModel):
    source_name: str
    source_name_hash: str
    source_url: HttpUrl
    source_feed: str

    @classmethod
    def from_db_model(cls, db_model: Source):
        return cls(
            source_name=db_model.name,
            source_name_hash=db_model.name_hash,
            source_url=db_model.url,
            source_feed=db_model.feed_hash,
        )
