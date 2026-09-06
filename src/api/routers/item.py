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
        response.proxy_url = tickets.url_for(
            tickets.mint(response.url, user.name_hash, item_url_hash)
        )
    return response


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
    headers = {
        "User-Agent": PROXY_USER_AGENT,
        # Sites check where a request claims to come from; the item's own page
        # is where a viewer would have been playing it.
        "Referer": str(item.url) if item else url,
        # Range responses and re-encoded bodies do not mix.
        "Accept-Encoding": "identity",
    }
    for name in FORWARDED_REQUEST_HEADERS:
        value = request.headers.get(name)
        if value:
            headers[name.title()] = value

    cookie = Source.cookie_for_item(claims.get("user"), claims.get("item"))
    if cookie:
        headers["Cookie"] = cookie

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
