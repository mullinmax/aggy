from datetime import datetime
from typing import Optional

from pydantic import HttpUrl
from .base import BaseResponseModel

from db.item import ItemLoose


class ItemResponse(BaseResponseModel):
    url: HttpUrl
    author: Optional[str] = None
    date_published: Optional[datetime] = None
    image_url: Optional[str] = None
    title: Optional[str] = None
    domain: Optional[str] = None
    excerpt: Optional[str] = None
    content: Optional[str] = None

    @classmethod
    def from_db_model(cls, db_model: ItemLoose):
        return cls(
            url=db_model.url,
            author=db_model.author,
            date_published=db_model.date_published,
            image_url=db_model.image_url,
            title=db_model.title,
            domain=db_model.domain,
            excerpt=db_model.excerpt,
            content=db_model.content,
        )
