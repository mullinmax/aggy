from pydantic import HttpUrl, constr
from datetime import datetime

from shared.db.base import BlinderBaseModel, r

class Item(BlinderBaseModel):
    url_hash: str
    title: constr(strict=True, min_length=1)
    content: str
    author: str
    image_url: str
    url: HttpUrl
    domain: str
    excerpt: str
    date_published: datetime = None

    @classmethod
    def read(cls, url_hash):
        return Item(
            **r.hgetall(f'ITEM:{url_hash}'),
            url_hash=url_hash
        )

    # @property
    # def preview_image(self):
    #     if self.image_key is None:
    #         return None
        
    #     return r.get(self.image_key)