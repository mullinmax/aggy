from pydantic import StringConstraints, HttpUrl
from typing_extensions import Annotated
from datetime import datetime

from constants import SOURCES_TO_INGEST_KEY, SOURCE_READ_INTERVAL_TIMEDELTA
from .item_collection import ItemCollection


class Source(ItemCollection):
    user_hash: str
    feed_hash: str
    name: Annotated[str, StringConstraints(strict=True, min_length=1)]
    url: HttpUrl

    @property
    def name_hash(self):
        return self.__insecure_hash__(self.name)

    @property
    def key(self):
        return f"USER:{self.user_hash}:FEED:{self.feed_hash}:SOURCE:{self.name_hash}"

    @property
    def items_key(self):
        return f"{self.key}:ITEMS"

    def create(self):
        with self.db_con() as r:
            if r.exists(self.key):
                raise Exception(f"Cannot create duplicate source {self.key}")

            r.hset(self.key, mapping={"url": str(self.url), "name": self.name})
            self.trigger_ingest(now=True)
        return

    def delete(self):
        with self.db_con() as r:
            r.delete(self.key)
            r.delete(self.items_key)

    def trigger_ingest(self, now=False):
        # if the source is not already in the list
        # we're assuming it's over due to ingest
        if now:
            score = int(datetime.now().timestamp())
        else:
            score = datetime.now() + SOURCE_READ_INTERVAL_TIMEDELTA
            score = int((score).timestamp())

        with self.db_con() as r:
            # lt=True means that if the source is already in the list
            # it will only be updated if the new score is lower
            r.zadd(SOURCES_TO_INGEST_KEY, mapping={self.key: score}, lt=True)

    @classmethod
    def read(cls, user_hash, feed_hash, source_hash):
        source_key = f"USER:{user_hash}:FEED:{feed_hash}:SOURCE:{source_hash}"
        source = cls.read_by_key(source_key)

        if source:
            return source

        raise ValueError("Source not found")

    @classmethod
    def read_by_key(cls, source_key):
        with cls.db_con() as r:
            if r.exists(source_key):
                source_data = r.hgetall(source_key)
                _, user_hash, _, feed_hash, _, source_hash = source_key.split(":")
                return Source(user_hash=user_hash, feed_hash=feed_hash, **source_data)
        return None
