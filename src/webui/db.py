import os
import redis
from pydantic import BaseModel, HttpUrl, constr, ValidationError
from uuid import uuid4
from typing import List, Set

REDIS_HOST = os.getenv('REDIS_HOST')
REDIS_PORT = os.getenv('REDIS_PORT')
r = redis.Redis(host=REDIS_HOST, port=int(REDIS_PORT), decode_responses=True, db=0)

class FeedAlreadyExistsError(Exception):
    pass

class FeedNotFoundError(Exception):
    pass

def init_db():
    r.set("SCHEMA_VERSION", "1.0.0")

class Category(BaseModel):
    user_hash: str
    name: constr(strict=True, min_length=1)
    uuid: str = ""  # UUID is generated if not provided

    def create(self):
        if not self.uuid:
            self.uuid = str(uuid4())
        category_key = f"USER:{self.user_hash}:CATEGORY:{self.uuid}"
        
        if not r.exists(category_key):
            r.hset(category_key, mapping={'name': self.name, 'user_hash': self.user_hash})
            r.sadd(f"USER:{self.user_hash}:CATEGORIES", self.uuid)
        
        return self.uuid

    @staticmethod
    def read_all(user_hash) -> List['Category']:
        category_uuids = r.smembers(f"USER:{user_hash}:CATEGORIES")
        categories = []
        for uuid in category_uuids:
            category_data = r.hgetall(f"USER:{user_hash}:CATEGORY:{uuid}")
            categories.append(Category(**category_data, uuid=uuid))
        return categories

class Feed(BaseModel):
    user: str
    name: constr(strict=True, min_length=1)
    url: HttpUrl
    category_uuids: Set[str] = set()  # Set of category UUIDs
    uuid: str = ""  # UUID is generated if not provided

    def create(self):
        if not self.uuid:
            self.uuid = str(uuid4())
        feed_key = f"USER:{self.user_hash}:FEED:{self.uuid}"
        
        if not r.exists(feed_key):
            r.hset(feed_key, mapping={
                'url': self.url,
                'name': self.name,
                'user': self.user_hash
                }
            )
            for category_uuid in self.category_uuids:
                self._add_to_category(category_uuid)
        
        return self.uuid

    def _add_to_category(self, category_uuid):
        r.sadd(f"USER:{self.user_hash}:CATEGORY:{category_uuid}:FEEDS", self.uuid)
        r.sadd(f"USER:{self.user_hash}:FEED:{self.uuid}:CATEGORIES", category_uuid)

    def update_categories(self, new_category_uuids: Set[str]):
        # Validate new categories exist
        valid_new_categories = set()
        for category_uuid in new_category_uuids:
            if r.exists(f"USER:{self.user_hash}:CATEGORY:{category_uuid}"):
                valid_new_categories.add(category_uuid)
        
        # Proceed only if there are valid new categories
        if not valid_new_categories:
            raise ValueError("No valid new categories provided.")
        
        # Get current categories
        current_categories = r.smembers(f"USER:{self.user_hash}:FEED:{self.uuid}:CATEGORIES")

        # Find categories to remove (those not in new valid categories)
        categories_to_remove = current_categories - valid_new_categories

        # Remove feed from categories no longer associated with
        for category_uuid in categories_to_remove:
            r.srem(f"USER:{self.user_hash}:CATEGORY:{category_uuid}:FEEDS", self.uuid)
            r.srem(f"USER:{self.user_hash}:FEED:{self.uuid}:CATEGORIES", category_uuid)

        # Find new categories to add (those not in current categories)
        categories_to_add = valid_new_categories - current_categories

        # Add feed to new categories
        for category_uuid in categories_to_add:
            self._add_to_category(category_uuid)

    @staticmethod
    def read(user_hash, feed_uuid) -> 'Feed':
        feed_key = f"USER:{self.user_hash}:FEED:{feed_uuid}"
        if r.exists(feed_key):
            feed_data = r.hgetall(feed_key)
            category_uuids = r.smembers(f"USER:{self.user_hash}:FEED:{feed_uuid}:CATEGORIES")
            return Feed(**feed_data, category_uuids=category_uuids, uuid=feed_uuid)
        else:
            return None

    @staticmethod
    def read_all(user) -> List['Feed']:
        feed_uuids = r.keys(f"USER:{user}:FEED:*")
        feeds = []
        for uuid in feed_uuids:
            feed_data = r.hgetall(f"USER:{self.user_hash}:FEED:{uuid}")
            category_uuids = r.smembers(f"USER:{self.user_hash}:FEED:{uuid}:CATEGORIES")
            feeds.append(Feed(**feed_data, category_uuids=category_uuids, uuid=uuid))
        return feeds

    def delete(self):
        feed_key = f"USER:{self.user_hash}:FEED:{self.uuid}"
        if r.exists(feed_key):
            # Clean up category memberships
            category_uuids = r.smembers(f"USER:{self.user_hash}:FEED:{self.uuid}:CATEGORIES")
            for category_uuid in category_uuids:
                r.srem(f"USER:{self.user_hash}:CATEGORY:{category_uuid}:FEEDS", self.uuid)
            r.delete(feed_key)
