from urllib.parse import urlparse

import feedparser

from db.item import ItemLoose


def ingest_rss_item(entry: feedparser.FeedParserDict) -> ItemLoose:
    # TODO more advanced parsing of content (like when there's more than 1 value)
    try:
        entry_content = entry.get("content")[0]["value"]
    except Exception:
        entry_content = None

    link = entry.get("link")
    # domain is the site's hostname, not the full article URL
    domain = urlparse(link).netloc if link else None

    return ItemLoose(
        url=link,
        title=entry.get("title"),
        content=entry_content,
        author=entry.get("author"),
        date_published=entry.get("published"),
        domain=domain or None,
        excerpt=entry_content,
    )
