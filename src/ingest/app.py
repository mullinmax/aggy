import os
import time
import json
import requests
import feedparser
import bleach
import redis
from croniter import croniter
from datetime import datetime
import logging
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify
from threading import Thread

app = Flask(__name__)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Environment variables
REDIS_HOST = os.getenv('REDIS_HOST', 'blinder-db')
REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
EXTRACT_HOST = os.getenv('EXTRACT_HOST', 'blinder-extract')
EXTRACT_PORT = int(os.getenv('EXTRACT_PORT', 3000))
CRON_EXPRESSIONS = os.getenv('CRON_EXPRESSIONS', '* * * * *')  # Example cron expressions

def extract_content(url):
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0'
        }
        headers_json = json.dumps(headers)

        response = requests.get(
            f'http://{EXTRACT_HOST}:{EXTRACT_PORT}/parser/',
            params={
                'url': url,
                'headers': headers_json
            },
            timeout=10
        )

        if response.status_code == 200:
            return response.json()
        else:
            logging.error(f"Error extracting content: {response.status_code}, Response: {response.text}")
            return {}
    except requests.RequestException as e:
        logging.error(f"Error in extract request: {e}")
        return {}

def extract_og_image(url):
    """Extracts Open Graph image from a given URL."""
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            og_image = soup.find('meta', property='og:image')
            if og_image and og_image['content']:
                return og_image['content']
    except requests.RequestException as e:
        logging.info(f"Error fetching Open Graph image: {e}")
    return ''

def sanitize_content(content):
    logging.info(content)
    if content is None:
        return ''
    allowed_tags = ['p', 'br', 'strong', 'em', 'ul', 'ol', 'li', 'a']
    return bleach.clean(content, tags=allowed_tags, attributes=['href'], strip=True)

def get_redis_conn():
    return redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

def download_image(url):
    if url is None or len(url) < 5:
        return None

    r = get_redis_conn()
    image_key = f'img:{url}'

    if r.exists(image_key):
        return image_key

    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'}
    try:
        response = requests.get(url, headers=headers, timeout=10, allow_redirects=True)
        if response.status_code == 200 and response.headers.get('Content-Type', '').startswith('image/'):
            # Saving image data to Redis
            r.set(image_key, response.content)
            logging.info(f'Image downloaded and stored: {url}')
            return image_key
        else:
            logging.error(f'Failed to download image: {url} with status code: {response.status_code}')
            return None
    except requests.RequestException as e:
        logging.error(f'Error downloading image: {e}')
        return None

def process_all_feeds():
    logging.info("Fetching and processing feeds...")
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

    user_keys = r.smembers('USERS')
    for user_key in user_keys:
        feed_keys = r.smembers(f"{user_key}:FEEDS")
        for feed_key in feed_keys:
            process_feed(feed_key)
    r.bgsave()

def process_feed(feed_key):
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    logging.info(f'getting items in {feed_key}')
    
    feed_url = r.hget(feed_key, 'url')
    
    if feed_url:
        feed = feedparser.parse(feed_url)

        for entry in feed.entries:
            feed_item_key = f"ITEM:{entry.id}"

            if r.exists(feed_item_key):
                logging.info(f"Item already exists in database: {feed_item_key}")
                continue  

            extracted_content = extract_content(entry.link)
            
            entry_data = {
                'title': extracted_content.get('title') or entry.title,
                'content': extracted_content.get('content') or entry.content[0]['value'],
                'author': extracted_content.get('author') or entry.get('author') or 'Unknown',
                'date_published': extracted_content.get('date_published') or entry.published or str(datetime.today()),
                'image_key': download_image(extracted_content.get('lead_image_url', '')) or download_image(extract_og_image(entry.link)),
                'url': entry.link,
                'domain': extracted_content.get('domain') or entry.link,
                'excerpt': extracted_content.get('excerpt') or entry.content[0]['value']
            }

            r.set(feed_item_key, json.dumps(entry_data))
            r.sadd(f"{feed_key}:items", feed_item_key)
            logging.info(f"Added {feed_item_key}")

@app.route('/trigger_feed', methods=['POST'])
def trigger_feed():
    data = request.json
    feed_key = data.get('feed_key')

    if feed_key:
        # Start processing in a separate thread
        thread = Thread(target=process_feed, args=(feed_key,))
        thread.start()

        return jsonify({"status": "success", "message": f"Processing started for feed: {feed_key}"}), 200
    else:
        return jsonify({"status": "error", "message": "Feed key is required"}), 400


def start_app():
    app.run(host='0.0.0.0', port=9001)

def main():
    thread = Thread(target=start_app)
    thread.start()

    time.sleep(5)
    logging.info("Starting and ingestion process...")
    process_all_feeds()

    cron_expressions = CRON_EXPRESSIONS.split(';')
    next_runs = [croniter(expr, datetime.now()).get_next(datetime) for expr in cron_expressions]
    logging.info(f'next runs:{next_runs}')
    while True:
        now = datetime.now()
        for i, next_run in enumerate(next_runs):
            if now >= next_run:
                process_all_feeds()
                next_runs[i] = croniter(cron_expressions[i], now).get_next(datetime)
                logging.info(f'next runs:{next_runs}')
        time.sleep(1)

if __name__ == "__main__":
    main()
