import logging
import time

import requests
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import confloat
from typing import Optional

from routers.auth import authenticate
from db.item import ItemLoose
from db.item_state import ItemState
from db.feed import Feed
from db.source import Source
from db.user import User
from ingest.backends import ytdlp
from route_models.stream import StreamUrlResponse
from route_models.thumbnail import ThumbnailResponse
from streaming import manifest, tickets

item_router = APIRouter()

# What a browser would send if it were fetching the media itself. Sites hand
# out URLs that only work for a request that looks like the one that asked
# for them, so the proxy has to keep looking like that request.
PROXY_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
# Headers worth passing on from the viewer: the range is what makes seeking
# work, and without it a scrub bar drags the whole file through.
FORWARDED_REQUEST_HEADERS = ("range", "accept", "accept-language")
# Headers worth passing back: everything the player needs to seek and to know
# what it is playing. Hop-by-hop and CORS headers are deliberately dropped -
# the browser is talking to us now, and we are its own origin.
FORWARDED_RESPONSE_HEADERS = (
    "content-type",
    "content-length",
    "content-range",
    "accept-ranges",
    "etag",
    "last-modified",
)
PROXY_CHUNK_BYTES = 64 * 1024
# Long enough to notice a picture is gone, short enough that a card waiting on
# the answer is not left hanging.
THUMBNAIL_CHECK_TIMEOUT_SECONDS = 8
# Asking the site for a new thumbnail means visiting the item's page, so an
# item whose picture is simply gone is not asked about again for a while.
THUMBNAIL_REFRESH_COOLDOWN_SECONDS = 10 * 60
PROXY_CONNECT_TIMEOUT_SECONDS = 10
PROXY_READ_TIMEOUT_SECONDS = 30


@item_router.post("/set_state")
def set_state(
    feed_hash: str,
    item_url_hash: str,
    score: Optional[confloat(ge=-1, le=1)] = None,
    is_read: bool = True,
    user: User = Depends(authenticate),
) -> None:
    # check feed exists
    feed = Feed.read(user_hash=user.name_hash, name_hash=feed_hash)
    if not feed:
        raise HTTPException(status_code=404, detail="Feed not found")

    ItemState.set_state(
        user_hash=user.name_hash,
        feed_hash=feed_hash,
        item_url_hash=item_url_hash,
        score=score,
        is_read=is_read,
    )


@item_router.get("/get_state")
def get_state(
    feed_hash: str,
    item_url_hash: str,
    user: User = Depends(authenticate),
) -> ItemState:
    item_state = ItemState.read(
        user_hash=user.name_hash,
        feed_hash=feed_hash,
        item_url_hash=item_url_hash,
    )

    if not item_state:
        raise HTTPException(status_code=404, detail="Item state not found")

    return item_state


# TODO downvote/hidden reasons:
# Boring: 😐
# Repetitive: 🔁
# NSFW: 🍑
# NSFL: 🤮
# Scary: 😱
# Disagreement: 🙅
# Misleading: 🤥
# Irrelevant: 🔍
# Low Quality: 🗑️
# Outdated: 🕰️
# Offensive: 🤡
# Promotional: 📢


@item_router.get(
    "/stream_url",
    summary="Resolve a currently-playable media URL for a video item",
    response_model=StreamUrlResponse,
)
def stream_url(
    item_url_hash: str,
    user: User = Depends(authenticate),
) -> StreamUrlResponse:
    """Ask the extraction service for a URL the browser can play right now.

    Video items store no playable URL: the ones sites hand out are signed and
    expire within hours, so a stored one would be broken by the time anyone
    pressed play. Instead the item keeps its page URL and this resolves a
    fresh stream per playback. The browser streams from the origin, and only
    falls back to `proxy_url` (this server pulling the bytes and piping them
    on) when the origin turns it away.
    """
    item = ItemLoose.read(url_hash=item_url_hash)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")

    if not any((entry or {}).get("type") == "stream" for entry in item.media or []):
        raise HTTPException(
            status_code=422, detail="This item has no resolvable stream"
        )

    # Playback goes to the same site the listing came from, so it needs the
    # same key to the door: a source configured with a cookie (an age gate, a
    # consent banner, a signed-in session) lends it to its own items.
    cookie = Source.cookie_for_item(user.name_hash, item_url_hash)

    started = time.monotonic()
    try:
        resolved = ytdlp.resolve_stream(str(item.url), cookie=cookie)
    except ytdlp.StreamUnavailable as e:
        # Logged as well as returned: the viewer sees the short reason on the
        # card, and the operator can see which item and how long it took.
        # A warning rather than info — someone pressed play and got nothing,
        # which is exactly what you go to the log to find.
        logging.warning(
            f"stream_url for {item.url} failed after "
            f"{time.monotonic() - started:.1f}s ({e.status_code}): {e}"
        )
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    except Exception as e:
        logging.exception(f"stream_url for {item.url} failed unexpectedly")
        raise HTTPException(status_code=502, detail=str(e)) from e

    response = StreamUrlResponse(**resolved)
    # Minted whether or not it gets used: the fallback has to be reachable the
    # moment the browser is refused, without a second round trip to find out
    # where to go instead.
    if response.url:
        response.proxy_url = _proxy_url(response.url, user.name_hash, item_url_hash)
    return response


