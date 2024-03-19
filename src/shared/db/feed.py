from pydantic import StringConstraints, HttpUrl
import hashlib

from .base import BlinderBaseModel
from src.shared.config import config
from typing_extensions import Annotated


class Feed(BlinderBaseModel):
    user_hash: str
    category_hash: str
    name: Annotated[str, StringConstraints(strict=True, min_length=1)]
    url: HttpUrl

    @property
    def name_hash(self):
        return hashlib.sha256(self.name.encode()).hexdigest()

    @property
    def key(self):
        return (
            f"USER:{self.user_hash}:CATEGORY:{self.category_hash}:FEED:{self.name_hash}"
        )

    def create(self):
        with self.redis_con() as r:
            if r.exists(self.key):
                raise Exception(f"Cannot create duplicate feed {self.key}")

            (r.hset(self.key, mapping={"url": str(self.url), "name": self.name}),)
            self.trigger_update()
        return

    def trigger_update(self):
        with self.redis_con() as r:
            r.zadd(config.get("FEEDS_TO_INGEST_KEY"), mapping={self.key: 0})

    @classmethod
    def read(cls, user_hash, category_hash, feed_hash):
        feed_key = f"USER:{user_hash}:CATEGORY:{category_hash}:FEED:{feed_hash}"
        with cls.redis_con() as r:
            if r.exists(feed_key):
                feed_data = r.hgetall(feed_key)
                return Feed(
                    user_hash=user_hash, category_hash=category_hash, **feed_data
                )
        return None
