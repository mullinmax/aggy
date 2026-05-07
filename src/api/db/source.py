from pydantic import StringConstraints, HttpUrl
from typing_extensions import Annotated
from datetime import datetime

from constants import SOURCE_READ_INTERVAL_TIMEDELTA
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

    @property
    def _items_table(self) -> str:
        return "source_items"

    def _items_filter(self) -> tuple[str, tuple]:
        return (
            "c.user_hash = %s AND c.feed_hash = %s AND c.source_hash = %s",
            (self.user_hash, self.feed_hash, self.name_hash),
        )

    def _collection_keys(self) -> tuple[list[str], tuple]:
        return (
            ["user_hash", "feed_hash", "source_hash"],
            (self.user_hash, self.feed_hash, self.name_hash),
        )

    def exists(self) -> bool:
        with self.db_con() as cur:
            cur.execute(
                "SELECT 1 FROM sources "
                "WHERE user_hash = %s AND feed_hash = %s AND name_hash = %s",
                (self.user_hash, self.feed_hash, self.name_hash),
            )
            return cur.fetchone() is not None

    def create(self):
        if self.exists():
            raise Exception(f"Cannot create duplicate source {self.key}")

        with self.db_con() as cur:
            cur.execute(
                "INSERT INTO sources (user_hash, feed_hash, name_hash, name, url, "
                "next_ingest_at) VALUES (%s, %s, %s, %s, %s, NOW())",
                (
                    self.user_hash,
                    self.feed_hash,
                    self.name_hash,
                    self.name,
                    str(self.url),
                ),
            )

    def delete(self):
        with self.db_con() as cur:
            cur.execute(
                "DELETE FROM sources "
                "WHERE user_hash = %s AND feed_hash = %s AND name_hash = %s",
                (self.user_hash, self.feed_hash, self.name_hash),
            )

    def trigger_ingest(self, now=False):
        if now:
            target = datetime.now()
        else:
            target = datetime.now() + SOURCE_READ_INTERVAL_TIMEDELTA

        # Mirrors the Redis ZADD lt=True semantics: only move next_ingest_at
        # earlier, never later.
        with self.db_con() as cur:
            cur.execute(
                "UPDATE sources SET next_ingest_at = LEAST(next_ingest_at, %s) "
                "WHERE user_hash = %s AND feed_hash = %s AND name_hash = %s",
                (target, self.user_hash, self.feed_hash, self.name_hash),
            )

    @classmethod
    def read(cls, user_hash, feed_hash, source_hash):
        with cls.db_con() as cur:
            cur.execute(
                "SELECT name, url FROM sources "
                "WHERE user_hash = %s AND feed_hash = %s AND name_hash = %s",
                (user_hash, feed_hash, source_hash),
            )
            row = cur.fetchone()

        if row:
            return cls(
                user_hash=user_hash,
                feed_hash=feed_hash,
                name=row["name"],
                url=row["url"],
            )
        raise ValueError("Source not found")

    @classmethod
    def read_by_key(cls, source_key):
        try:
            _, user_hash, _, feed_hash, _, source_hash = source_key.split(":")
        except ValueError:
            return None
        try:
            return cls.read(
                user_hash=user_hash,
                feed_hash=feed_hash,
                source_hash=source_hash,
            )
        except ValueError:
            return None
