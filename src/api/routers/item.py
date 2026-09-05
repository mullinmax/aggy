import logging
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import confloat
from typing import Optional

from routers.auth import authenticate
from db.item import ItemLoose
from db.item_state import ItemState
from db.feed import Feed
from db.user import User
from ingest.backends import ytdlp
from route_models.stream import StreamUrlResponse

item_router = APIRouter()


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
    fresh stream per playback. Nothing is downloaded or proxied — the browser
    streams from the origin.
    """
    item = ItemLoose.read(url_hash=item_url_hash)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")

    if not any((entry or {}).get("type") == "stream" for entry in item.media or []):
        raise HTTPException(
            status_code=422, detail="This item has no resolvable stream"
        )

    started = time.monotonic()
    try:
        resolved = ytdlp.resolve_stream(str(item.url))
    except ytdlp.StreamUnavailable as e:
        # Logged as well as returned: the viewer sees the short reason on the
        # card, and the operator can see which item and how long it took.
        logging.info(
            f"stream_url for {item.url} failed after "
            f"{time.monotonic() - started:.1f}s ({e.status_code}): {e}"
        )
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e
    except Exception as e:
        logging.exception(f"stream_url for {item.url} failed unexpectedly")
        raise HTTPException(status_code=502, detail=str(e)) from e

    return StreamUrlResponse(**resolved)
