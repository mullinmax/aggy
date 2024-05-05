from pydantic import StringConstraints, HttpUrl
from typing_extensions import Annotated
from typing import List

from .base import BlinderBaseModel
from config import config
from .item import ItemStrict


class Feed(BlinderBaseModel):
    user_hash: str
    category_hash: str
    name: Annotated[str, StringConstraints(strict=True, min_length=1)]
    url: HttpUrl

    @property
    def name_hash(self):
        return self.__insecure_hash__(self.name)

    @property
    def key(self):
        return (
            f"USER:{self.user_hash}:CATEGORY:{self.category_hash}:FEED:{self.name_hash}"
        )

    @property
    def feed_items_key(self):
        return f"{self.key}:ITEMS"

    @property
    def items(self) -> List[ItemStrict]:
        items = []
        with self.redis_con() as r:
            for item_url_hash in r.smembers(self.feed_items_key):
                try:
                    items.append(ItemStrict.read(url_hash=item_url_hash))
                except Exception:
                    pass
        return items

    def create(self):
        with self.redis_con() as r:
            if r.exists(self.key):
                raise Exception(f"Cannot create duplicate feed {self.key}")

            (r.hset(self.key, mapping={"url": str(self.url), "name": self.name}),)
            self.trigger_ingest(skip_line=True)
        return

    def trigger_ingest(self, skip_line=False):
        with self.redis_con() as r:
            r.zadd(
                config.get("FEEDS_TO_INGEST_KEY"), mapping={self.key: 0}, lt=skip_line
            )

    @classmethod
    def read(cls, user_hash, category_hash, feed_hash):
        feed_key = f"USER:{user_hash}:CATEGORY:{category_hash}:FEED:{feed_hash}"
        return cls.read_by_key(feed_key)

    @classmethod
    def read_by_key(cls, feed_key):
        with cls.redis_con() as r:
            if r.exists(feed_key):
                feed_data = r.hgetall(feed_key)
                _, user_hash, _, category_hash, _, feed_hash = feed_key.split(":")
                return Feed(
                    user_hash=user_hash, category_hash=category_hash, **feed_data
                )
        return None

    def add_items(self, items: ItemStrict):
        with self.redis_con() as r:
            if isinstance(items, ItemStrict):
                items = [items]
            for item in items:
                r.sadd(self.feed_items_key, item.url_hash)

    def count_items(self):
        with self.redis_con() as r:
            return r.scard(self.feed_items_key)
