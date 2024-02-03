import feedparser
import redis
import json
import bleach
import requests
import hashlib
import base64
import urllib.parse

# Environment variables
REDIS_HOST = 'blinder-db'
REDIS_PORT = 6379
EXTRACT_HOST = 'blinder-extract'
EXTRACT_PORT = 3000

# RSS Feed URL
FEED_URL = 'https://rss-bridge.org/bridge01/?action=display&bridge=YoutubeBridge&context=By+custom+name&custom=%40TeslaDaily&duration_min=&duration_max=&format=Atom'

def extract_content(url):
    try:
        # Define headers to mimic a modern browser
        headers = {
            'User-Agent': 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)'
        }

        # Convert headers to JSON string
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
            print(f"Error extracting content: {response.status_code}, Response: {response.text}")
    except requests.RequestException as e:
        print(f"Error in extract request: {e}")
    return {}

def sanitize_content(content):
    if content is None:
        return ''  # Return an empty string if content is None
        
    allowed_tags = ['p', 'br', 'strong', 'em', 'ul', 'ol', 'li', 'a']
    return bleach.clean(content, tags=allowed_tags, attributes=['href'], strip=True)

def main():
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

    feed = feedparser.parse(FEED_URL)

    for entry in feed.entries:
        extracted_content = extract_content(entry.link)

        entry_data = {
            'title': sanitize_content(extracted_content.get('title', '')),
            'content': sanitize_content(extracted_content.get('content', '')),
            'author': sanitize_content(extracted_content.get('author', '')),
            'date_published': extracted_content.get('date_published', ''),
            'lead_image_url': extracted_content.get('lead_image_url', ''),
            'dek': sanitize_content(extracted_content.get('dek', '')),
            'next_page_url': extracted_content.get('next_page_url', ''),
            'url': entry.link,
            'domain': extracted_content.get('domain', ''),
            'excerpt': sanitize_content(extracted_content.get('excerpt', '')),
            'word_count': extracted_content.get('word_count', 0),
            'direction': extracted_content.get('direction', 'ltr'),
            'total_pages': extracted_content.get('total_pages', 1),
            'rendered_pages': extracted_content.get('rendered_pages', 1)
        }
        print(f"adding {entry_data['title']}")
        r.set(f"rss:{entry.id}", json.dumps(entry_data))

if __name__ == "__main__":
    main()
