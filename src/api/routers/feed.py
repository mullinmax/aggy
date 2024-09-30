from fastapi import APIRouter, Depends, HTTPException

from typing import List

from db.feed import Feed
from db.user import User
from route_models.feed import FeedResponse
from route_models.source import SourceRouteModel
from route_models.item import ItemResponse
from route_models.acknowledge import AcknowledgeResponse
from routers.auth import authenticate

feed_router = APIRouter()


def get_feed_by_name_hash(user_hash: str, name_hash: str) -> Feed:
    cat = Feed.read(user_hash=user_hash, name_hash=name_hash)
    if cat is None:
        raise HTTPException(status_code=404, detail="Feed not found")

    return cat


# create feed
@feed_router.post("/create", summary="Create a feed", response_model=FeedResponse)
def create_feed(feed_name: str, user: User = Depends(authenticate)) -> FeedResponse:
    feed = Feed(user_hash=user.name_hash, name=feed_name)
    if not feed.exists():
        feed.create()
    return FeedResponse.from_db_model(feed)


# delete feed
@feed_router.delete(
    "/delete",
    summary="Delete a feed",
    response_model=AcknowledgeResponse,
)
def delete_feed(
    feed_name_hash: str, user: User = Depends(authenticate)
) -> AcknowledgeResponse:
    cat = get_feed_by_name_hash(user.name_hash, feed_name_hash)
    if cat.exists():
        cat.delete()
        return AcknowledgeResponse()

    raise HTTPException(status_code=404, detail="Feed not found")


# get a feed
@feed_router.get("/get", summary="Get a feed", response_model=FeedResponse)
def get_feed(feed_name_hash: str, user: User = Depends(authenticate)) -> FeedResponse:
    cat = get_feed_by_name_hash(user.name_hash, feed_name_hash)

    if cat is None:
        raise HTTPException(status_code=404, detail="Feed not found")

    return FeedResponse.from_db_model(cat)


# get all feeds
@feed_router.get(
    "/list",
    summary="List feeds a user has created",
    response_model=List[FeedResponse],
)
def list_feeds(user: User = Depends(authenticate)) -> List[FeedResponse]:
    # TODO add list of sources in each feed in the response
    return [FeedResponse.from_db_model(c) for c in user.feeds if c is not None]


# get all sources in a feed
@feed_router.get(
    "/sources",
    summary="List all sources in a feed",
    response_model=List[SourceRouteModel],
)
def sources(
    feed_name_hash: str, user: User = Depends(authenticate)
) -> List[SourceRouteModel]:
    cat = Feed.read(user_hash=user.name_hash, name_hash=feed_name_hash)

    if cat is None:
        raise HTTPException(status_code=404, detail="Feed not found")

    return [SourceRouteModel.from_db_model(f) for f in cat.sources]


# get all items in a feed
# TODO sort method (best, worst, newest, oldest, previous favorites, etc.)
# TODO filter method (read, unread, etc.)
@feed_router.get(
    "/items",
    summary="List all items in a feed",
    response_model=List[ItemResponse],
)
def get_feed_items(
    feed_name_hash: str,
    start: int = 0,
    end: int = -1,
    user: User = Depends(authenticate),
) -> List[ItemResponse]:
    cat = Feed.read(user_hash=user.name_hash, name_hash=feed_name_hash)

    if cat is None:
        raise HTTPException(status_code=404, detail="Feed not found")

    return [
        ItemResponse.from_db_model(i) for i in cat.query_items(start=start, end=end)
    ]


# TODO search items in a feed
