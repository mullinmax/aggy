"""Cross-feed summary statistics about the articles a user has collected.

Everything here is scoped to a single user: an article counts once per user no
matter how many of their feeds it landed in, and articles belonging to other
users are never counted.

The unit of grouping is the *article's own* base domain (the link the article
points at, e.g. ``reddit.com``), not the source/feed URL it arrived through --
several sources routinely deliver articles from the same site.
"""

from datetime import date, timedelta
from typing import List, Optional

from .base import get_db_con

# Second-level suffixes under which the *next* label is the registrable name:
# without this, "bbc.co.uk" would fold to "co.uk" and every UK site would share
# a row. A full Public Suffix List would need a new dependency and a data file
# to keep fresh; this covers the suffixes a feed reader realistically meets.
# The platform entries (blogspot/github.io) are in the real PSL too, and keeping
# them split is what a reader wants anyway -- each blog is its own publisher.
_MULTI_LABEL_SUFFIXES = frozenset(
    {
        "co.uk",
        "org.uk",
        "ac.uk",
        "gov.uk",
        "me.uk",
        "net.uk",
        "sch.uk",
        "com.au",
        "net.au",
        "org.au",
        "edu.au",
        "gov.au",
        "co.nz",
        "net.nz",
        "org.nz",
        "co.jp",
        "ne.jp",
        "or.jp",
        "ac.jp",
        "go.jp",
        "co.kr",
        "co.in",
        "co.za",
        "co.il",
        "com.br",
        "com.mx",
        "com.ar",
        "com.cn",
        "com.tw",
        "com.hk",
        "com.sg",
        "com.tr",
        "com.pl",
        "com.ua",
        "com.es",
        "com.pt",
        "github.io",
        "blogspot.com",
    }
)


def base_domain(host: Optional[str]) -> str:
    """The registrable domain of a hostname: ``old.reddit.com`` -> ``reddit.com``.

    Hostnames that aren't domain names (IP addresses, single labels) come back
    unchanged, and an empty/unparseable host becomes ``"unknown"`` so those
    articles still show up in the table instead of vanishing.
    """
    if not host:
        return "unknown"

    host = host.strip().strip(".").lower()
    if not host:
        return "unknown"

    # IPv6 literals and bare IPv4 addresses have no registrable domain
    if ":" in host or host.replace(".", "").isdigit():
        return host

    labels = host.split(".")
    if len(labels) <= 2:
        return host

    if ".".join(labels[-2:]) in _MULTI_LABEL_SUFFIXES:
        return ".".join(labels[-3:])

    return ".".join(labels[-2:])


# Every article in any of the user's feeds, once, with the per-article flags the
# summaries are built from. The host is pulled out of the URL in SQL (strip the
# scheme, keep the authority, drop any userinfo and port) so Postgres can do the
# grouping; folding hosts into base domains happens in Python.
#
# "Has a preview image" matches ItemBase.embeddable_image_url: an explicit
# image_url, or failing that the first <img> in the (sanitized) content -- that
# is exactly the picture the image embedder would be handed.
_USER_ITEMS_CTE = """
WITH user_items AS (
    SELECT DISTINCT ON (i.url_hash)
        i.url_hash,
        lower(split_part(regexp_replace(split_part(regexp_replace(
            i.url, '^[a-zA-Z][a-zA-Z0-9+.-]*://', ''), '/', 1),
            '^.*@', ''), ':', 1)) AS host,
        (i.image_url IS NOT NULL OR i.content ~* '<img\\s') AS has_preview_image,
        (i.media IS NOT NULL AND i.media::text NOT IN ('null', '[]'))
            AS has_media,
        (i.embeddings IS NOT NULL AND i.embeddings::text NOT IN ('null', '{}'))
            AS has_text_embedding,
        (i.image_embeddings IS NOT NULL
            AND i.image_embeddings::text NOT IN ('null', '{}'))
            AS has_image_embedding,
        (i.content IS NOT NULL AND i.content <> '') AS has_content,
        (i.excerpt IS NOT NULL AND i.excerpt <> '') AS has_excerpt,
        (i.author IS NOT NULL AND i.author <> '') AS has_author,
        (i.date_published IS NOT NULL) AS has_date_published,
        length(regexp_replace(COALESCE(i.content, ''), '<[^>]*>', '', 'g'))
            AS content_chars,
        c.added_at,
        uv.score AS user_score
    FROM feed_items c
    JOIN items i ON i.url_hash = c.item_url_hash
    LEFT JOIN user_item_votes uv
        ON uv.user_hash = c.user_hash AND uv.item_url_hash = c.item_url_hash
    WHERE c.user_hash = %s
    ORDER BY i.url_hash, c.added_at
)
"""

# Count columns shared by the per-domain rows and the overall summary. Every one
# is a plain count, which is what makes folding several hosts into one base
# domain a matter of adding them up.
_COUNT_FIELDS = (
    "with_preview_image",
    "with_image_embedding",
    "with_text_embedding",
    "with_media",
    "with_content",
    "with_excerpt",
    "with_author",
    "with_date_published",
    "up_votes",
    "down_votes",
    "neutral_votes",
)

