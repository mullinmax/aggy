from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional

from routers.auth import authenticate
from db.list import UserList
from db.item import ItemLoose
from db.user import User
from route_models.list import ListResponse
from route_models.item import ItemResponse
from route_models.acknowledge import AcknowledgeResponse

list_router = APIRouter()


def get_list_by_name_hash(user_hash: str, name_hash: str) -> UserList:
    lst = UserList.read(user_hash=user_hash, name_hash=name_hash)
    if lst is None:
        raise HTTPException(status_code=404, detail="List not found")
    return lst


@list_router.post("/create", summary="Create a list", response_model=ListResponse)
def create_list(list_name: str, user: User = Depends(authenticate)) -> ListResponse:
    name = list_name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="List name cannot be empty")

    lst = UserList(user_hash=user.name_hash, name=name)
    if lst.exists():
        raise HTTPException(
            status_code=409, detail=f'A list named "{name}" already exists'
        )
    lst.create()
    return ListResponse.from_db_model(lst, item_count=0, contains_item=False)


@list_router.get(
    "/list",
    summary="List a user's lists",
    response_model=List[ListResponse],
)
def get_lists(
    item_url_hash: Optional[str] = Query(
        None,
        description="If given, each list reports whether it contains this item "
        "(for the add-to-list checklist).",
    ),
    user: User = Depends(authenticate),
) -> List[ListResponse]:
    return [
        ListResponse.from_db_model(
            lst,
            item_count=lst.item_count(),
            contains_item=(
                lst.contains(item_url_hash) if item_url_hash is not None else None
            ),
        )
        for lst in UserList.read_all(user.name_hash)
    ]


@list_router.get("/get", summary="Get a list", response_model=ListResponse)
def get_list(
    list_name_hash: str, user: User = Depends(authenticate)
) -> ListResponse:
    lst = get_list_by_name_hash(user.name_hash, list_name_hash)
    return ListResponse.from_db_model(lst, item_count=lst.item_count())


@list_router.delete(
    "/delete",
    summary="Delete a list",
    response_model=AcknowledgeResponse,
)
def delete_list(
    list_name_hash: str, user: User = Depends(authenticate)
) -> AcknowledgeResponse:
    lst = get_list_by_name_hash(user.name_hash, list_name_hash)
    lst.delete()
    return AcknowledgeResponse()


@list_router.get(
    "/items",
    summary="List the items in a list",
    response_model=List[ItemResponse],
)
def get_list_items(
    list_name_hash: str, user: User = Depends(authenticate)
) -> List[ItemResponse]:
    lst = get_list_by_name_hash(user.name_hash, list_name_hash)
    return [ItemResponse.from_db_model(item) for item in lst.items()]


@list_router.post(
    "/set_item_lists",
    summary="Set which of the user's lists an item belongs to",
    response_model=AcknowledgeResponse,
)
def set_item_lists(
    item_url_hash: str,
    list_hashes: Optional[str] = Query(
        None, description="Comma-separated list name hashes the item should be in"
    ),
    user: User = Depends(authenticate),
) -> AcknowledgeResponse:
    if not ItemLoose.read(item_url_hash):
        raise HTTPException(status_code=404, detail="Item not found")

    hashes = [h for h in (list_hashes or "").split(",") if h]
    UserList.set_item_membership(
        user_hash=user.name_hash,
        item_url_hash=item_url_hash,
        list_hashes=hashes,
    )
    return AcknowledgeResponse()
