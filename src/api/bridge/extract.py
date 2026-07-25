"""Turn a page's HTML into feed entries using CSS selectors.

rss-bridge's CSS Selector bridge does this too, but only over HTML it fetched
itself with a plain HTTP GET. Doing the extraction in-process means the same
selectors can be applied to HTML that came from the headless renderer, and
that the preview a user approves is produced by exactly the code that later
ingests the source.
"""

from datetime import datetime
from typing import List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from bridge.analyze import (
    _entry_link,
    _sample_text,
    _select,
    _time_value,
    php_time_format_to_strptime,
)

DEFAULT_LIMIT = 20
# Same ceiling the analyzer uses when validating an entry selector: past this
# the selector is matching navigation or a tag cloud, not an article list.
MAX_ENTRIES = 300


def _image(entry) -> Optional[str]:
    """The entry's thumbnail, including the lazy-loading spellings of `src`.

    Listing pages very often carry the real thumbnail in a data attribute and
    leave `src` as a placeholder until the image scrolls into view.
    """
    for img in _select(entry, "img"):
        for attribute in ("src", "data-src", "data-original", "data-thumb"):
            value = (img.get(attribute) or "").strip()
            if value and not value.startswith("data:"):
                return value
        srcset = (img.get("srcset") or "").strip()
        if srcset:
            first = srcset.split(",")[0].strip().split(" ")[0]
            if first:
                return first
    return None


def _published(entry, selector: str, php_format: str) -> Optional[datetime]:
    if not selector or not php_format:
        return None
    matches = _select(entry, selector)
    if not matches:
        return None
    value = " ".join(_time_value(matches[0]).split())
    try:
        return datetime.strptime(value, php_time_format_to_strptime(php_format))
    except ValueError:
        return None


def extract_entries(html: str, base_url: str, selectors: dict) -> List[dict]:
    """Apply a source's stored selectors to a page.

    Returns dicts of ``{url, title, text, author, date_published, image}``;
    entries without a link are dropped, since there'd be nothing to open or
    dedupe on. ``text`` is the entry's own visible text, which stands in for
    the article body until the per-item scrapers fetch the real one.
    """
    soup = BeautifulSoup(html, "html.parser")

    entry_selector = (selectors.get("entry_element_selector") or "").strip()
    if not entry_selector:
        raise Exception("This source has no entry selector configured")

    url_selector = (selectors.get("url_selector") or "a").strip() or "a"
    title_selector = (selectors.get("title_selector") or "").strip()
    author_selector = (selectors.get("author_selector") or "").strip()
    time_selector = (selectors.get("time_selector") or "").strip()
    time_format = (selectors.get("time_format") or "").strip()

    try:
        limit = int(selectors.get("limit") or DEFAULT_LIMIT)
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT
    limit = max(1, min(limit, MAX_ENTRIES))

    entries = []
    for element in _select(soup, entry_selector)[:limit]:
        link = _entry_link(element, url_selector)
        if link is None:
            continue

        title = None
        if title_selector:
            matches = _select(element, title_selector)
            if matches:
                title = _sample_text(matches[0]) or None
        if not title:
            title = _sample_text(link) or None

        author = None
        if author_selector:
            matches = _select(element, author_selector)
            if matches:
                author = _sample_text(matches[0]) or None

        image = _image(element)
        entries.append(
            {
                "url": urljoin(base_url, link.get("href", "")),
                "title": title,
                "text": _sample_text(element) or None,
                "author": author,
                "date_published": _published(element, time_selector, time_format),
                "image": urljoin(base_url, image) if image else None,
            }
        )

    return entries
