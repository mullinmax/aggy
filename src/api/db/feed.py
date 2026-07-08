from pydantic import StringConstraints
from typing import List, Optional
from typing_extensions import Annotated

from .item_collection import ItemCollection


class Feed(ItemCollection):
    user_hash: str
    name: Annotated[str, StringConstraints(strict=True, min_length=1)]

    @property
    def key(self):
        return f"USER:{self.user_hash}:FEED:{self.name_hash}"

    @property
    def sources_key(self):
        return f"{self.key}:SOURCES"

    @property
    def items_key(self):
        return f"{self.key}:ITEMS"

    @property
    def name_hash(self):
        return self.__insecure_hash__(self.name)

    @property
    def _items_table(self) -> str:
        return "feed_items"

    def _items_filter(self) -> tuple[str, tuple]:
        return (
            "c.user_hash = %s AND c.feed_hash = %s",
            (self.user_hash, self.name_hash),
        )

    def _collection_keys(self) -> tuple[list[str], tuple]:
        return (["user_hash", "feed_hash"], (self.user_hash, self.name_hash))

    @property
    def source_hashes(self) -> List[str]:
        with self.db_con() as cur:
            cur.execute(
                "SELECT name_hash FROM sources "
                "WHERE user_hash = %s AND feed_hash = %s",
                (self.user_hash, self.name_hash),
            )
            return [row["name_hash"] for row in cur.fetchall()]

    @property
    def sources(self):
        # Local import to avoid a circular dependency at module load time.
        from .source import Source

        with self.db_con() as cur:
            cur.execute(
                "SELECT user_hash, feed_hash, name_hash, name, url FROM sources "
                "WHERE user_hash = %s AND feed_hash = %s",
                (self.user_hash, self.name_hash),
            )
            rows = cur.fetchall()

        return [
            Source(
                user_hash=row["user_hash"],
                feed_hash=row["feed_hash"],
                name=row["name"],
                url=row["url"],
            )
            for row in rows
        ]

    def sources_with_stats(self) -> List[dict]:
        """Sources in this feed plus item count and last ingest time."""
        with self.db_con() as cur:
            cur.execute(
                "SELECT s.name, s.url, s.name_hash, s.feed_hash, s.last_ingested_at, "
                "s.last_ingest_error, s.template_name_hash, s.template_parameters, "
                "(SELECT COUNT(*) FROM source_items si "
                " WHERE si.user_hash = s.user_hash AND si.feed_hash = s.feed_hash "
                " AND si.source_hash = s.name_hash) AS item_count "
                "FROM sources s WHERE s.user_hash = %s AND s.feed_hash = %s "
                "ORDER BY s.name",
                (self.user_hash, self.name_hash),
            )
            return cur.fetchall()

    def query_items_with_sources(self, skip=None, limit=None):
        """Like ``query_items`` but pairs each item with the name of a source
        in this feed that produced it (None if untracked)."""
        from .item import ItemStrict

        sql = (
            "SELECT i.*, ("
            " SELECT s.name FROM source_items si"
            " JOIN sources s ON s.user_hash = si.user_hash"
            "  AND s.feed_hash = si.feed_hash AND s.name_hash = si.source_hash"
            " WHERE si.user_hash = c.user_hash AND si.feed_hash = c.feed_hash"
            "  AND si.item_url_hash = c.item_url_hash LIMIT 1) AS source_name "
            "FROM items i "
            "JOIN feed_items c ON c.item_url_hash = i.url_hash "
            "WHERE c.user_hash = %s AND c.feed_hash = %s "
            "ORDER BY c.score DESC, c.added_at DESC"
        )
        params: tuple = (self.user_hash, self.name_hash)
        if limit is not None and limit >= 0:
            sql += " LIMIT %s"
            params = params + (limit,)
        if skip is not None and skip > 0:
            sql += " OFFSET %s"
            params = params + (skip,)

        with self.db_con() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

        results = []
        for row in rows:
            if not row:
                continue
            source_name = row.pop("source_name", None)
            results.append((ItemStrict.from_row(row), source_name))
        return results

    def exists(self) -> bool:
        with self.db_con() as cur:
            cur.execute(
                "SELECT 1 FROM feeds WHERE user_hash = %s AND name_hash = %s",
                (self.user_hash, self.name_hash),
            )
            return cur.fetchone() is not None

    def create(self):
        if self.exists():
            raise Exception(f"Feed with name {self.name} already exists")

        with self.db_con() as cur:
            cur.execute(
                "INSERT INTO feeds (user_hash, name_hash, name) VALUES (%s, %s, %s)",
                (self.user_hash, self.name_hash, self.name),
            )

        return self.key

    def delete(self):
        # ON DELETE CASCADE removes sources, feed_items, source_items, and
        # item_states tied to this feed.
        with self.db_con() as cur:
            cur.execute(
                "DELETE FROM feeds WHERE user_hash = %s AND name_hash = %s",
                (self.user_hash, self.name_hash),
            )

    @classmethod
    def read(cls, user_hash, name_hash) -> Optional["Feed"]:
        with cls.db_con() as cur:
            cur.execute(
                "SELECT name FROM feeds WHERE user_hash = %s AND name_hash = %s",
                (user_hash, name_hash),
            )
            row = cur.fetchone()

        if row:
            return cls(user_hash=user_hash, name=row["name"])

        return None

    @classmethod
    def read_all(cls, user_hash) -> List["Feed"]:
        with cls.db_con() as cur:
            cur.execute(
                "SELECT name FROM feeds WHERE user_hash = %s",
                (user_hash,),
            )
            rows = cur.fetchall()

        return [cls(user_hash=user_hash, name=row["name"]) for row in rows]

    def add_source(self, source):
        source.user_hash = self.user_hash
        source.feed_hash = self.name_hash
        if not source.exists():
            source.create()

    def delete_source(self, source):
        source.delete()
