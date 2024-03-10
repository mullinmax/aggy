from pydantic import constr, HttpUrl
from typing import List, Set
from flask import current_app

from .base import BlinderBaseModel, r

class Feed(BlinderBaseModel):
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