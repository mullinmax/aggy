from flask import Flask, render_template, request, redirect, url_for
import redis
import json
import bleach
import os
import logging
import base64
import requests

app = Flask(__name__)

# Environment variables for Redis
REDIS_HOST = os.getenv('REDIS_HOST')
REDIS_PORT = os.getenv('REDIS_PORT')
INGEST_HOST = os.getenv('INGEST_HOST')
INGEST_PORT = os.getenv('INGEST_PORT')

# Connect to Redis
def get_redis_conn(decode_responses=True):
    return redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=decode_responses)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def trigger_feed_processing(feed_key):
    """Sends a POST request to the ingestion engine to process a specific feed."""
    url = f"http://{INGEST_HOST}:{INGEST_PORT}/trigger_feed"
    data = {'feed_key': feed_key}
    try:
        response = requests.post(url, json=data)
        if response.status_code == 200:
            return True
        else:
            logging.error(f"Failed to trigger feed processing: {response.text}")
            return False
    except requests.RequestException as e:
        logging.error(f"Error triggering feed processing: {e}")
        return False

@app.route('/add_feed', methods=['GET', 'POST'])
def add_feed():
    r = get_redis_conn()
    if request.method == 'POST':
        feed_name = request.form.get('feed_name')
        feed_url = request.form.get('feed_url')
        feed_category = request.form.get('feed_category')

        if feed_name and feed_url:
            feed_key = f"feed:{feed_name}"
            feed_data = {
                'name': feed_name,
                'url': feed_url,
                'category': feed_category
            }

            # Save to Redis
            r.set(feed_key, json.dumps(feed_data))
            r.sadd("categories", feed_category)
            r.sadd(f"category:{feed_category}", f"feed:{feed_name}")
            r.bgsave()

            # Trigger the ingestion engine to process the new feed
            if trigger_feed_processing(feed_key):
                logging.info(f"Triggered processing for feed: {feed_name}")
            else:
                logging.error(f"Failed to trigger processing for feed: {feed_name}")

            return redirect(url_for('index'))

    return render_template('add_feed.html')

def get_categories():
    r = get_redis_conn()
    categories = r.smembers("categories")
    category_data = {}
    for category in categories:
        feeds = r.smembers(f"category:{category}")
        category_data[category] = [json.loads(r.get(feed)) for feed in feeds]
    return category_data

def get_items_for_category(category_name=None):
    r = get_redis_conn()
    feed_items = []
    category_feeds = r.smembers(f"category:{category_name}") if category_name else r.keys('feed:*')
    
    for feed_key in category_feeds:
        feed_items_keys = r.smembers(f"{feed_key}:items")
        for item_key in feed_items_keys:
            item = json.loads(r.get(item_key))
            preprocess_item(item)
            feed_items.append(item)
    
    return feed_items

def preprocess_item(item):
    # Create a Redis connection without response decoding for binary data
    r_binary = get_redis_conn(decode_responses=False)

    image_key = item.get('image_key')
    if image_key:
        image_data = r_binary.get(image_key)  # Fetch as bytes
        if image_data:
            item['image_data'] = base64.b64encode(image_data).decode('utf-8')

    # Sanitize other fields using the regular Redis connection
    r = get_redis_conn()
    for field, value in item.items():
        if isinstance(value, str):
            item[field] = bleach.clean(value, strip=True)


@app.route('/')
@app.route('/category/<category_name>')
def index(category_name=None):
    categories = get_categories()
    feed_items = get_items_for_category(category_name)
    return render_template('index.html', categories=categories, feed_items=feed_items, current_category=category_name)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
