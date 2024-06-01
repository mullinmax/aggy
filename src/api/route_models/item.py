from datetime import datetime
from typing import Optional

from pydantic import HttpUrl
from .base import BaseRouteModel

from db.item import ItemLoose


class ItemResponse(BaseRouteModel):
    item_url: HttpUrl
    item_author: Optional[str] = None
    item_date_published: Optional[datetime] = None
    item_image_url: Optional[str] = None
    item_title: Optional[str] = None
    item_domain: Optional[str] = None
    item_excerpt: Optional[str] = None
    item_content: Optional[str] = None

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
    def from_db_model(cls, db_model: ItemLoose):
        return cls(
            item_url=db_model.url,
            item_item_author=db_model.author,
            item_date_published=db_model.date_published,
            item_image_url=db_model.image_url,
            item_title=db_model.title,
            item_domain=db_model.domain,
            item_excerpt=db_model.excerpt,
            item_content=db_model.content,
        )
