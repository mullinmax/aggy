"""Ingest a video site's channel / user / playlist / search page.

The heavy lifting happens in the ``aggy-ytdlp`` sidecar, which enumerates the
page with yt-dlp in metadata-only mode. Nothing is ever downloaded: the
listing pass returns titles, thumbnails, and page URLs, and the playable
stream URL is resolved on demand (and never stored, since it expires) by
``/item/stream_url`` when a viewer actually presses play.

This reaches sites that publish no feed at all, paginate their listings, and
gate them behind an age or consent interstitial that a plain HTTP fetch never
gets past.
"""

import logging
from datetime import datetime, timezone
from typing import List, Optional
from urllib.parse import urlparse

import requests

from config import config
from db.item import ItemLoose
from db.source import Source

# Fetching the listing is slower than an RSS GET: the sidecar may walk several
# pages of results, each needing its own request to the site.
EXTRACT_TIMEOUT_SECONDS = 180
DEFAULT_MAX_ENTRIES = 30


def is_configured() -> bool:
    return config.get("YTDLP_HOST", None) is not None


def _service_url(path: str) -> str:
    return "http://{host}:{port}{path}".format(
        host=config.get("YTDLP_HOST"),
        port=config.get("YTDLP_PORT"),
        path=path,
    )


def _published(entry: dict) -> Optional[datetime]:
    timestamp = entry.get("timestamp")
    if timestamp:
        try:
            return datetime.fromtimestamp(int(timestamp), tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            pass
    upload_date = entry.get("upload_date")  # "YYYYMMDD"
    if upload_date:
        try:
            return datetime.strptime(str(upload_date), "%Y%m%d").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            pass
    return None


def entry_to_item(entry: dict) -> Optional[ItemLoose]:
    """One sidecar entry -> an item, or None when it has no usable URL."""
    url = entry.get("url")
    if not url:
        return None

    thumbnail = entry.get("thumbnail")
    # A listing pass returns no description for most sites, and ItemStrict
    # requires excerpt/content, so the title stands in for the body.
    description = entry.get("description") or entry.get("title")
    return ItemLoose(
        url=url,
        title=entry.get("title"),
        author=entry.get("uploader"),
        date_published=_published(entry),
        domain=urlparse(url).netloc or None,
        excerpt=description,
        content=description,
        image_url=thumbnail,
        # "stream" tells the UI to ask the API for a playable URL when the
        # viewer opens the item. Storing one here instead would bake in a
        # signed URL that stops working within hours.
        media=[{"type": "stream", "url": url, "poster": thumbnail}],
    )


def is_supported(url: str) -> dict:
    """Whether the sidecar has a real extractor for this URL.

    Pattern matching only — the site is never contacted — so this is cheap
    enough to run while a user is pasting a URL. Returns
    ``{"supported": bool, "extractor": str | None}``, and simply says no when
    the service isn't running.
    """
    if not is_configured():
        return {"supported": False, "extractor": None}

    try:
        response = requests.post(
            _service_url("/supported"), json={"url": url}, timeout=15
        )
        if response.status_code != 200:
            return {"supported": False, "extractor": None}
        return response.json()
    except (requests.RequestException, ValueError) as e:
        logging.warning(f"Could not check extractor support for {url}: {e}")
        return {"supported": False, "extractor": None}


def fetch_items(source: Source) -> List[ItemLoose]:
    if not is_configured():
        raise Exception(
            "This source needs the aggy-ytdlp service, which isn't configured "
            "(set YTDLP_HOST)"
        )

    source_config = source.config or {}
    payload = {
        "url": str(source.url),
        "limit": int(source_config.get("limit") or DEFAULT_MAX_ENTRIES),
    }
    if source_config.get("cookie"):
        payload["cookie"] = source_config["cookie"]

    try:
        response = requests.post(
            _service_url("/extract"),
            json=payload,
            timeout=EXTRACT_TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        raise Exception(f"Could not reach the extraction service: {e}") from e

    if response.status_code != 200:
        detail = response.text.strip()[:300]
        raise Exception(f"Extraction failed (HTTP {response.status_code}): {detail}")

    entries = response.json().get("entries") or []
    if not entries:
        raise Exception(
            "No entries found at that URL. It may need a channel, playlist, or "
            "search-results page rather than a single item."
        )

    logging.info(f"Source '{source.name}': listing has {len(entries)} entries")

    items = [entry_to_item(entry) for entry in entries]
    return [item for item in items if item is not None]


def enrich_new_item(item):
    """Fill in what a listing pass didn't carry, for an item just discovered.

    Flat extraction is cheap because it never visits the items themselves, so
    on many sites an entry arrives with a URL and a title and nothing else —
    no thumbnail, which leaves a card with an empty frame. This visits the
    item once, the first time it's seen, and is skipped entirely when the
    listing already gave us a picture.
    """
    if not is_configured() or item.image_url:
        return None

    try:
        response = requests.post(
            _service_url("/metadata"),
            json={"url": str(item.url)},
            timeout=EXTRACT_TIMEOUT_SECONDS,
        )
        if response.status_code != 200:
            logging.info(
                f"No metadata for {item.url} "
                f"(HTTP {response.status_code}); keeping the listing's version"
            )
            return None
        data = response.json()
    except (requests.RequestException, ValueError) as e:
        logging.warning(f"Metadata lookup failed for {item.url}: {e}")
        return None

    thumbnail = data.get("thumbnail")
    if not thumbnail:
        return None

    updates = {"image_url": thumbnail}

    # the stream entry's poster is the same picture; without it the player
    # shows a blank box until it's told to play
    if item.media:
        updates["media"] = [
            {**entry, "poster": entry.get("poster") or thumbnail}
            if entry.get("type") == "stream"
            else entry
            for entry in item.media
        ]

    if item.date_published is None:
        published = _published(data)
        if published is not None:
            updates["date_published"] = published

    description = (data.get("description") or "").strip()
    if description and item.excerpt == item.title:
        updates["excerpt"] = description
        updates["content"] = description

    return item.model_copy(update=updates)


def resolve_stream(url: str, cookie: Optional[str] = None) -> dict:
    """A currently-playable media URL for a page URL.

    Called per playback rather than at ingest time; the returned URL is
    typically signed and short-lived, so it is deliberately never persisted.
    """
    if not is_configured():
        raise Exception("The aggy-ytdlp service isn't configured (set YTDLP_HOST)")

    payload = {"url": url}
    if cookie:
        payload["cookie"] = cookie

    response = requests.post(
        _service_url("/resolve"), json=payload, timeout=EXTRACT_TIMEOUT_SECONDS
    )
    if response.status_code != 200:
        detail = response.text.strip()[:300]
        raise Exception(
            f"Could not resolve a playable URL (HTTP {response.status_code}): {detail}"
        )
    return response.json()
