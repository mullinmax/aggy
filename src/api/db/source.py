import json
from typing import Dict, Optional

from pydantic import StringConstraints, HttpUrl
from typing_extensions import Annotated

from constants import SOURCE_READ_INTERVAL_MINUTES
from .item_collection import ItemCollection

# Sentinel for update(): distinguishes "leave unchanged" from an explicit
# None ("reset to the server default").
_UNSET = object()


class Source(ItemCollection):
    user_hash: str
    feed_hash: str
    name: Annotated[str, StringConstraints(strict=True, min_length=1)]
    url: HttpUrl
    # Set when the source was created from a template, so its parameters can
    # be edited later.
    template_name_hash: Optional[str] = None
    template_parameters: Optional[Dict[str, str]] = None
    # How often to check this source, in minutes. None uses the server-wide
    # SOURCE_READ_INTERVAL_MINUTES default.
    ingest_interval_minutes: Optional[int] = None

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
                "template_name_hash, template_parameters, ingest_interval_minutes, "
                "next_ingest_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())",
                (
                    self.user_hash,
                    self.feed_hash,
                    self.name_hash,
                    self.name,
                    str(self.url),
                    self.template_name_hash,
                    json.dumps(self.template_parameters)
                    if self.template_parameters is not None
                    else None,
                    self.ingest_interval_minutes,
                ),
            )

    def update(
        self, name: str, url: str, template_parameters=None, ingest_interval=_UNSET
    ):
        """Update this source in place. Renaming changes name_hash; the
        source_items FK cascades so existing items stay attached. Resets
        next_ingest_at so the (possibly new) URL is fetched promptly.

        ``ingest_interval`` sets the per-source check frequency in minutes;
        pass ``None`` to reset it to the server default, or leave it out to
        keep the current value."""
        new_name_hash = self.__insecure_hash__(name)
        interval_sql = ""
        interval_params: tuple = ()
        if ingest_interval is not _UNSET:
            interval_sql = "ingest_interval_minutes = %s, "
            interval_params = (ingest_interval,)
        with self.db_con() as cur:
            cur.execute(
                "UPDATE sources SET name = %s, name_hash = %s, url = %s, "
                "template_parameters = COALESCE(%s, template_parameters), "
                f"{interval_sql}"
                "next_ingest_at = NOW() "
                "WHERE user_hash = %s AND feed_hash = %s AND name_hash = %s",
                (
                    name,
                    new_name_hash,
                    str(url),
                    json.dumps(template_parameters)
                    if template_parameters is not None
                    else None,
                )
                + interval_params
                + (
                    self.user_hash,
                    self.feed_hash,
                    self.name_hash,
                ),
            )
        self.name = name
        self.url = url
        if template_parameters is not None:
            self.template_parameters = template_parameters
        if ingest_interval is not _UNSET:
            self.ingest_interval_minutes = ingest_interval

    def delete(self):
        with self.db_con() as cur:
            cur.execute(
                "DELETE FROM sources "
                "WHERE user_hash = %s AND feed_hash = %s AND name_hash = %s",
                (self.user_hash, self.feed_hash, self.name_hash),
            )

    def trigger_ingest(self, now=False):
        # Compare against the database clock (next_ingest_at is TIMESTAMPTZ);
        # a naive Python datetime here breaks when app/DB timezones differ.
        if now:
            target_sql = "NOW()"
            params = ()
        else:
            target_sql = (
                "NOW() + make_interval(mins => COALESCE(ingest_interval_minutes, %s))"
            )
            params = (SOURCE_READ_INTERVAL_MINUTES,)

        # Mirrors the Redis ZADD lt=True semantics: only move next_ingest_at
        # earlier, never later.
        with self.db_con() as cur:
            cur.execute(
                f"UPDATE sources SET next_ingest_at = LEAST(next_ingest_at, {target_sql}) "
                "WHERE user_hash = %s AND feed_hash = %s AND name_hash = %s",
                params + (self.user_hash, self.feed_hash, self.name_hash),
            )

    def push_next_ingest(self):
        """Push the next scheduled ingest a full interval out from now."""
        with self.db_con() as cur:
            cur.execute(
                "UPDATE sources SET next_ingest_at = NOW() + "
                "make_interval(mins => COALESCE(ingest_interval_minutes, %s)) "
                "WHERE user_hash = %s AND feed_hash = %s AND name_hash = %s",
                (
                    SOURCE_READ_INTERVAL_MINUTES,
                    self.user_hash,
                    self.feed_hash,
                    self.name_hash,
                ),
            )

    def mark_ingested(self):
        with self.db_con() as cur:
            cur.execute(
                "UPDATE sources SET last_ingested_at = NOW(), last_ingest_error = NULL "
                "WHERE user_hash = %s AND feed_hash = %s AND name_hash = %s",
                (self.user_hash, self.feed_hash, self.name_hash),
            )

    def mark_ingest_error(self, error: str):
        with self.db_con() as cur:
            cur.execute(
                "UPDATE sources SET last_ingested_at = NOW(), last_ingest_error = %s "
                "WHERE user_hash = %s AND feed_hash = %s AND name_hash = %s",
                (error[:500], self.user_hash, self.feed_hash, self.name_hash),
            )

    @classmethod
    def read(cls, user_hash, feed_hash, source_hash):
        with cls.db_con() as cur:
            cur.execute(
                "SELECT name, url, template_name_hash, template_parameters, "
                "ingest_interval_minutes "
                "FROM sources "
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
                template_name_hash=row["template_name_hash"],
                template_parameters=row["template_parameters"],
                ingest_interval_minutes=row["ingest_interval_minutes"],
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
