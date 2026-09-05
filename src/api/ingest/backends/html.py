"""Ingest a plain web page by applying stored CSS selectors to it.

Sources of this kind keep their selectors in ``Source.config``, the same set
the analyzer suggested and the user approved in the preview. When the source
is marked ``render``, the page comes from the headless renderer instead of a
plain GET, so JavaScript-built listings work.
"""

import logging
from typing import List
from urllib.parse import urlparse

from bridge.analyze import fetch_page
from bridge.extract import extract_entries
from bridge.render import render_page
from db.item import ItemLoose
from db.source import Source
from ingest.errors import IngestError


def fetch_items(source: Source) -> List[ItemLoose]:
    source_config = source.config or {}
    url = str(source.url)
    cookie = source_config.get("cookie") or ""

    if source_config.get("render"):
        html = render_page(url, cookie=cookie)
    else:
        html = fetch_page(url, cookie=cookie)

    entries = extract_entries(html, url, source_config)
    if not entries:
        raise IngestError(
            "The page had no entries matching this source's selectors. "
            "The site's markup may have changed."
        )

    logging.info(f"Source '{source.name}': page has {len(entries)} entries")

    items = []
    for entry in entries:
        # ItemStrict insists on excerpt/content, and a listing page rarely
        # carries the article body: fall back to the entry's own text (and
        # then its title) so the item survives until a scraper finds better.
        text = entry["text"] or entry["title"]
        items.append(
            ItemLoose(
                url=entry["url"],
                title=entry["title"],
                author=entry["author"],
                date_published=entry["date_published"],
                domain=urlparse(entry["url"]).netloc or None,
                image_url=entry["image"],
                excerpt=text,
                content=text,
            )
        )
    return items
