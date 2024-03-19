from pydantic import StringConstraints
from typing import List
import hashlib
from typing_extensions import Annotated

from .base import BlinderBaseModel
from .item import ItemStrict
from .feed import Feed


class Category(BlinderBaseModel):
    user_hash: str
    name: Annotated[str, StringConstraints(strict=True, min_length=1)]

    @property
    def key(self):
        return f"USER:{self.user_hash}:CATEGORY:{self.name_hash}"

    @property
    def items_key(self):
        return f"{self.key}:ITEMS"

    @property
    def feeds_key(self):
        return f"{self.key}:FEEDS"

    @property
    def name_hash(self):
        return hashlib.sha256(self.name.encode()).hexdigest()

    @property
    def feed_hashes(self):
        with self.redis_con() as r:
            return list(r.smembers(f"{self.feeds_key}"))

    @property
    def feeds(self) -> List[Feed]:
        return [
            Feed.read(
                user_hash=self.user_hash,
                category_hash=self.name_hash,
                feed_hash=feed_hash,
            )
            for feed_hash in self.feed_hashes
        ]

    def create(self):
        with self.redis_con() as r:
            if self.exists():
                raise Exception(f"Category with name {self.name} already exists")

            r.hset(self.key, mapping={"name": self.name})
            r.sadd(f"USER:{self.user_hash}:CATEGORIES", self.name_hash)

        return self.key

    def delete(self):
        with self.redis_con() as r:
            # remove category from list of user's categories
            r.srem(f"USER:{self.user_hash}:CATEGORIES", self.name_hash)

            # delete each feed then remove list
            for feed_hash in self.feed_hashes:
                feed = Feed.read(
                    user_hash=self.user_hash,
                    category_hash=self.name_hash,
                    feed_hash=feed_hash,
                )
                feed.delete()
            r.delete(self.feeds_key)

            # delete list of category items
            r.delete(f"{self.key}:ITEMS")

            # delete self
            r.delete(self.key)

    @classmethod
    def read(cls, user_hash, name_hash):
        with cls.redis_con() as r:
            category_data = r.hgetall(f"USER:{user_hash}:CATEGORY:{name_hash}")

        if category_data:
            return Category(name_hash=name_hash, user_hash=user_hash, **category_data)
        else:
            raise Exception("Category does not exist")

    @classmethod
    def read_all(cls, user_hash) -> List["Category"]:
        with cls.redis_con() as r:
            category_name_hashs = r.smembers(f"USER:{user_hash}:CATEGORIES")

        categories = []
        for name_hash in category_name_hashs:
            categories.append(cls.read(user_hash, name_hash))
        return categories

    def get_all_items(self):
        with self.redis_con() as r:
            url_hashes = r.zrange(self.items_key, 0, -1)

        items = [ItemStrict.read(url_hash) for url_hash in url_hashes]
        items = [i for i in items if i]
        return items

    def add_feed(self, feed: Feed):
        with self.redis_con() as r:
            feed.user_hash = self.user_hash
            feed.category_hash = self.name_hash
            if not feed.exists():
                feed.create()
            r.sadd(f"{self.key}:FEEDS", feed.name_hash)

    def delete_feed(self, feed: Feed):
        with self.redis_con() as r:
            feed.delete()
            r.srem(f"{self.key}:FEEDS", feed.name_hash)
