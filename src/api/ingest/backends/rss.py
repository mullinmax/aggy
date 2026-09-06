"""The original ingest backend: fetch a URL and parse it as RSS/Atom."""

import logging
import re
from typing import List

import feedparser
import requests
from bs4 import BeautifulSoup

from config import config
from db.item import ItemLoose
from db.source import Source
from ingest.errors import IngestError
from ingest.item.rss import ingest_rss_item
from ingest.reddit_rate_limit import is_reddit_url, reddit_get


def feed_headers() -> dict:
    # A descriptive User-Agent matters: reddit.com and others rate-limit
    # anonymous/default agents far more aggressively.
    return {
        "User-Agent": (
            f"aggy/{config.get('BUILD_VERSION')} "
            "(self-hosted feed aggregator; +https://github.com/mullinmax/aggy)"
        )
    }


# How much of a failed response to quote back. Enough for a bridge's one-line
# explanation, not enough to put a stack trace in the sources list.
ERROR_MESSAGE_MAX_CHARS = 300

# Bridges wrap their failures in a whole error page — a greeting, an apology,
# then the node version and git hash. The one line worth showing a user is
# labelled, so pull that out and drop the rest of the furniture.
_LABELLED_ERROR = re.compile(
    r"error message:\s*(?P<message>.+?)"
    r"(?=\s+(?:route|full route|node version|git hash|git date|path):|$)",
    re.IGNORECASE,
)


def _response_message(response) -> str:
    """The human-readable part of a failed response body, if there is one."""
    try:
        body = response.text[:4000]
    except Exception:
        return ""
    if not body.strip():
        return ""

    content_type = response.headers.get("Content-Type", "")
    if "html" in content_type or body.lstrip().startswith("<"):
        body = BeautifulSoup(body, "html.parser").get_text(" ", strip=True)

    message = " ".join(body.split())

    labelled = _LABELLED_ERROR.search(message)
    if labelled:
        message = labelled.group("message").strip()

    if len(message) > ERROR_MESSAGE_MAX_CHARS:
        message = message[: ERROR_MESSAGE_MAX_CHARS - 1] + "…"
    return message


def fetch_items(source: Source) -> List[ItemLoose]:
    # Fetch the feed ourselves so failures produce a useful error instead of
    # feedparser silently returning zero entries (rss-bridge answers bad
    # parameters with an HTML error page, for example).
    #
    # reddit.com requests share a global adaptive throttle so all ingest jobs
    # stay under one budget and back off together on 429s.
    fetch = reddit_get if is_reddit_url(source.url) else requests.get
    try:
        response = fetch(str(source.url), timeout=60, headers=feed_headers())
    except requests.RequestException as e:
        raise IngestError(f"Could not fetch feed: {e}") from e

    if response.status_code == 429:
        retry_after = response.headers.get("Retry-After")
        detail = f", retry after {retry_after}s" if retry_after else ""
        raise IngestError(f"Rate limited by feed server (HTTP 429{detail})")

    if response.status_code != 200:
        # Bridges put the real reason in the body — "this route is empty",
        # "route not found", a stack trace — and the status code alone
        # ("HTTP 503") tells a user nothing they can act on.
        detail = _response_message(response)
        raise IngestError(
            f"Feed request returned HTTP {response.status_code}"
            + (f": {detail}" if detail else "")
        )

    parsed = feedparser.parse(response.content)
    entries = parsed.entries

    if not entries:
        detail = ""
        if parsed.bozo and parsed.get("bozo_exception"):
            detail = f" ({parsed.bozo_exception})"
        elif is_reddit_url(source.url):
            # reddit answers a throttled or blocked request with a valid but
            # empty feed rather than an error, so an empty listing from a
            # subreddit that clearly has posts is almost always the throttle
            detail = " (reddit serves an empty feed when it is throttling)"
        raise IngestError(f"Feed returned no entries{detail}")

    # rss-bridge reports bridge failures as a 200 OK feed containing a single
    # item titled "Bridge returned error <code>! (<id>)". Treat that as a
    # failed ingest instead of ingesting the error as an article.
    bridge_errors = [
        e
        for e in entries
        if str(e.get("title", "")).startswith("Bridge returned error")
    ]
    if bridge_errors:
        raise IngestError(f"rss-bridge failed: {bridge_errors[0].get('title')}")

    logging.info(f"Source '{source.name}': feed has {len(entries)} entries")

    return [ingest_rss_item(entry) for entry in entries if entry.get("link")]
