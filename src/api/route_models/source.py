from datetime import datetime
from typing import Optional

from pydantic import HttpUrl

from db.source import Source
from .base import BaseRouteModel


class SourceRouteModel(BaseRouteModel):
    source_name: str
    source_name_hash: str
    source_url: HttpUrl
    source_feed: str
    source_item_count: int = 0
    source_last_ingested_at: Optional[datetime] = None

    @classmethod
    def from_db_model(cls, db_model: Source):
        return cls(
            source_name=db_model.name,
            source_name_hash=db_model.name_hash,
            source_url=db_model.url,
            source_feed=db_model.feed_hash,
        )

    @classmethod
    def from_stats_row(cls, feed_hash: str, row: dict):
        return cls(
            source_name=row["name"],
            source_name_hash=row["name_hash"],
            source_url=row["url"],
            source_feed=feed_hash,
            source_item_count=row["item_count"],
            source_last_ingested_at=row["last_ingested_at"],
        )
