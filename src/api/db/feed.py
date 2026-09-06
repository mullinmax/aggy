from pydantic import StringConstraints
from typing import List, Optional
from typing_extensions import Annotated

from .item_collection import ItemCollection

# sort name -> ORDER BY clause; "best" is the pre-prediction default.
# Module-level because pydantic would treat an underscored class attribute
# as a private attr.
ITEM_SORTS = {
    "best": "c.score DESC, c.added_at DESC",
    "predicted": "c.predicted_score DESC NULLS LAST, c.added_at DESC",
    "predicted_asc": "c.predicted_score ASC NULLS LAST, c.added_at DESC",
    "controversial": "c.predicted_confidence ASC NULLS LAST, c.added_at DESC",
    "confident": "c.predicted_confidence DESC NULLS LAST, c.added_at DESC",
    "newest": "i.date_published DESC NULLS LAST, c.added_at DESC",
    "oldest": "i.date_published ASC NULLS LAST, c.added_at ASC",
}

# Sorts whose whole point is a strict, monotonic ranking of the model's
# prediction. The feed's UI marks threshold crossings in these orders with
# horizontal-rule dividers (e.g. where predicted votes fall from "upvote" to
# "neutral"), which only reads correctly if the list is truly monotonic — so
# these sorts skip the round-robin source interleaving the browse sorts use.
MONOTONIC_SORTS = {"predicted", "predicted_asc", "controversial", "confident"}

# date-filter name -> postgres interval. "all" (or None) means no cutoff.
# The cutoff runs against the item's publish date, falling back to when the
# feed picked it up for items that never carried one.
ITEM_AGE_WINDOWS = {
    "day": "1 day",
    "week": "7 days",
    "month": "30 days",
    "year": "365 days",
}

# The `media` entry types the ingest backends produce, grouped by the kind of
# post they make. A single item can land in more than one group on purpose —
# a clip carries a poster image, a link post carries a preview — so the post
# type filter is a set of overlapping tags rather than one label per item.
MEDIA_TYPES_VIDEO = ("video", "gif", "stream", "embed")
MEDIA_TYPES_IMAGE = ("image", "gif")

# Hosts and file extensions the UI plays inline from the item URL alone, with
# no stored media entry (kept in step with utils.is_playable_media_url and the
# frontend's youtubeId/isVideoFile).
_PLAYABLE_URL_SQL = (
    "i.url ~* '^https?://(www\\.|m\\.)?"
    "(youtube\\.com|youtu\\.be|youtube-nocookie\\.com)/'"
    " OR i.url ~* '\\.(mp4|webm)(\\?|$)'"
)

# An item has a picture if it carries a card image, an image media entry, or
# an <img> inside its (sanitized) content — many feeds only put pictures in
# the content body.
_HAS_IMAGE_SQL = "i.image_url IS NOT NULL OR i.content ~* '<img\\s'"

# Enough body text to be worth reading, rather than a bare pointer at another
# page. Reddit link posts and video listings sit well under this; even a
# one-paragraph article clears it.
TEXT_BODY_MIN_CHARS = 120
_BODY_TEXT_SQL = (
    "length(btrim(regexp_replace(COALESCE(i.content, i.excerpt, ''),"
    " '<[^>]*>', ' ', 'g')))"
)


def _media_has_type_sql(types) -> str:
    """SQL testing whether the item's JSONB media array holds any of `types`.

    Containment (`@>`) rather than `jsonb_array_elements`, because `media` is
    NULL on most items and holds a bare JSON `null` on some, and unnesting
    either one raises.
    """
    tests = " OR ".join(
        f"""i.media @> '[{{"type": "{media_type}"}}]'::jsonb""" for media_type in types
    )
    return f"COALESCE({tests}, FALSE)"


