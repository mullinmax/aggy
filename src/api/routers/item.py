from fastapi import APIRouter, Depends

from routers.auth import authenticate
from .db.item_state import ItemState
from .db.user import User

item_router = APIRouter()


@item_router.post("/set_state")
def set_state(
    item_url_hash: str,
    score: float = 0,
    mark_as_read: bool = True,
    user: User = Depends(authenticate),
) -> None:
    ItemState.set_state(
        user_hash="test",
        category_hash="test",
        item_url_hash=item_url_hash,
        score=score,
        mark_as_read=mark_as_read,
    )


# TODO get a preview for an item  (and save it to the DB)

# TODO get item's feed that produced it

# TODO downvote reasons:
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
