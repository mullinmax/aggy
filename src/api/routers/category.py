from fastapi import APIRouter, Depends, HTTPException

from typing import List

from db.category import Category
from db.user import User
from route_models.category import CategoryResponse
from route_models.source import SourceRouteModel
from route_models.item import ItemResponse
from route_models.acknowledge import AcknowledgeResponse
from routers.auth import authenticate

category_router = APIRouter()


def get_category_by_name_hash(user_hash: str, name_hash: str) -> Category:
    cat = Category.read(user_hash=user_hash, name_hash=name_hash)
    if cat is None:
        raise HTTPException(status_code=404, detail="Category not found")

    return cat


# create category
@category_router.post(
    "/create", summary="Create a category", response_model=CategoryResponse
)
def create_category(
    category_name: str, user: User = Depends(authenticate)
) -> CategoryResponse:
    category = Category(user_hash=user.name_hash, name=category_name)
    if not category.exists():
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
    if cat.exists():
        cat.delete()
        return AcknowledgeResponse()

    raise HTTPException(status_code=404, detail="Category not found")


# get a category
@category_router.get("/get", summary="Get a category", response_model=CategoryResponse)
def get_category(
    category_name_hash: str, user: User = Depends(authenticate)
) -> CategoryResponse:
    cat = get_category_by_name_hash(user.name_hash, category_name_hash)

    if cat is None:
        raise HTTPException(status_code=404, detail="Category not found")

    return CategoryResponse.from_db_model(cat)


# get all categories
@category_router.get(
    "/list",
    summary="List categories a user has created",
    response_model=List[CategoryResponse],
)
def list_categories(user: User = Depends(authenticate)) -> List[CategoryResponse]:
    # TODO add list of sources in each category in the response
    return [CategoryResponse.from_db_model(c) for c in user.categories if c is not None]


# get all sources in a category
@category_router.get(
    "/sources",
    summary="List all sources in a category",
    response_model=List[SourceRouteModel],
)
def sources(
    category_name_hash: str, user: User = Depends(authenticate)
) -> List[SourceRouteModel]:
    cat = Category.read(user_hash=user.name_hash, name_hash=category_name_hash)

    if cat is None:
        raise HTTPException(status_code=404, detail="Category not found")

    return [SourceRouteModel.from_db_model(f) for f in cat.sources]


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

    if cat is None:
        raise HTTPException(status_code=404, detail="Category not found")

    return [
        ItemResponse.from_db_model(i) for i in cat.query_items(start=start, end=end)
    ]


# TODO search items in a category
