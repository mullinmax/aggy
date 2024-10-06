from pydantic import StringConstraints, HttpUrl
from typing_extensions import Annotated

from .item_collection import ItemCollection
from utils import schedule
from constants import SOURCE_READ_INTERVAL_TIMEDELTA, SOURCES_TO_INGEST_QUEUE


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

            # make sure this new source gets ingested right away
            schedule(
                queue=SOURCES_TO_INGEST_QUEUE,
                key=self.key,
                interval=SOURCE_READ_INTERVAL_TIMEDELTA,
                now=True,
            )
        return

    def delete(self):
        with self.db_con() as r:
            r.delete(self.key)
            r.delete(self.items_key)

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
