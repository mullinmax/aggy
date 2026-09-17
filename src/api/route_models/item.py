from datetime import datetime
from typing import Dict, List, Optional

from pydantic import HttpUrl
from .base import BaseRouteModel

from db.item import ItemLoose


class ItemResponse(BaseRouteModel):
    item_hash: str
    item_url: HttpUrl
    item_author: Optional[str] = None
    item_date_published: Optional[datetime] = None
    item_image_url: Optional[str] = None
    item_media: Optional[List[Dict[str, Optional[str]]]] = None
    item_title: Optional[str] = None
    item_domain: Optional[str] = None
    item_excerpt: Optional[str] = None
    item_content: Optional[str] = None
    item_source_name: Optional[str] = None
    item_source_color: Optional[str] = None
    item_user_score: Optional[float] = None
    item_is_read: Optional[bool] = None
    item_in_list: Optional[bool] = None
    item_predicted_score: Optional[float] = None
    item_predicted_confidence: Optional[float] = None
    # How many other items are the same content as this one (0 when it is not
    # in a duplicate group), and the group they share, so the hidden members
    # can be asked for.
    item_duplicate_count: Optional[int] = None
    item_duplicate_group: Optional[str] = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "item_url": "https://example.com",
                "item_author": "John Doe",
                "item_date_published": "2021-01-01T00:00:00",
                "item_image_url": "https://example.com/image.jpg",
                "item_title": "Example Title",
                "item_domain": "example.com",
                "item_excerpt": "This is an example excerpt.",
                "item_content": "This is an example content. it's longer than the excerpt most of the time.",
            }
        }
    }

    @classmethod
    def from_db_model(
        cls,
        db_model: ItemLoose,
        source_name: str = None,
        source_color: str = None,
        user_score: float = None,
        is_read: bool = None,
        in_list: bool = None,
        predicted_score: float = None,
        predicted_confidence: float = None,
        duplicate_count: int = None,
        duplicate_group: str = None,
    ):
        return cls(
            item_source_name=source_name,
            item_source_color=source_color,
            item_user_score=user_score,
            item_is_read=is_read,
            item_in_list=in_list,
            item_predicted_score=predicted_score,
            item_predicted_confidence=predicted_confidence,
            item_duplicate_count=duplicate_count,
            item_duplicate_group=duplicate_group,
            item_hash=db_model.url_hash,
            item_url=db_model.url,
            item_author=db_model.author,
            item_date_published=db_model.date_published,
            item_image_url=db_model.image_url,
            item_media=db_model.media,
            item_title=db_model.title,
            item_domain=db_model.domain,
            item_excerpt=db_model.excerpt,
            item_content=db_model.content,
        )


class DuplicateMemberResponse(BaseRouteModel):
    """One member of a duplicate group, as the feed's duplicate badge shows it.

    The feed shows a single member of each group -- whichever the current model
    scores highest -- so this is what the others are, including the shown one
    so the UI can mark it.
    """

    item_hash: str
    item_url: HttpUrl
    item_title: Optional[str] = None
    item_source_name: Optional[str] = None
    item_predicted_score: Optional[float] = None
    item_predicted_confidence: Optional[float] = None
    item_date_published: Optional[datetime] = None
    # What put this item in the group, and how sure that signal is.
    item_duplicate_signal: str
    item_duplicate_confidence: float
    # True for the one the feed is currently showing.
    item_is_shown: bool = False


class ItemDuplicatesResponse(BaseRouteModel):
    duplicate_group: str
    members: List[DuplicateMemberResponse]
