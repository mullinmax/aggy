import os
import redis
from pydantic import BaseModel, HttpUrl, constr, ValidationError, validator

REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
REDIS_PORT = os.getenv('REDIS_PORT', 6379)
r = redis.Redis(host=REDIS_HOST, port=int(REDIS_PORT), decode_responses=True, db=0)

class FeedAlreadyExistsError(Exception):
    pass

class FeedNotFoundError(Exception):
    pass

def init_db():
    r.set("SCHEMA_VERSION", "1.0.0")

class Feed(BaseModel):
    user: str
    name: constr(strict=True, min_length=1)
    url: HttpUrl
    category: constr(strict=True, min_length=1)

    # @validator('name', 'category')
    # def no_colons_allowed(cls, v, field):
    #     if ':' in v:
    #         raise ValueError(f"The {field.name} cannot contain colons (:)")
    #     return v

    def create(self):
        feed_key = f"USER:{self.user}:FEED:{self.name}"
        category_key = f"USER:{self.user}:CATEGORY:{self.category}"
        feeds_key = f"{category_key}:FEEDS"

        # Check if the feed already exists
        if r.exists(feed_key):
            raise Exception(f'Feed: {feed_key} already exists')

        # Use ZADD to add the category and feed to sorted sets
        # Assuming a default score for demonstration purposes. Adjust as needed.
        default_score = 0
        r.zadd(f"USER:{self.user}:CATEGORIES", {category_key: default_score}, nx=True)
        r.zadd(feeds_key, {feed_key: default_score}, nx=True)

        # Set feed details
        r.hset(feed_key, mapping={
            'url': self.url,
            'category': self.category
            # Include other details as necessary
        })

    @classmethod
    def read(cls, user, feed_name):
        feed_key = f"USER:{user}:FEED:{feed_name}"
        if not r.exists(feed_key):
            raise FeedNotFoundError(f'Feed {feed_name} not found for user {user}')
        
        feed_data = r.hgetall(feed_key)
        return cls(user=user, name=feed_name, **feed_data)

    def delete(self):
        feed_key = f"USER:{self.user}:FEED:{self.name}"
        if not r.exists(feed_key):
            raise FeedNotFoundError(f'Feed {self.name} not found for user {self.user}')
        
        # r.
        r.delete(feed_key)
        # Optionally remove the feed from the category set





# create category
def create_category(category):
    r.zadd("CATEGORIES", 0, f"CATEGORY:{category}:FEEDS", nx=True)

# read categories
def read_categories():
    return r.zrange("CATEGORIES", 0 -1)

# create feed
def create_feed(category, feed_name, url):
    create_category(category)
    r.hset(f"CATEGORY:{category}:FEED:{feed_name}", mapping={
        'url':url,
        'unread_items_key':f'CATEGORY:{category}:FEED:{feed_name}:UNREAD_ITEMS',
        'items_key':f'CATEGORY:{category}:FEED:{feed_name}:ITEMS'
    })

# read feeds
def read_feed(category, feed):
    return r.hget(f"CATEGORY:{category}:FEED:{feed_name}")

# update feed
def update_feed():
    pass

# delete feed
def delete_feed():
    pass



# create item
def create_item(category, feed, link, title, content, image_key=None):
    feed_key = f'CATEGORY:{category}:FEED:{feed}'
    # r.
    r.hset(f"{feed_key}:ITEM:{link}", mapping={
        'title':title,
        'content':content,
        'image':image_key
    })

# read item
def read_item(category, feed, link):
    return r.hget(f"CATEGORY:{category}:FEED:{feed_name}:ITEM:{link}")

# update item
def update_item():
    pass

# delete item
def delete_item():
    pass
