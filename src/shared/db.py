import redis
from pydantic import BaseModel, HttpUrl, constr, ValidationError
from uuid import uuid4
from typing import List, Set
import hashlib
from flask import current_app

from shared.config import config

r = redis.Redis(
    host=config.get('REDIS_HOST'), 
    port=int(config.get('REDIS_PORT')), 
    decode_responses=True, 
    db=0
)

def init_db():
    r.set("SCHEMA_VERSION", "1.0.0")

class Category(BaseModel):
    user_hash: str
    name: constr(strict=True, min_length=1)
    name_hash: str = ""  # generated if not provided

    @property
    def __key__(self):
        if not self.name_hash:
            self.name_hash = hashlib.sha256(self.name.encode()).hexdigest()
        return f"USER:{self.user_hash}:CATEGORY:{self.name_hash}"

    def create(self):
        category_key = self.__key__
        
        if r.exists(category_key):
            raise Exception(f"Category with name {self.name} already exists")    

        r.hset(category_key, mapping={'name': self.name, 'user_hash': self.user_hash})
        r.sadd(f"USER:{self.user_hash}:CATEGORIES", self.name_hash)
        
        return category_key

    @classmethod
    def read(cls, user_hash, name_hash):
        category_data = r.hgetall(f"USER:{user_hash}:CATEGORY:{name_hash}")
        current_app.logger.info(category_data)
        if category_data:
            return Category(**category_data, name_hash=name_hash)
        else:
            raise Exception("Category does not exist")

    @classmethod
    def read_all(cls, user_hash) -> List['Category']:
        category_name_hashs = r.smembers(f"USER:{user_hash}:CATEGORIES")
        categories = []
        for name_hash in category_name_hashs:
            categories.append(cls.read(user_hash, name_hash))
        return categories

    def get_all_items(self):
        current_app.logger.info(f'getting all items in {self.__key__}')
        url_hashes = r.zrange(f'{self.__key__}:ITEMS', 0, -1)
        current_app.logger.info(f'{url_hashes=}')
        items = [Item.read(url_hash) for url_hash in url_hashes]
        current_app.logger.info(f'items recovered: {items}')
        return items

class Feed(BaseModel):
    user_hash: str
    name: constr(strict=True, min_length=1)
    url: HttpUrl
    category_hashes: Set[str] # Set of category UUIDs
    name_hash: str = ""  # generated if not provided

    def create(self):
        if not self.name_hash:
            self.name_hash = hashlib.sha256(self.name.encode()).hexdigest()
        feed_key = f"USER:{self.user_hash}:FEED:{self.name_hash}"
        
        if r.exists(feed_key):
            raise Exception(f'Cannot create duplicate feed {feed_key}')            

        r.hset(
            feed_key, 
            mapping={
                'url': str(self.url),
                'name': self.name,
                'user_hash': self.user_hash
            }
        )
        for category_hash in self.category_hashes:
            self._add_to_category(category_hash)
    
        r.sadd(f"USER:{self.user_hash}:FEEDS", self.name_hash)
        r.zadd(config.get("FEEDS_TO_INGEST_KEY"), mapping={feed_key:0})

        return self.name_hash

    def _add_to_category(self, category_hash):
        r.sadd(f"USER:{self.user_hash}:CATEGORY:{category_hash}:FEEDS", self.name_hash)
        r.sadd(f"USER:{self.user_hash}:FEED:{self.name_hash}:CATEGORIES", category_hash)

    def update_categories(self, new_category_hashes: Set[str]):
        # Validate new categories exist
        valid_new_categories = set()
        for category_hash in new_category_hashes:
            if r.exists(f"USER:{self.user_hash}:CATEGORY:{category_hash}"):
                valid_new_categories.add(category_hash)
        
        # Proceed only if there are valid new categories
        if not valid_new_categories:
            raise ValueError("No valid new categories provided.")
        
        # Get current categories
        current_categories = r.smembers(f"USER:{self.user_hash}:FEED:{self.name_hash}:CATEGORIES")

        # Find categories to remove (those not in new valid categories)
        categories_to_remove = current_categories - valid_new_categories

        # Remove feed from categories no longer associated with
        for category_hash in categories_to_remove:
            r.srem(f"USER:{self.user_hash}:CATEGORY:{category_hash}:FEEDS", self.name_hash)
            r.srem(f"USER:{self.user_hash}:FEED:{self.name_hash}:CATEGORIES", category_hash)

        # Find new categories to add (those not in current categories)
        categories_to_add = valid_new_categories - current_categories

        # Add feed to new categories
        for category_hash in categories_to_add:
            self._add_to_category(category_hash)

    @staticmethod
    def read(user_hash, feed_hash) -> 'Feed':
        feed_key = f"USER:{self.user_hash}:FEED:{feed_hash}"
        if r.exists(feed_key):
            feed_data = r.hgetall(feed_key)
            category_hashes = r.smembers(f"USER:{user_hash}:FEED:{feed_hash}:CATEGORIES")
            return Feed(**feed_data, category_hashes=category_hashes, name_hash=feed_hash)
        else:
            return None

    @staticmethod
    def read_all(user_hash) -> List['Feed']:
        feed_hashes = r.smembers(f"USER:{user_hash}:FEEDS")
        feeds = []
        for feed_hash in feed_hashes:
            feed_data = r.hgetall(f"USER:{user_hash}:FEED:{feed_hash}")
            feed_data['category_hashes'] = r.smembers(f"USER:{user_hash}:FEED:{feed_hash}:CATEGORIES")
            feed_data['feed_hash'] = feed_hash
            current_app.logger.info(feed_data)
            feeds.append(Feed(**feed_data))
        return feeds

    def delete(self):
        feed_key = f"USER:{self.user_hash}:FEED:{self.name_hash}"
        if r.exists(feed_key):
            # Clean up category memberships
            category_hashes = r.smembers(f"USER:{self.user_hash}:FEED:{self.name_hash}:CATEGORIES")
            for category_hash in category_hashes:
                r.srem(f"USER:{self.user_hash}:CATEGORY:{category_hash}:FEEDS", self.name_hash)
            r.srem(f"USER:{self.user_hash}:FEEDS", feed_key)
            r.delete(feed_key)

class Item(BaseModel):
    url_hash: str
    title: constr(strict=True, min_length=1)
    content: str
    author: str
    image_key: str
    url: HttpUrl
    domain: str
    excerpt: str

    @classmethod
    def read(cls, url_hash):
        return Item(
            **r.hgetall(f'ITEM:{url_hash}'),
            url_hash=url_hash
        )