_HOST_AGGREGATE_SQL = (
    _USER_ITEMS_CTE
    + """
SELECT
    host,
    COUNT(*) AS article_count,
    COUNT(*) FILTER (WHERE has_preview_image) AS with_preview_image,
    COUNT(*) FILTER (WHERE has_image_embedding) AS with_image_embedding,
    COUNT(*) FILTER (WHERE has_text_embedding) AS with_text_embedding,
    COUNT(*) FILTER (WHERE has_media) AS with_media,
    COUNT(*) FILTER (WHERE has_content) AS with_content,
    COUNT(*) FILTER (WHERE has_excerpt) AS with_excerpt,
    COUNT(*) FILTER (WHERE has_author) AS with_author,
    COUNT(*) FILTER (WHERE has_date_published) AS with_date_published,
    COUNT(*) FILTER (WHERE user_score > 0) AS up_votes,
    COUNT(*) FILTER (WHERE user_score < 0) AS down_votes,
    COUNT(*) FILTER (WHERE user_score = 0) AS neutral_votes,
    SUM(content_chars) AS content_chars,
    MIN(added_at) AS first_added_at,
    MAX(added_at) AS last_added_at
FROM user_items
GROUP BY host
"""
)

_TIMELINE_SQL = (
    _USER_ITEMS_CTE
    + """
SELECT
    date_trunc('day', added_at)::date AS day,
    COUNT(*) AS article_count,
    COUNT(*) FILTER (WHERE has_preview_image) AS with_preview_image,
    COUNT(*) FILTER (WHERE has_text_embedding) AS with_text_embedding,
    COUNT(*) FILTER (WHERE has_image_embedding) AS with_image_embedding
FROM user_items
WHERE added_at >= date_trunc('day', NOW()) - make_interval(days => %s)
GROUP BY 1
ORDER BY 1
"""
)


def _new_domain_row(domain: str) -> dict:
    row = {
        "domain": domain,
        "article_count": 0,
        "content_chars": 0,
        "first_added_at": None,
        "last_added_at": None,
    }
    row.update({field: 0 for field in _COUNT_FIELDS})
    return row


def _merge_host_row(target: dict, row: dict) -> None:
    target["article_count"] += row["article_count"] or 0
    target["content_chars"] += row["content_chars"] or 0
    for field in _COUNT_FIELDS:
        target[field] += row[field] or 0

    for field, pick in (("first_added_at", min), ("last_added_at", max)):
        value = row[field]
        if value is not None:
            current = target[field]
            target[field] = value if current is None else pick(current, value)


def domain_stats(user_hash: str) -> List[dict]:
    """Per-base-domain article stats for one user, busiest domain first."""
    with get_db_con() as cur:
        cur.execute(_HOST_AGGREGATE_SQL, (user_hash,))
        rows = cur.fetchall()

    domains: dict[str, dict] = {}
    for row in rows:
        domain = base_domain(row["host"])
        _merge_host_row(domains.setdefault(domain, _new_domain_row(domain)), row)

    for row in domains.values():
        # average length of the article body, over the articles that have one
        with_content = row["with_content"]
        row["avg_content_chars"] = (
            round(row["content_chars"] / with_content) if with_content else None
        )
        del row["content_chars"]

    return sorted(
        domains.values(),
        key=lambda row: (-row["article_count"], row["domain"]),
    )


def _summarize(domains: List[dict]) -> dict:
    summary = {
        "total_articles": sum(row["article_count"] for row in domains),
        "domain_count": len(domains),
    }
    for field in _COUNT_FIELDS:
        summary[field] = sum(row[field] for row in domains)

    lengths = [
        (row["avg_content_chars"], row["with_content"])
        for row in domains
        if row["avg_content_chars"] is not None
    ]
    total_with_content = sum(count for _, count in lengths)
    summary["avg_content_chars"] = (
        round(sum(avg * count for avg, count in lengths) / total_with_content)
        if total_with_content
        else None
    )

    stamps = [row["last_added_at"] for row in domains if row["last_added_at"]]
    firsts = [row["first_added_at"] for row in domains if row["first_added_at"]]
    summary["first_added_at"] = min(firsts) if firsts else None
    summary["last_added_at"] = max(stamps) if stamps else None
    return summary


def article_timeline(user_hash: str, days: int) -> List[dict]:
    """Articles collected per day over the last ``days`` days.

    Days with no articles are filled in with zeroes so the chart has an even
    time axis instead of silently compressing quiet stretches.
    """
    with get_db_con() as cur:
        cur.execute(_TIMELINE_SQL, (user_hash, days))
        by_day = {row["day"]: row for row in cur.fetchall()}
        cur.execute("SELECT date_trunc('day', NOW())::date AS today")
        today: date = cur.fetchone()["today"]

    timeline = []
    for offset in range(days, -1, -1):
        day = today - timedelta(days=offset)
        row = by_day.get(day)
        timeline.append(
            {
                "day": day,
                "article_count": row["article_count"] if row else 0,
                "with_preview_image": row["with_preview_image"] if row else 0,
                "with_text_embedding": row["with_text_embedding"] if row else 0,
                "with_image_embedding": row["with_image_embedding"] if row else 0,
            }
        )
    return timeline


def article_stats(user_hash: str, timeline_days: int = 30) -> dict:
    """Everything the article-stats page shows: overall totals, a row per base
    domain, and a daily collection timeline."""
    domains = domain_stats(user_hash)
    return {
        "summary": _summarize(domains),
        "domains": domains,
        "timeline": article_timeline(user_hash, timeline_days),
    }
