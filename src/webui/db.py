import os
import redis

REDIS_HOST = os.getenv('REDIS_HOST')
REDIS_PORT = os.getenv('REDIS_PORT')
r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT)



# db setup
def init_db():
    # set schema version
    r.set("SCHEMA_VERSION", "0.0.0")

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
    r.
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
