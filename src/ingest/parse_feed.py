import feedparser
import logging
import redis
import hashlib
import requests
import json
from bs4 import BeautifulSoup

from shared.config import config
from shared import db

def extract_content(url):
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0'
        }
        headers_json = json.dumps(headers)

        response = requests.get(
            f"http://{config.get('EXTRACT_HOST')}:{config.get('EXTRACT_PORT')}/parser/",
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

def parse_feed(feed_key):
    logging.info(f'starting parsing feed with key: {feed_key}')
    r = db.r
    # get url from feed
    url = r.hget(feed_key, 'url')
    if not url:
        logging.error(f'unable to find url for feed_key {feed_key}')


    # find all categories that the feed is a member of
    user_prefix = feed_key.split(':FEED:')[0]
    categories = r.smembers(f'{feed_key}:CATEGORIES')
    category_keys = [f'{user_prefix}:CATEGORY:{category}' for category in categories]

    feed = feedparser.parse(url)
    for entry in feed.entries:
        hashed_url = hashlib.sha256(entry.link.encode()).hexdigest()
        item_key = f'ITEM:{hashed_url}'

        # we're using hlen because we want to check that it exists and has some content
        # in the future we can setup preview refreshing when something isn't right by simply deleting the contents
        if r.hlen(item_key) > 0:
            logging.info(f"Item already exists in database: {item_key}")
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

        r.hmset(item_key, entry_data)
        r.sadd(f"{feed_key}:ITEMS", hashed_url)
        logging.info(f"Added {hashed_url} to {feed_key}")
        for category_key in category_keys:
            logging.info(f'Adding item {hashed_url} to category {category_key}')
            r.zadd(f"{category_key}:ITEMS", {hashed_url:0}, nx=True)

def download_image(url):
    if url is None or len(url) < 5:
        return None

    r = db.r
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