@item_router.get(
    "/thumbnail",
    summary="A picture for a video item that loads right now",
    response_model=ThumbnailResponse,
)
def thumbnail(
    item_url_hash: str,
    user: User = Depends(authenticate),
) -> ThumbnailResponse:
    """Find a working preview picture for an item whose stored one failed.

    A video site signs its thumbnails much as it signs its streams, and
    refuses anything hotlinked from a page it does not know, so the picture
    saved when the item was ingested stops loading well before the item stops
    being worth showing. The card only asks for this once its own attempt has
    failed, and then in two steps: the stored picture fetched through this
    server, which answers hotlinking, and failing that a fresh one from the
    site, which answers expiry and is kept so the next reader pays nothing.
    """
    item = ItemLoose.read(url_hash=item_url_hash)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")

    cookie = Source.cookie_for_item(user.name_hash, item_url_hash)
    stored = _stored_poster(item)
    if stored and _picture_loads(stored, item, cookie):
        return ThumbnailResponse(url=_proxy_url(stored, user.name_hash, item_url_hash))

    fresh = _refreshed_poster(item)
    if fresh:
        return ThumbnailResponse(url=_proxy_url(fresh, user.name_hash, item_url_hash))

    raise HTTPException(
        status_code=404, detail="The site has no picture for this item any more"
    )


def _proxy_url(url: str, user_hash: str, item_url_hash: str) -> str:
    return tickets.url_for(tickets.mint(url, user_hash, item_url_hash))


def _stored_poster(item) -> Optional[str]:
    """The picture the item was saved with: the stream's own, else the card's."""
    for entry in item.media or []:
        if (entry or {}).get("type") == "stream" and entry.get("poster"):
            return entry["poster"]
    return item.image_url


def _picture_loads(url: str, item, cookie: Optional[str]) -> bool:
    """Whether the stored picture is still there, asked as the site expects.

    Only the first byte is wanted: this is about whether the URL still
    answers, not about the picture itself, which the browser will fetch
    through the proxy in a moment.
    """
    try:
        response = requests.get(
            url,
            headers={
                **_origin_headers(item, cookie, str(item.url)),
                "Range": "bytes=0-0",
            },
            stream=True,
            allow_redirects=True,
            timeout=THUMBNAIL_CHECK_TIMEOUT_SECONDS,
        )
        response.close()
    except requests.RequestException as e:
        logging.info(f"Stored thumbnail for {item.url} could not be fetched: {e}")
        return False
    if response.status_code >= 400:
        logging.info(
            f"Stored thumbnail for {item.url} is gone "
            f"(HTTP {response.status_code}); asking the site for another"
        )
        return False
    return True


# Items whose picture the site was recently asked about. Asking means visiting
# the item's page, and an item whose thumbnail is simply gone would otherwise
# be asked about again every time its card is drawn.
_thumbnail_refreshed_at: dict = {}


def _refreshed_poster(item) -> Optional[str]:
    """A new thumbnail from the site, kept so this is paid for only once."""
    asked_at = _thumbnail_refreshed_at.get(item.url_hash)
    if asked_at is not None and (
        time.monotonic() - asked_at < THUMBNAIL_REFRESH_COOLDOWN_SECONDS
    ):
        return None
    _thumbnail_refreshed_at[item.url_hash] = time.monotonic()

    fresh = ytdlp.poster_for(str(item.url))
    if not fresh:
        return None

    updates = {"image_url": fresh}
    if item.media:
        updates["media"] = [
            {**entry, "poster": fresh}
            if (entry or {}).get("type") == "stream"
            else entry
            for entry in item.media
        ]
    try:
        item.update(**updates)
    except Exception:
        # A picture the viewer can see now matters more than storing it; the
        # next reader simply asks again.
        logging.exception(f"Could not store the new thumbnail for {item.url}")
    return fresh


