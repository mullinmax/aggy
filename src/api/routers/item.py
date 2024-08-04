from fastapi import APIRouter, Depends, HTTPException

from routers.auth import authenticate
from db.item_state import ItemState
from db.category import Category
from db.user import User

item_router = APIRouter()


@item_router.post("/set_state")
def set_state(
    category_hash: str,
    item_url_hash: str,
    score: float = 0,
    mark_as_read: bool = True,
    user: User = Depends(authenticate),
) -> None:
    # check category exists
    category = Category.read(user=user.name_hash, name_hash=category_hash)
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    ItemState.set_state(
        user_hash=user.name_hash,
        category_hash=category_hash,
        item_url_hash=item_url_hash,
        score=score,
        mark_as_read=mark_as_read,
    )


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
