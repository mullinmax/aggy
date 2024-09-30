from .base import BaseRouteModel

from db.feed import Feed


class FeedResponse(BaseRouteModel):
    feed_name: str
    feed_name_hash: str

    model_config = {
        "json_schema_extra": {
            "example": {
                "feed_name": "Technology",
                "feed_name_hash": "982d98h98hf1uhfdi1sdhu",
            }
        }
    }

    @classmethod
    def from_db_model(cls, db_model: Feed):
        return cls(feed_name=db_model.name, feed_name_hash=db_model.name_hash)
