from pydantic import StringConstraints
from typing import List, Optional
from typing_extensions import Annotated

from .item_collection import ItemCollection
from .feed import Feed


# TODO write unit test that ensures we are using hashes where we should be
# (ie. user_hash, name_hash, etc. should be so many characters and of a certain set)
class Category(ItemCollection):
    user_hash: str
    name: Annotated[str, StringConstraints(strict=True, min_length=1)]

    @property
    def key(self):
        return f"USER:{self.user_hash}:CATEGORY:{self.name_hash}"

    @property
    def feeds_key(self):
        return f"{self.key}:FEEDS"

    @property
    def name_hash(self):
        return self.__insecure_hash__(self.name)

    @property
    def feed_hashes(self):
        with self.db_con() as r:
            return list(r.smembers(self.feeds_key))

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

    @property
    def items_key(self):
        return f"{self.key}:ITEMS"

    def create(self):
        with self.db_con() as r:
            if self.exists():
                raise Exception(f"Category with name {self.name} already exists")

            r.hset(self.key, mapping={"name": self.name})
            r.sadd(f"USER:{self.user_hash}:CATEGORIES", self.name_hash)

        return self.key

    def delete(self):
        with self.db_con() as r:
            # remove category from list of user's categories
            r.srem(f"USER:{self.user_hash}:CATEGORIES", self.name_hash)

            # delete each feed then remove list
            for feed_hash in self.feed_hashes:
                try:
                    feed = Feed.read(
                        user_hash=self.user_hash,
                        category_hash=self.name_hash,
                        feed_hash=feed_hash,
                    )
                    feed.delete()
                except ValueError:
                    # feed does not exist
                    pass
            r.delete(self.feeds_key)

            # delete list of category items
            r.delete(f"{self.key}:ITEMS")

            # delete self
            r.delete(self.key)

    @classmethod
    def read(cls, user_hash, name_hash) -> Optional["Category"]:
        key = f"USER:{user_hash}:CATEGORY:{name_hash}"
        with cls.db_con() as r:
            category_data = r.hgetall(key)

        if category_data:
            category_data["name_hash"] = name_hash
            category_data["user_hash"] = user_hash
            return Category(**category_data)

        return None

    @classmethod
    def read_all(cls, user_hash) -> List["Category"]:
        with cls.db_con() as r:
            category_name_hashs = r.smembers(f"USER:{user_hash}:CATEGORIES")

        categories = []
        for name_hash in category_name_hashs:
            categories.append(cls.read(user_hash=user_hash, name_hash=name_hash))

        return categories

    def add_feed(self, feed: Feed):
        with self.db_con() as r:
            feed.user_hash = self.user_hash
            feed.category_hash = self.name_hash
            if not feed.exists():
                feed.create()
            r.sadd(f"{self.key}:FEEDS", feed.name_hash)

    def delete_feed(self, feed: Feed):
        with self.db_con() as r:
            feed.delete()
            r.srem(f"{self.key}:FEEDS", feed.name_hash)
