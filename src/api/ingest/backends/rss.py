"""The original ingest backend: fetch a URL and parse it as RSS/Atom."""

import logging
from typing import List

import feedparser
import requests

from config import config
from db.item import ItemLoose
from db.source import Source
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
        raise Exception(f"Could not fetch feed: {e}") from e

    if response.status_code == 429:
        retry_after = response.headers.get("Retry-After")
        detail = f", retry after {retry_after}s" if retry_after else ""
        raise Exception(f"Rate limited by feed server (HTTP 429{detail})")

    if response.status_code != 200:
        raise Exception(f"Feed request returned HTTP {response.status_code}")

    parsed = feedparser.parse(response.content)
    entries = parsed.entries

    if not entries:
        detail = ""
        if parsed.bozo and parsed.get("bozo_exception"):
            detail = f" ({parsed.bozo_exception})"
        raise Exception(f"Feed returned no entries{detail}")

    # rss-bridge reports bridge failures as a 200 OK feed containing a single
    # item titled "Bridge returned error <code>! (<id>)". Treat that as a
    # failed ingest instead of ingesting the error as an article.
    bridge_errors = [
        e for e in entries if str(e.get("title", "")).startswith("Bridge returned error")
    ]
    if bridge_errors:
        raise Exception(f"rss-bridge failed: {bridge_errors[0].get('title')}")

    logging.info(f"Source '{source.name}': feed has {len(entries)} entries")

    return [ingest_rss_item(entry) for entry in entries if entry.get("link")]
