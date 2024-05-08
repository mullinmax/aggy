from pydantic import HttpUrl

from db.feed import Feed
from .base import BaseResponseModel


class FeedResponse(BaseResponseModel):
    name: str
    name_hash: str
    feed_url: HttpUrl
    feed_description: str
    feed_category: str

    @classmethod
    def from_db_model(cls, db_model: Feed):
        return cls(
            name=db_model.name,
            name_hash=db_model.name_hash,
            feed_url=db_model.url,
            feed_description=db_model.description,
            feed_category=db_model.category_hash,
        )
