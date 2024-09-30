from fastapi import APIRouter, Depends, HTTPException

from typing import List, Union

from db.feed import Feed
from db.source import Source
from db.user import User
from route_models.item import ItemResponse
from route_models.acknowledge import AcknowledgeResponse
from routers.auth import authenticate

source_router = APIRouter()


@source_router.post(
    "/create",
    summary="Create a source (within a feed)",
    response_model=AcknowledgeResponse,
)
def create_source(
    feed_name_hash: str,
    source_name: str,
    source_url: str,
    user: User = Depends(authenticate),
) -> AcknowledgeResponse:
    feed = Feed.read(user_hash=user.name_hash, name_hash=feed_name_hash)
    source = Source(
        user_hash=user.name_hash,
        feed_hash=feed_name_hash,
        name=source_name,
        url=source_url,
    )
    feed.add_source(source)
    return AcknowledgeResponse()


@source_router.get(
    "/items", summary="Get all items in a source", response_model=List[ItemResponse]
)
def get_items(
    feed_name_hash: str,
    source_name_hash: str,
    skip: Union[int, None] = None,
    limit: Union[int, None] = None,
    user: User = Depends(authenticate),
) -> List[ItemResponse]:
    try:
        source = Source.read(
            user_hash=user.name_hash,
            feed_hash=feed_name_hash,
            source_hash=source_name_hash,
        )
        items = source.query_items(skip=skip, limit=limit)
        return [ItemResponse.from_db_model(item) for item in items]
    except Exception:
        raise HTTPException(status_code=404, detail="Source not found")


@source_router.delete(
    "/delete",
    summary="Delete a source",
    response_model=AcknowledgeResponse,
)
def delete_source(
    feed_name_hash: str, source_name_hash: str, user: User = Depends(authenticate)
) -> AcknowledgeResponse:
    feed = Feed.read(user_hash=user.name_hash, name_hash=feed_name_hash)
    source = Source.read(
        user_hash=user.name_hash,
        feed_hash=feed_name_hash,
        source_hash=source_name_hash,
    )
    feed.delete_source(source)
    return AcknowledgeResponse
