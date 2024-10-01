from fastapi import APIRouter, Depends, HTTPException
from pydantic import confloat
from typing import Optional

from routers.auth import authenticate
from db.item_state import ItemState
from db.feed import Feed
from db.user import User

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
