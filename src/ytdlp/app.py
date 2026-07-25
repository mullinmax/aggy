"""Metadata-only extraction service for video sites.

Wraps yt-dlp, which knows how to enumerate a channel, user, playlist, or
search-results page on well over a thousand sites and how to get past the age
and consent interstitials that stop a plain HTTP fetch. Two things it
deliberately never does: download a video, or transcode one. ``/extract``
lists a page's entries (titles, thumbnails, page URLs) and ``/resolve`` hands
back a currently-playable URL for a single entry so the browser can stream it
straight from the origin.

The service is internal: aggy-api is the only client, and it is not exposed
in the bundled compose file.
"""

import logging
from typing import Optional
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from yt_dlp import YoutubeDL
from yt_dlp.extractor import gen_extractor_classes
from yt_dlp.utils import DownloadError

app = FastAPI(title="aggy-ytdlp")

MAX_LIMIT = 200
DEFAULT_LIMIT = 30

BASE_OPTIONS = {
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "noprogress": True,
    # keep one bad entry in a listing from failing the whole page
    "ignoreerrors": True,
}


class ExtractRequest(BaseModel):
    url: str
    limit: int = DEFAULT_LIMIT
    cookie: Optional[str] = None


class ResolveRequest(BaseModel):
    url: str
    cookie: Optional[str] = None


def _validate(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(status_code=422, detail="URL must be http(s)")


def _options(cookie: Optional[str], **extra) -> dict:
    options = dict(BASE_OPTIONS, **extra)
    if cookie:
        options["http_headers"] = {"Cookie": cookie}
    return options


def _best_thumbnail(entry: dict) -> Optional[str]:
    if entry.get("thumbnail"):
        return entry["thumbnail"]
    thumbnails = entry.get("thumbnails") or []
    if not thumbnails:
        return None
    # widest wins; entries without dimensions sort last
    best = max(
        thumbnails, key=lambda t: (t.get("width") or 0, t.get("preference") or 0)
    )
    return best.get("url")


def _entry_url(entry: dict) -> Optional[str]:
    # flat entries carry the listing's link in `url`; a fully extracted one
    # (a single video passed straight in) uses `webpage_url`
    return entry.get("webpage_url") or entry.get("url")


def _to_entry(raw: dict) -> Optional[dict]:
    url = _entry_url(raw)
    if not url or not str(url).startswith("http"):
        return None
    return {
        "url": url,
        "title": raw.get("title"),
        "description": raw.get("description"),
        "uploader": raw.get("uploader")
        or raw.get("channel")
        or raw.get("playlist_uploader"),
        "thumbnail": _best_thumbnail(raw),
        "duration": raw.get("duration"),
        "timestamp": raw.get("timestamp"),
        "upload_date": raw.get("upload_date"),
        "view_count": raw.get("view_count"),
        "extractor": raw.get("ie_key") or raw.get("extractor_key"),
    }


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


class SupportedRequest(BaseModel):
    url: str


@app.post("/supported")
def supported(request: SupportedRequest) -> dict:
    """Whether a real extractor claims this URL.

    Purely local pattern matching — no request is made to the site — so the
    API can cheaply ask "is this a video listing?" while a user is typing a
    URL. The catch-all "generic" extractor matches everything and is not a
    useful answer, so it doesn't count.
    """
    _validate(request.url)

    for extractor in gen_extractor_classes():
        name = extractor.ie_key()
        if name == "Generic":
            continue
        if extractor.suitable(request.url):
            return {"supported": True, "extractor": name}
    return {"supported": False, "extractor": None}


@app.post("/extract")
def extract(request: ExtractRequest) -> dict:
    """List the entries of a channel / user / playlist / search page."""
    _validate(request.url)
    limit = max(1, min(request.limit or DEFAULT_LIMIT, MAX_LIMIT))

    # extract_flat stops at the listing itself: one request per results page
    # and no per-video extraction, which is both far faster and much lighter
    # on the site than resolving every entry up front.
    options = _options(
        request.cookie,
        extract_flat="in_playlist",
        playlistend=limit,
        lazy_playlist=True,
    )

    try:
        with YoutubeDL(options) as ydl:
            info = ydl.sanitize_info(ydl.extract_info(request.url, download=False))
    except DownloadError as e:
        raise HTTPException(status_code=422, detail=str(e)[:500])
    except Exception as e:
        logging.exception(f"extract failed for {request.url}")
        raise HTTPException(status_code=500, detail=str(e)[:500])

    if info is None:
        raise HTTPException(status_code=422, detail="Nothing could be extracted")

    raw_entries = info.get("entries")
    if raw_entries is None:  # a single item rather than a listing
        raw_entries = [info]

    entries = [_to_entry(raw) for raw in raw_entries if raw]
    return {
        "title": info.get("title"),
        "entries": [entry for entry in entries if entry][:limit],
    }


def _progressive_url(info: dict) -> Optional[dict]:
    """A single URL playable in a browser `video` element.

    Skips the split video-only/audio-only renditions that would need muxing,
    and HLS/DASH manifests, neither of which a plain `video` tag can play
    everywhere.
    """
    candidates = []
    for fmt in info.get("formats") or []:
        if not fmt.get("url"):
            continue
        if fmt.get("vcodec") in (None, "none") or fmt.get("acodec") in (None, "none"):
            continue
        if (fmt.get("protocol") or "") not in ("https", "http"):
            continue
        candidates.append(fmt)

    if not candidates:
        return None

    best = max(candidates, key=lambda f: (f.get("height") or 0, f.get("tbr") or 0))
    return {
        "url": best["url"],
        "ext": best.get("ext"),
        "height": best.get("height"),
        "protocol": best.get("protocol"),
    }


@app.post("/resolve")
def resolve(request: ResolveRequest) -> dict:
    """A currently-playable media URL for one page URL.

    These URLs are usually signed and expire within hours, so callers are
    expected to ask again per playback rather than store the result.
    """
    _validate(request.url)

    try:
        with YoutubeDL(_options(request.cookie, noplaylist=True)) as ydl:
            info = ydl.sanitize_info(ydl.extract_info(request.url, download=False))
    except DownloadError as e:
        raise HTTPException(status_code=422, detail=str(e)[:500])
    except Exception as e:
        logging.exception(f"resolve failed for {request.url}")
        raise HTTPException(status_code=500, detail=str(e)[:500])

    if not info:
        raise HTTPException(status_code=422, detail="Nothing could be extracted")

    resolved = _progressive_url(info)
    if resolved is None:
        raise HTTPException(
            status_code=422,
            detail="No directly playable rendition is available for this item",
        )

    resolved["title"] = info.get("title")
    resolved["duration"] = info.get("duration")
    resolved["poster"] = _best_thumbnail(info)
    return resolved
