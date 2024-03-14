from pydantic import BaseModel, HttpUrl, validator, constr, root_validator
from datetime import datetime
import dateparser
from bleach import clean
from typing import Optional, List
import hashlib
import html
import requests
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup

from .base import BlinderBaseModel, r

class ItemBase(BlinderBaseModel):
    url: HttpUrl
    author: Optional[str] = None
    date_published: Optional[datetime] = None
    image_url: Optional[str] = None

    @property
    def key(self):
        return f'ITEM:{self.url_hash}'

    @property
    def url_hash(self):
        encoded_str = str(self.url).encode('utf-8')
        return hashlib.sha256(encoded_str).hexdigest()

    def exists(self) -> bool:
        return r.strlen(self.key) > 0

    def create(self):
        r.set(self.key, self.json())

    @classmethod
    def read(cls, url_hash):
        item_json = r.get(f'ITEM:{url_hash}')
        if item_json:
            return cls.parse_raw(item_json)
        return None

    def update(self, **updates):
        item_json = r.get(self.key)
        if item_json:
            item = self.parse_raw(item_json)
            
            for field, value in updates.items():
                setattr(item, field, value)
            
            item.create()
        else:
            raise ValueError(f"Item with url_hash {url_hash} not found")

    def delete(self):
        r.delete(self.key)

    @validator('content', pre=True, allow_reuse=True, check_fields=False)
    def sanitize_and_fix_links(cls, v, values):
        #TODO fix this so it correctly finds and fixes relative links
        if 'url' in values and v:
            soup = BeautifulSoup(str(v), 'html.parser')
            
            # Find all <a> tags with a relative href attribute
            for a_tag in soup.find_all('a', href=True):
                # Check if the link is relative
                href = a_tag['href']
                parsed_href = urlparse(href)
                if not parsed_href.netloc:
                    # Join the relative link with the base URL
                    base_url = str(values['url'])
                    absolute_url = urljoin(base_url, href)
                    a_tag['href'] = absolute_url
            
            # Find and fix relative src in <img> tags
            for img_tag in soup.find_all('img', src=True):
                src = img_tag['src']
                parsed_src = urlparse(src)
                if not parsed_src.netloc:
                    base_url = str(values['url'])
                    absolute_url = urljoin(base_url, src)
                    img_tag['src'] = absolute_url
            
            # Sanitize the potentially modified HTML
            sanitized_html = clean(
                str(soup), 
                tags=['p', 'b', 'i', 'u', 'a', 'img'],
                attributes={'a': ['href', 'title'], 'img': ['src', 'alt']},
                strip=True
            )
            return sanitized_html
        return v

    @validator('date_published', pre=True, allow_reuse=True)
    def parse_date_published(cls, v):
        if v is None:
            return None
        parsed_date = dateparser.parse(str(v))
        if parsed_date:
            return parsed_date
        raise ValueError("Invalid date format")

    @validator('title', 'author', 'domain', 'excerpt', pre=True, allow_reuse=True, check_fields=False)
    def remove_html_tags(cls, v):
        if v:
            return clean(
                str(html.unescape(v)), 
                tags=[],
                attributes={},
                strip=True
            ).strip()
        return v


class ItemStrict(ItemBase):
    title: constr(strict=True, min_length=1)
    domain: str
    excerpt: str
    content: str

class ItemLoose(ItemStrict):
    title: Optional[str] = None
    domain: Optional[str] = None
    excerpt: Optional[str] = None
    content: Optional[str] = None

    @classmethod
    def merge_instances(cls, items: List['ItemLoose']) -> 'ItemLoose':
        if not items:
            raise ValueError("No items to merge")
        
        # Initialize the best instance with the first item's values
        best = cls(
            url=items[0].url,  # Assuming url is the same for all items, as it's the basis of comparison
            author=items[0].author,
            date_published=items[0].date_published,
            title=items[0].title,
            image_url=items[0].image_url,
            domain=items[0].domain,
            excerpt=items[0].excerpt,
            content=items[0].content
        )

        def longest(*items):
            return max(*items, key=len)

        def shortest(*items):
            return min(*items, key=len)

        for item in items[1:]:  # Start from the second item
            # prefer non-null values
            best.title = best.title or item.title
            best.image_url = best.image_url or item.image_url
            best.domain = best.domain or item.domain
            best.excerpt = best.excerpt or item.excerpt
            best.content = best.content or item.content
            best.author = best.author or item.author
            best.date_published = best.date_published or item.date_published 

            # pick the title closest to 100 characters
            if best.title and item.title:
                if abs(100 - len(item.title)) < abs(100 - len(best.title)):
                        best.title = item.title
            
            #TODO take the largest image (needs caching server)

            # take the shortest domain
            if best.domain and item.domain:
                best.domain = shortest(best.domain, item.domain)

            # take the largest excerpt between 10 and 250 characters long
            if best.excerpt and item.excerpt:
                l = len(item.excerpt)
                if 10 < l < 250:
                    l = len(best.excerpt)
                    if 10 < l < 250:
                        best.excerpt = longest(best.excerpt, item.excerpt)
                    else:
                        best.excerpt = item.excerpt

            # prefer content with html, then longest
            if best.content and item.content:
                if '<' in item.content and '<' not in best.content:
                    best.content = item.content
                else:
                    best.content = longest(best.content, item.content)
            
            if best.author and item.author and len(item.author):
                best.author = shortest(best.author, item.author)

            # use the oldest date if there are multiple
            if best.date_published and item.date_published:
                best.date_published = min(best.date_published, item.date_published)
        
        if not best.excerpt and best.content:
            best.excerpt = best.content[:250]

        return best