from fastapi import APIRouter, Depends, HTTPException

from typing import List

from db.category import Category
from db.user import User
from route_models.category import CategoryResponse
from route_models.feed import FeedResponse
from route_models.item import ItemResponse
from route_models.acknowledge import AcknowledgeResponse
from routers.auth import authenticate

category_router = APIRouter()


def get_category_by_name_hash(user_hash: str, name_hash: str) -> Category:
    cat = None
    try:
        cat = Category.read(user_hash=user_hash, name_hash=name_hash)
    except Exception:
        raise HTTPException(status_code=500, detail="Category not found")

    return cat


# create category
@category_router.post(
    "/create", summary="Create a category", response_model=CategoryResponse
)
def create_category(name: str, user: User = Depends(authenticate)) -> CategoryResponse:
    category = Category(user_hash=user.name_hash, name=name)
    category.create()
    return CategoryResponse.from_db_model(category)


# delete category
@category_router.delete(
    "/delete",
    summary="Delete a category",
    response_model=AcknowledgeResponse,
)
def delete_category(
    category_name_hash: str, user: User = Depends(authenticate)
) -> AcknowledgeResponse:
    cat = get_category_by_name_hash(user.name_hash, category_name_hash)
    cat.delete()
    return AcknowledgeResponse()


# get a category
@category_router.get("/get", summary="Get a category", response_model=CategoryResponse)
def get_category(
    category_name_hash: str, user: User = Depends(authenticate)
) -> CategoryResponse:
    cat = get_category_by_name_hash(user.name_hash, category_name_hash)
    return CategoryResponse.from_db_model(cat)


# get all categories
@category_router.get(
    "/list",
    summary="List categories a user has created",
    response_model=List[CategoryResponse],
)
def list_categories(user: User = Depends(authenticate)) -> List[CategoryResponse]:
    # TODO add list of feeds in each category in the response
    return [CategoryResponse.from_db_model(c) for c in user.categories]


# get all feeds in a category
@category_router.get(
    "/feeds",
    summary="List all feeds in a category",
    response_model=List[FeedResponse],
)
def feeds(
    category_name_hash: str, user: User = Depends(authenticate)
) -> List[FeedResponse]:
    cat = Category.read(user_hash=user.name_hash, name_hash=category_name_hash)
    return [FeedResponse.from_db_model(f) for f in cat.feeds]


# get all items in a category
# TODO sort method (best, worst, newest, oldest, previous favorites, etc.)
# TODO filter method (read, unread, etc.)
@category_router.get(
    "/items",
    summary="List all items in a category",
    response_model=List[ItemResponse],
)
def get_category_items(
    category_name_hash: str,
    start: int = 0,
    end: int = -1,
    user: User = Depends(authenticate),
) -> List[ItemResponse]:
    cat = Category.read(user_hash=user.name_hash, name_hash=category_name_hash)
    return [
        ItemResponse.from_db_model(i) for i in cat.query_items(start=start, end=end)
    ]


# TODO search items in a category
