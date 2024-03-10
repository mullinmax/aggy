from pydantic import BaseModel, HttpUrl, validator, constr, root_validator
from datetime import datetime
import dateparser
from bleach import clean
from typing import Optional
import hashlib

from .base import BlinderBaseModel, r

class ItemBase(BlinderBaseModel):
    url: HttpUrl
    url_hash: str
    content: Optional[str] = None
    date_published: Optional[datetime] = None

    @root_validator(pre=True)
    def ensure_url_hash(cls, values):
        url = values.get('url')
        url_hash = values.get('url_hash')
        if url and not url_hash:
            values['url_hash'] = hashlib.sha256(str(url).encode('utf-8')).hexdigest()
        elif not url:
            raise ValueError("URL must be provided to generate url_hash")
        return values

    @classmethod
    def create(cls, item):
        if not item.url_hash:
            item.url_hash = item.generate_url_hash()
        item_json = item.json()
        r.set(f'ITEM:{item.url_hash}', item_json)


    @classmethod
    def read(cls, url_hash):
        item_json = r.get(f'ITEM:{url_hash}')
        if item_json:
            return cls.parse_raw(item_json)
        return None


    @classmethod
    def update(cls, url_hash, **updates):
        # Fetch the existing item
        item_json = r.get(f'ITEM:{url_hash}')
        if item_json:
            # Deserialize JSON string to an item instance
            item = cls.parse_raw(item_json)
            
            # Update the item with the provided changes
            for field, value in updates.items():
                setattr(item, field, value)
            
            # Serialize the updated item back to a JSON string
            updated_item_json = item.json()
            
            # Save the updated item back to Redis
            r.set(f'ITEM:{url_hash}', updated_item_json)
        else:
            raise ValueError(f"Item with url_hash {url_hash} not found")


    @classmethod
    def delete(cls, url_hash):
        r.delete(f'ITEM:{url_hash}')

    @validator('content', pre=True, allow_reuse=True)
    def sanitize_content(cls, v):
        if v:
            return clean(
                str(v), 
                tags=['p', 'b', 'i', 'u', 'a', 'img'],
                attributes={'a': ['href', 'title'], 'img': ['src', 'alt']},
                strip=True
            )
        return v

    @validator('date_published', pre=True, allow_reuse=True)
    def parse_date_published(cls, v):
        if v is None:
            return None
        parsed_date = dateparser.parse(v)
        if parsed_date:
            return parsed_date
        raise ValueError("Invalid date format")

    @validator('title', 'author', 'image_url', 'domain', 'excerpt', 'content', pre=True, allow_reuse=True, check_fields=False)
    def remove_html_tags(cls, v):
        if v:
            return clean(
                str(v), 
                tags=[],
                attributes={},
                strip=True
            )
        return v


class ItemStrict(ItemBase):
    title: constr(strict=True, min_length=1)
    author: str
    image_url: str
    domain: str
    excerpt: str

class ItemLoose(ItemStrict):
    title: Optional[constr(strict=True, min_length=1)] = None
    author: Optional[str] = None
    image_url: Optional[str] = None
    domain: Optional[str] = None
    excerpt: Optional[str] = None
