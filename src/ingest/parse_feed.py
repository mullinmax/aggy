import feedparser
import logging
import hashlib
import requests
import json
from bs4 import BeautifulSoup
from bleach import clean
import dateparser

from shared.config import config
from shared.db import r, ItemLoose, ItemStrict

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
    # get url from feed
    url = r.hget(feed_key, 'url')
    if not url:
        logging.error(f'unable to find url for feed_key {feed_key}')


    # find all categories that the feed is a member of
    user_prefix = feed_key.split(':FEED:')[0]
    categories = r.smembers(f'{feed_key}:CATEGORIES')
    category_keys = [f'{user_prefix}:CATEGORY:{category}' for category in categories]

    feed = feedparser.parse(url)
    url_hashes_to_link = []
    for entry in feed.entries:
        url_hash = hashlib.sha256(entry.link.encode()).hexdigest()
        item_key = f'ITEM:{url_hash}'

        # we're using hlen because we want to check that it exists and has some content
        # in the future we can setup preview refreshing when something isn't right by simply deleting the contents
        if r.hlen(item_key) > 0:
            logging.info(f"Item already exists in database: {item_key}")
            url_hashes_to_link.append(url_hash)
            continue  

        extracted_content = extract_content(entry.link)

        entry_data = {
            'title': extracted_content.get('title') or entry.title,
            'content': extracted_content.get('content') or entry.content[0]['value'],
            'author': extracted_content.get('author') or entry.get('author') or 'Unknown',
            'date_published': extracted_content.get('date_published') or entry.published or str(datetime.today()),
            'image_url': extracted_content.get('lead_image_url', '') or extract_og_image(entry.link),
            'url': entry.link,
            'domain': extracted_content.get('domain') or entry.link,
            'excerpt': extracted_content.get('excerpt') or entry.content[0]['value']
        }

        entry_data['date_published'] = clean_date(entry_data['date_published'])

        sanitized_item = {}
        for k, v in entry_data.items():
            sanitized_item[k] = sanitize(v)

        item = ItemStrict(**entry_data)
        ItemStrict.create(item)

        # r.hmset(item_key, entry_data)
        url_hashes_to_link.append(item.url_hash)
    
    for url_hash in url_hashes_to_link:
        r.sadd(f"{feed_key}:ITEMS", url_hash)
        logging.info(f"Added {url_hash} to {feed_key}")
        for category_key in category_keys:
            logging.info(f'Adding item {url_hash} to category {category_key}')
            r.zadd(f"{category_key}:ITEMS", {url_hash:0}, nx=True)

def sanitize(x): 
    return clean(
        x, 
        tags = ['p', 'b', 'i', 'u', 'a', 'img'],
        attributes = {'a': ['href', 'title'], 'img': ['src', 'alt']}
    )

def clean_date(date_str):
    return str(dateparser.parse(str(date_str)))