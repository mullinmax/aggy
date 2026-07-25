from datetime import datetime
from typing import Dict, Optional

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
    source_last_ingest_error: Optional[str] = None
    source_template_name_hash: Optional[str] = None
    source_template_parameters: Optional[Dict[str, str]] = None
    source_ingest_interval_minutes: Optional[int] = None
    source_color: Optional[str] = None
    # Set when this source mirrors another feed instead of an RSS URL.
    source_feed_hash: Optional[str] = None
    source_feed_name: Optional[str] = None
    # Which ingest backend reads this source: "rss", "ytdlp", or "html".
    source_kind: str = "rss"

    @classmethod
    def from_db_model(cls, db_model: Source):
        return cls(
            source_name=db_model.name,
            source_name_hash=db_model.name_hash,
            source_url=db_model.url,
            source_feed=db_model.feed_hash,
            source_template_name_hash=db_model.template_name_hash,
            source_template_parameters=db_model.template_parameters,
            source_ingest_interval_minutes=db_model.ingest_interval_minutes,
            source_color=db_model.color,
            source_feed_hash=db_model.source_feed_hash,
            source_kind=db_model.kind,
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
            source_last_ingest_error=row["last_ingest_error"],
            source_template_name_hash=row.get("template_name_hash"),
            source_template_parameters=row.get("template_parameters"),
            source_ingest_interval_minutes=row.get("ingest_interval_minutes"),
            source_color=row.get("color"),
            source_feed_hash=row.get("source_feed_hash"),
            source_feed_name=row.get("source_feed_name"),
            source_kind=row.get("kind") or "rss",
        )
