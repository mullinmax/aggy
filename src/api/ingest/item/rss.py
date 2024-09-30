import feedparser

from db.item import ItemLoose


def ingest_rss_item(entry: feedparser.SourceParserDict) -> ItemLoose:
    # TODO more advanced parsing of content (like when there's more than 1 value)
    try:
        entry_content = entry.get("content")[0]["value"]
    except Exception:
        entry_content = None

    return ItemLoose(
        url=entry.get("link"),
        title=entry.get("title"),
        content=entry_content,
        author=entry.get("author"),
        date_published=entry.get("published"),
        domain=entry.get("link"),
        excerpt=entry_content,
    )
