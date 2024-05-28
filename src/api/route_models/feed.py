from pydantic import HttpUrl

from db.feed import Feed
from .base import BaseRouteModel


class FeedResponse(BaseRouteModel):
    name: str
    name_hash: str
    feed_url: HttpUrl
    feed_category: str

    @classmethod
    def from_db_model(cls, db_model: Feed):
        return cls(
            name=db_model.name,
            name_hash=db_model.name_hash,
            feed_url=db_model.url,
            feed_category=db_model.category_hash,
        )
