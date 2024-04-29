from fastapi import APIRouter, Depends

from typing import List

from shared.db.category import Category
from shared.db.feed import Feed
from shared.db.user import User
from response_models.category import CategoryResponse
from response_models.feed import FeedResponse
from response_models.item import ItemResponse
from response_models.acknowledge import AcknowledgeResponse
from routers.auth import authenticate

category_router = APIRouter()


# create category
@category_router.post(
    "/create", summary="Create a category", response_model=CategoryResponse
)
def create_category(name: str, user: User = Depends(authenticate)) -> CategoryResponse:
    cat = Category(user_hash=user.name_hash, name=name)
    cat.create()
    return CategoryResponse.from_db_model(cat)


# delete category
@category_router.delete(
    "/delete",
    summary="Delete a category",
    response_model=AcknowledgeResponse,
)
def delete_category(
    category_name_hash: str, user: User = Depends(authenticate)
) -> AcknowledgeResponse:
    cat = Category.read(user_hash=user.name_hash, name_hash=category_name_hash)
    cat.delete()
    return AcknowledgeResponse()


# get a category
@category_router.get("/get", summary="Get a category", response_model=CategoryResponse)
def get_category(
    category_name_hash: str, user: User = Depends(authenticate)
) -> CategoryResponse:
    cat = Category.read(user_hash=user.name_hash, name_hash=category_name_hash)
    return CategoryResponse.from_db_model(cat)


# get all categories
@category_router.get(
    "/get_all",
    summary="Get all categories a user has created",
    response_model=List[CategoryResponse],
)
def get_categories(user: User = Depends(authenticate)) -> List[CategoryResponse]:
    cats = Category.read_all(user_hash=user.name_hash)
    return [CategoryResponse.from_db_model(c) for c in cats]


# get all items in a category
# TODO sort method (best, worst, newest, oldest, previous favorites, etc.)
# TODO pagination
# TODO filter method (read, unread, etc.)
@category_router.get(
    "/get_all_items",
    summary="List all items in a category",
    response_model=List[ItemResponse],
)
def get_all_items(
    category_name_hash: str, user: User = Depends(authenticate)
) -> List[ItemResponse]:
    cat = Category.read(user_hash=user.name_hash, name_hash=category_name_hash)
    return [ItemResponse.from_db_model(i) for i in cat.items]


# get all feeds in a category
@category_router.get(
    "/get_all_feeds",
    summary="List all feeds in a category",
    response_model=List[FeedResponse],
)
def get_all_feeds(
    category_name_hash: str, user: User = Depends(authenticate)
) -> List[FeedResponse]:
    cat = Category.read(user_hash=user.name_hash, name_hash=category_name_hash)
    return [FeedResponse.from_db_model(f) for f in cat.feeds]


# add a feed to a category
@category_router.post(
    "/add_feed", summary="Add a feed to a category", response_model=AcknowledgeResponse
)
def add_feed_to_category(
    category_name_hash: str, feed_name_hash: str, user: User = Depends(authenticate)
) -> AcknowledgeResponse:
    cat = Category.read(user_hash=user.name_hash, name_hash=category_name_hash)
    feed = Feed.read(
        user_hash=user.name_hash,
        category_hash=category_name_hash,
        name_hash=feed_name_hash,
    )
    cat.add_feed(feed)
    return AcknowledgeResponse()


# delete a feed from a category
@category_router.delete(
    "/delete_feed",
    summary="Delete a feed from a category",
    response_model=AcknowledgeResponse,
)
def delete_feed_from_category(
    category_name_hash: str, feed_name_hash: str, user: User = Depends(authenticate)
) -> AcknowledgeResponse:
    cat = Category.read(user_hash=user.name_hash, name_hash=category_name_hash)
    feed = Feed.read(
        user_hash=user.name_hash,
        category_hash=category_name_hash,
        name_hash=feed_name_hash,
    )
    cat.delete_feed(feed)
    return AcknowledgeResponse


# get all items in a feed
@category_router.post(
    "/items", summary="Get all items in a feed", response_model=List[ItemResponse]
)
def get_items(
    category_name_hash: str, feed_name_hash: str, user: User = Depends(authenticate)
) -> List[ItemResponse]:
    cat = Category.read(user_hash=user.name_hash, name_hash=category_name_hash)
    feed = cat.read_feed(name_hash=feed_name_hash)
    items = feed.get_all_items()
    return [ItemResponse.from_db_model(i) for i in items]


# TODO search items in a category
# TODO get item's feed that produced it