@item_router.get(
    "/stream",
    summary="Pipe a resolved media URL through this server",
    # The browser is pointed straight at this URL by a `video` element, never
    # through the generated client, so it stays out of the schema.
    include_in_schema=False,
)
def stream(ticket: str, request: Request):
    """Fetch a stream on the viewer's behalf and hand the bytes straight on.

    Playing from the origin is the better route and is tried first, but it
    fails in three ways that look identical from the card: sites sign URLs
    for whoever asked (this server, not the viewer), CDNs refuse a page they
    do not know when a player has to fetch a playlist over XHR, and a URL on
    plain http cannot be loaded by a page on https. Coming back through here
    makes the media same-origin and fetched by the same server that resolved
    it, which answers all three.

    The URL is not taken from the caller: it comes out of a ticket this
    server signed, so nobody can point this at an address of their choosing.
    """
    try:
        claims = tickets.verify(ticket)
    except tickets.InvalidTicket as e:
        raise HTTPException(status_code=403, detail=str(e)) from e

    url = claims["url"]
    if not str(url).lower().startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Unsupported stream address")

    item = ItemLoose.read(url_hash=claims.get("item"))
    cookie = Source.cookie_for_item(claims.get("user"), claims.get("item"))
    headers = _origin_headers(item, cookie, fallback_referer=url)
    for name in FORWARDED_REQUEST_HEADERS:
        value = request.headers.get(name)
        if value:
            headers[name.title()] = value

    try:
        upstream = requests.get(
            url,
            headers=headers,
            stream=True,
            allow_redirects=True,
            timeout=(PROXY_CONNECT_TIMEOUT_SECONDS, PROXY_READ_TIMEOUT_SECONDS),
        )
    except requests.RequestException as e:
        logging.warning(f"stream proxy could not reach the origin: {e}")
        raise HTTPException(
            status_code=502, detail="The site would not hand over this video"
        ) from None

    if upstream.status_code >= 400:
        upstream.close()
        logging.warning(
            f"stream proxy refused by the origin (HTTP {upstream.status_code})"
        )
        raise HTTPException(
            status_code=502,
            detail=f"The site answered HTTP {upstream.status_code}",
        )

    passthrough = {
        name: upstream.headers[name]
        for name in FORWARDED_RESPONSE_HEADERS
        if name in upstream.headers
    }

    if manifest.looks_like_manifest(url, upstream.headers.get("Content-Type", "")):
        return _proxied_manifest(upstream, claims, passthrough)

    return StreamingResponse(
        upstream.iter_content(chunk_size=PROXY_CHUNK_BYTES),
        status_code=upstream.status_code,
        headers=passthrough,
        media_type=upstream.headers.get("Content-Type"),
    )


def _origin_headers(item, cookie, fallback_referer: str) -> dict:
    """What to send a site so a request looks like the viewer's own.

    Sites hand out URLs that only work for a request resembling the one that
    asked for them, and hotlink protection turns away anything arriving from
    somewhere it does not recognise. So the request keeps the item's own page
    as its referer and the source's cookie, which is what got past the site's
    door in the first place.
    """
    headers = {
        "User-Agent": PROXY_USER_AGENT,
        "Referer": str(item.url) if item else fallback_referer,
        # Range responses and re-encoded bodies do not mix.
        "Accept-Encoding": "identity",
    }
    if cookie:
        headers["Cookie"] = cookie
    return headers


def _proxied_manifest(upstream, claims: dict, passthrough: dict) -> Response:
    """An HLS playlist, with everything it names pointed back through here.

    Read whole rather than piped: it is a few kilobytes of text, and each URL
    in it needs a ticket of its own before the browser sees it.
    """
    body = upstream.raw.read(manifest.MAX_MANIFEST_BYTES + 1, decode_content=True)
    upstream.close()
    if len(body) > manifest.MAX_MANIFEST_BYTES:
        raise HTTPException(status_code=502, detail="That playlist is implausibly big")

    rewritten = manifest.rewrite(
        body.decode("utf-8", errors="replace"),
        # after redirects: relative URLs are relative to where it actually came
        # from, not where we asked
        str(upstream.url),
        lambda target: tickets.url_for(
            tickets.mint(target, claims.get("user"), claims.get("item"))
        ),
    )
    # The length changed, and these were measured against the original body.
    for header in ("content-length", "etag", "last-modified"):
        passthrough.pop(header, None)
    return Response(
        content=rewritten,
        status_code=upstream.status_code,
        headers=passthrough,
        media_type=upstream.headers.get("Content-Type")
        or "application/vnd.apple.mpegurl",
    )
