from fastapi import APIRouter, Depends, HTTPException

from typing import List

from db.category import Category
from db.source import Source
from db.user import User
from route_models.item import ItemResponse
from route_models.acknowledge import AcknowledgeResponse
from routers.auth import authenticate

source_router = APIRouter()


@source_router.post(
    "/create",
    summary="Create a source (within a category)",
    response_model=AcknowledgeResponse,
)
def create_source(
    category_name_hash: str,
    source_name: str,
    source_url: str,
    user: User = Depends(authenticate),
) -> AcknowledgeResponse:
    cat = Category.read(user_hash=user.name_hash, name_hash=category_name_hash)
    source = Source(
        user_hash=user.name_hash,
        category_hash=category_name_hash,
        name=source_name,
        url=source_url,
    )
    cat.add_source(source)
    return AcknowledgeResponse()


@source_router.get(
    "/items", summary="Get all items in a source", response_model=List[ItemResponse]
)
def get_items(
    category_name_hash: str,
    source_name_hash: str,
    start: int = 0,
    end: int = -1,
    user: User = Depends(authenticate),
) -> List[ItemResponse]:
    try:
        source = Source.read(
            user_hash=user.name_hash,
            category_hash=category_name_hash,
            source_hash=source_name_hash,
        )
        items = source.query_items(start=start, end=end)
        return [ItemResponse.from_db_model(item) for item in items]
    except Exception:
        raise HTTPException(status_code=404, detail="Source not found")


@source_router.delete(
    "/delete",
    summary="Delete a source",
    response_model=AcknowledgeResponse,
)
def delete_source(
    category_name_hash: str, source_name_hash: str, user: User = Depends(authenticate)
) -> AcknowledgeResponse:
    cat = Category.read(user_hash=user.name_hash, name_hash=category_name_hash)
    source = Source.read(
        user_hash=user.name_hash,
        category_hash=category_name_hash,
        source_hash=source_name_hash,
    )
    cat.delete_source(source)
    return AcknowledgeResponse
