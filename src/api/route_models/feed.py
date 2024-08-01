from pydantic import HttpUrl

from db.feed import Feed
from .base import BaseRouteModel


class FeedRouteModel(BaseRouteModel):
    feed_name: str
    feed_name_hash: str
    feed_url: HttpUrl
    feed_category: str

    @classmethod
    def from_db_model(cls, db_model: Feed):
        return cls(
            feed_name=db_model.name,
            feed_name_hash=db_model.name_hash,
            feed_url=db_model.url,
            feed_category=db_model.category_hash,
        )
