from fastapi import APIRouter, Depends, HTTPException

from typing import List

from db.category import Category
from db.feed import Feed
from db.user import User
from route_models.item import ItemResponse
from route_models.acknowledge import AcknowledgeResponse
from routers.auth import authenticate

feed_router = APIRouter()


@feed_router.post(
    "/create",
    summary="Create a feed (within a category)",
    response_model=AcknowledgeResponse,
)
def create_feed(
    category_name_hash: str,
    feed_name: str,
    feed_url: str,
    user: User = Depends(authenticate),
) -> AcknowledgeResponse:
    cat = Category.read(user_hash=user.name_hash, name_hash=category_name_hash)
    feed = Feed(
        user_hash=user.name_hash,
        category_hash=category_name_hash,
        name=feed_name,
        url=feed_url,
    )
    cat.add_feed(feed)
    return AcknowledgeResponse()


@feed_router.get(
    "/items", summary="Get all items in a feed", response_model=List[ItemResponse]
)
def get_items(
    category_name_hash: str, feed_name_hash: str, user: User = Depends(authenticate)
) -> List[ItemResponse]:
    try:
        feed = Feed.read(
            user_hash=user.name_hash,
            category_hash=category_name_hash,
            feed_hash=feed_name_hash,
        )
    except Exception:
        raise HTTPException(status_code=404, detail="Feed not found")

    return [ItemResponse.from_db_model(i) for i in feed.items]


@feed_router.delete(
    "/delete",
    summary="Delete a feed",
    response_model=AcknowledgeResponse,
)
def delete_feed(
    category_name_hash: str, feed_name_hash: str, user: User = Depends(authenticate)
) -> AcknowledgeResponse:
    cat = Category.read(user_hash=user.name_hash, name_hash=category_name_hash)
    feed = Feed.read(
        user_hash=user.name_hash,
        category_hash=category_name_hash,
        feed_hash=feed_name_hash,
    )
    cat.delete_feed(feed)
    return AcknowledgeResponse