def post_type_sql(post_type: str) -> Optional[str]:
    """SQL predicate for one post type, or None when the name is unknown.

    The types overlap by design: an article with a photo is both `image` and
    `text`, and a video keeps its `image` tag when it has a thumbnail, so
    ticking a box adds posts to the view instead of carving them up.
    """
    if post_type == "video":
        return f"({_media_has_type_sql(MEDIA_TYPES_VIDEO)} OR {_PLAYABLE_URL_SQL})"
    if post_type == "image":
        return f"({_media_has_type_sql(MEDIA_TYPES_IMAGE)} OR {_HAS_IMAGE_SQL})"
    if post_type == "link":
        # a link card, or a post that is nothing but a pointer: no picture, no
        # video, and no body of its own
        return (
            f"({_media_has_type_sql(('link',))}"
            f" OR (NOT ({post_type_sql('image')}) AND NOT ({post_type_sql('video')})"
            f" AND {_BODY_TEXT_SQL} < {TEXT_BODY_MIN_CHARS}))"
        )
    if post_type == "text":
        return f"({_BODY_TEXT_SQL} >= {TEXT_BODY_MIN_CHARS})"
    return None


# Post types offered by the feed filter, in the order the UI shows them.
POST_TYPES = ("image", "video", "link", "text")


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

        # Feed sources (source_feed_hash set) are mirrored by the ingest
        # fan-out, never fetched, so the ingest scheduler skips them here.
        with self.db_con() as cur:
            cur.execute(
                "SELECT user_hash, feed_hash, name_hash, name, url, color, "
                "kind, config FROM sources "
                "WHERE user_hash = %s AND feed_hash = %s "
                "AND source_feed_hash IS NULL",
                (self.user_hash, self.name_hash),
            )
            rows = cur.fetchall()

        return [
            Source(
                user_hash=row["user_hash"],
                feed_hash=row["feed_hash"],
                name=row["name"],
                url=row["url"],
                color=row["color"],
                kind=row["kind"],
                config=row["config"],
            )
            for row in rows
        ]

    def sources_with_stats(self) -> List[dict]:
        """Sources in this feed plus item count and last ingest time.

        Includes feed sources; for those, ``source_feed_name`` carries the
        referenced feed's display name so the UI can label them.
        """
        with self.db_con() as cur:
            cur.execute(
                "SELECT s.name, s.url, s.name_hash, s.feed_hash, s.last_ingested_at, "
                "s.last_ingest_error, s.template_name_hash, s.template_parameters, "
                "s.ingest_interval_minutes, s.color, s.source_feed_hash, s.kind, "
                "sf.name AS source_feed_name, "
                "(SELECT COUNT(*) FROM source_items si "
                " WHERE si.user_hash = s.user_hash AND si.feed_hash = s.feed_hash "
                " AND si.source_hash = s.name_hash) AS item_count "
                "FROM sources s "
                "LEFT JOIN feeds sf ON sf.user_hash = s.user_hash "
                " AND sf.name_hash = s.source_feed_hash "
                "WHERE s.user_hash = %s AND s.feed_hash = %s "
                "ORDER BY s.name",
                (self.user_hash, self.name_hash),
            )
            return cur.fetchall()

    def query_items_with_sources(
        self,
        skip=None,
        limit=None,
        sort: str = "best",
        include_read: bool = True,
        source_hashes: Optional[List[str]] = None,
        post_types: Optional[List[str]] = None,
        max_age: Optional[str] = None,
    ):
        """Like ``query_items`` but pairs each item with its source name and
        the user's item state / model prediction.

        Returns (item, meta) tuples where meta carries source_name,
        user_score, is_read, predicted_score, predicted_confidence.

        - ``include_read=False`` hides items the user has already voted on.
        - ``source_hashes`` restricts to items produced by those sources.
        - ``post_types`` keeps items matching any of ``POST_TYPES`` ("image",
          "video", "link", "text"); the types overlap, so an illustrated
          article answers to both "image" and "text". ``None`` (or every type)
          keeps all.
        - ``max_age`` is a key of ``ITEM_AGE_WINDOWS`` ("day", "week",
          "month", "year") keeping only items published within that window;
          ``None`` (or "all") keeps every item.

        Browse sorts interleave sources within the sort order: each source's
        best item first (ordered by the sort key), then each source's
        second-best, and so on, so the feed mixes sources instead of long runs
        of one. The prediction-ranked sorts (``MONOTONIC_SORTS``) skip that
        interleaving and return items in strict sort order instead.
        """
        from .item import ItemStrict

        order_by = ITEM_SORTS.get(sort, ITEM_SORTS["best"])
        # the same sort keys, without table prefixes, for the outer
        # interleave query where every column is already flattened
        outer_order = order_by.replace("c.", "").replace("i.", "")

        # Votes are shared across feeds: user_score comes from the user's latest
        # vote on the item in any feed (user_item_votes), so a vote cast in one
        # feed shows here too. is_read stays per-feed (from item_states).
        sql = (
            "SELECT i.*, c.score, c.added_at, "
            "c.predicted_score, c.predicted_confidence, "
            "uv.score AS user_score, st.is_read AS is_read, "
            "EXISTS (SELECT 1 FROM list_items li"
            " WHERE li.user_hash = c.user_hash"
            "  AND li.item_url_hash = c.item_url_hash) AS in_list, "
            "src.name AS source_name, src.color AS source_color, "
            "ROW_NUMBER() OVER (PARTITION BY src.name_hash "
            f"ORDER BY {order_by}) AS source_rank "
            "FROM items i "
            "JOIN feed_items c ON c.item_url_hash = i.url_hash "
            "LEFT JOIN item_states st ON st.user_hash = c.user_hash"
            " AND st.feed_hash = c.feed_hash"
            " AND st.item_url_hash = c.item_url_hash "
            "LEFT JOIN user_item_votes uv ON uv.user_hash = c.user_hash"
            " AND uv.item_url_hash = c.item_url_hash "
            "LEFT JOIN LATERAL ("
            " SELECT s.name, s.name_hash, s.color FROM source_items si"
            " JOIN sources s ON s.user_hash = si.user_hash"
            "  AND s.feed_hash = si.feed_hash AND s.name_hash = si.source_hash"
            " WHERE si.user_hash = c.user_hash AND si.feed_hash = c.feed_hash"
            "  AND si.item_url_hash = c.item_url_hash LIMIT 1) src ON TRUE "
            "WHERE c.user_hash = %s AND c.feed_hash = %s"
        )
        params: tuple = (self.user_hash, self.name_hash)

        if not include_read:
            # "hide read" hides items voted on in any feed (shared votes)
            sql += " AND uv.score IS NULL"
        if source_hashes is not None:
            sql += (
                " AND EXISTS (SELECT 1 FROM source_items sf"
                " WHERE sf.user_hash = c.user_hash AND sf.feed_hash = c.feed_hash"
                " AND sf.item_url_hash = c.item_url_hash"
                " AND sf.source_hash = ANY(%s))"
            )
            params = params + (list(source_hashes),)
        # Post-type filter: keep items matching any ticked type. An empty list
        # would match nothing, which is what an all-boxes-cleared filter panel
        # should show, so it is honoured rather than treated as "no filter".
        if post_types is not None:
            predicates = [
                clause
                for clause in (post_type_sql(post_type) for post_type in post_types)
                if clause is not None
            ]
            sql += f" AND ({' OR '.join(predicates)})" if predicates else " AND FALSE"

        # Items with no publish date fall back to when the feed picked them
        # up, so a date filter never silently drops undated items that only
        # just arrived.
        window = ITEM_AGE_WINDOWS.get(max_age) if max_age else None
        if window is not None:
            sql += " AND COALESCE(i.date_published, c.added_at) >= NOW() - %s::interval"
            params = params + (window,)

        # Prediction-ranked sorts stay strictly monotonic (see MONOTONIC_SORTS);
        # the browse sorts interleave sources by round-robin rank first.
        outer_sort = (
            outer_order if sort in MONOTONIC_SORTS else f"q.source_rank, {outer_order}"
        )
        sql = f"SELECT * FROM ({sql}) q ORDER BY {outer_sort}"
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
            # interleave/sort bookkeeping columns aren't item fields
            row.pop("score", None)
            row.pop("added_at", None)
            row.pop("source_rank", None)
            meta = {
                "source_name": row.pop("source_name", None),
                "source_color": row.pop("source_color", None),
                "user_score": row.pop("user_score", None),
                "is_read": row.pop("is_read", None),
                "in_list": row.pop("in_list", None),
                "predicted_score": row.pop("predicted_score", None),
                "predicted_confidence": row.pop("predicted_confidence", None),
            }
            results.append((ItemStrict.from_row(row), meta))
        return results

    def stats(self) -> dict:
        """Dashboard summary numbers: total items, unvoted items, and the
        average posts per day over the last 30 days (or since the first
        item arrived, whichever window is shorter)."""
        with self.db_con() as cur:
            cur.execute(
                "SELECT COUNT(*) AS total, "
                "COUNT(*) FILTER (WHERE st.score IS NULL) AS unread, "
                "COUNT(*) FILTER "
                " (WHERE c.added_at >= NOW() - INTERVAL '30 days') AS recent, "
                "MIN(c.added_at) AS first_added_at "
                "FROM feed_items c "
                "LEFT JOIN item_states st ON st.user_hash = c.user_hash"
                " AND st.feed_hash = c.feed_hash"
                " AND st.item_url_hash = c.item_url_hash "
                "WHERE c.user_hash = %s AND c.feed_hash = %s",
                (self.user_hash, self.name_hash),
            )
            row = cur.fetchone()
            cur.execute("SELECT NOW() AS now")
            now = cur.fetchone()["now"]

        days = 30.0
        if row["first_added_at"] is not None:
            age_days = (now - row["first_added_at"]).total_seconds() / 86400
            days = max(1.0, min(30.0, age_days))
        posts_per_day = (row["recent"] or 0) / days

        return {
            "feed_item_count": row["total"] or 0,
            "feed_unread_count": row["unread"] or 0,
            "feed_posts_per_day": round(posts_per_day, 1),
        }

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

    def rename(self, new_name: str):
        """Rename this feed in place.

        The name_hash is derived from the name, so it changes too. The
        sources, feed_items, item_states, and ranking_model_stats foreign
        keys are ON UPDATE CASCADE, so every source, item, vote, and model
        stat stays attached to the feed under its new hash.
        """
        new_name_hash = self.__insecure_hash__(new_name)
        with self.db_con() as cur:
            cur.execute(
                "UPDATE feeds SET name = %s, name_hash = %s "
                "WHERE user_hash = %s AND name_hash = %s",
                (new_name, new_name_hash, self.user_hash, self.name_hash),
            )
        self.name = new_name

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

    def item_url_hashes(self) -> List[str]:
        """Every item URL hash currently in this feed."""
        with self.db_con() as cur:
            cur.execute(
                "SELECT item_url_hash FROM feed_items "
                "WHERE user_hash = %s AND feed_hash = %s",
                (self.user_hash, self.name_hash),
            )
            return [row["item_url_hash"] for row in cur.fetchall()]

    def _downstream_feed_hashes(self) -> set:
        """Feed hashes that (transitively) source this feed — i.e. every feed
        this feed's items already flow into. Used to reject cycles."""
        seen: set = set()
        frontier = [self.name_hash]
        with self.db_con() as cur:
            while frontier:
                origin = frontier.pop()
                cur.execute(
                    "SELECT feed_hash FROM sources "
                    "WHERE user_hash = %s AND source_feed_hash = %s",
                    (self.user_hash, origin),
                )
                for row in cur.fetchall():
                    fh = row["feed_hash"]
                    if fh not in seen:
                        seen.add(fh)
                        frontier.append(fh)
        return seen

    def add_feed_source(self, origin_feed: "Feed", name: Optional[str] = None):
        """Add another of the user's feeds as a source of this feed.

        Every item already in ``origin_feed`` is mirrored into this feed right
        away, and future items are mirrored by the ingest fan-out. Raises
        ValueError if the two feeds are the same or if the link would create a
        cycle (the origin already receives this feed's items).
        """
        from .source import Source, feed_source_url
        from .propagation import propagate_items

        if origin_feed.name_hash == self.name_hash:
            raise ValueError("A feed cannot be a source of itself")
        if not origin_feed.exists():
            raise ValueError("Source feed not found")
        # A cycle forms when the origin already flows into this feed.
        if origin_feed.name_hash in self._downstream_feed_hashes():
            raise ValueError(
                "That feed already receives this feed's items; adding it would "
                "create a loop"
            )

        source = Source(
            user_hash=self.user_hash,
            feed_hash=self.name_hash,
            name=name.strip() if name and name.strip() else origin_feed.name,
            url=feed_source_url(origin_feed.name_hash),
            source_feed_hash=origin_feed.name_hash,
        )
        if source.exists():
            raise ValueError(
                f'A source named "{source.name}" already exists in this feed'
            )
        source.create()

        # Backfill: mirror the origin feed's current items into this feed (and
        # anything downstream of it). propagate_items finds this feed via the
        # source row just created.
        propagate_items(
            self.user_hash, origin_feed.name_hash, origin_feed.item_url_hashes()
        )
        return source
