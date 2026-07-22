from typing import Optional

from .base import BaseRouteModel

from db.list import UserList


class ListResponse(BaseRouteModel):
    list_name: str
    list_name_hash: str
    # Number of items in the list (filled in by /list/list).
    list_item_count: Optional[int] = None
    # Whether a queried item is in this list (filled in when /list/list is
    # called with item_url_hash, to drive the add-to-list checklist).
    list_contains_item: Optional[bool] = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "list_name": "Watch later",
                "list_name_hash": "982d98h98hf1uhfdi1sdhu",
            }
        }
    }

    @classmethod
    def from_db_model(
        cls,
        db_model: UserList,
        item_count: int = None,
        contains_item: bool = None,
    ):
        return cls(
            list_name=db_model.name,
            list_name_hash=db_model.name_hash,
            list_item_count=item_count,
            list_contains_item=contains_item,
        )
