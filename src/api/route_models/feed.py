from typing import Optional

from .base import BaseRouteModel

from db.feed import Feed


class FeedResponse(BaseRouteModel):
    feed_name: str
    feed_name_hash: str
    # Summary stats, filled in by /feed/list for the dashboard cards.
    feed_item_count: Optional[int] = None
    feed_unread_count: Optional[int] = None
    feed_posts_per_day: Optional[float] = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "feed_name": "Technology",
                "feed_name_hash": "982d98h98hf1uhfdi1sdhu",
            }
        }
    }

    @classmethod
    def from_db_model(cls, db_model: Feed, stats: dict = None):
        return cls(
            feed_name=db_model.name,
            feed_name_hash=db_model.name_hash,
            **(stats or {}),
        )
