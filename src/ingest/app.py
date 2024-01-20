import feedparser
import redis
import json
import bleach
import requests
from bs4 import BeautifulSoup

# Environment variables for Redis
REDIS_HOST = 'blinder-db'
REDIS_PORT = 6379

# RSS Feed URL
FEED_URL = 'https://rss-bridge.org/bridge01/?action=display&bridge=YoutubeBridge&context=By+custom+name&custom=%40TeslaDaily&duration_min=&duration_max=&format=Atom'

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
        print(f"Error fetching Open Graph image: {e}")
    return ''

def extract_image(entry):
    """Extracts image from the feed entry."""
    if 'media_content' in entry and len(entry.media_content) > 0:
        return entry.media_content[0].get('url', '')
    elif 'media_thumbnail' in entry and len(entry.media_thumbnail) > 0:
        return entry.media_thumbnail[0].get('url', '')
    elif 'enclosures' in entry and len(entry.enclosures) > 0:
        return entry.enclosures[0].get('href', '')
    return ''  # Default case if no image found

def main():
    """Main function to ingest and store RSS feed items."""
    # Connect to Redis
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

    # Parse the RSS feed
    feed = feedparser.parse(FEED_URL)

    # Iterate over feed entries and save to Redis
    for entry in feed.entries:
        # Attempt to extract image from the feed entry
        image_url = extract_image(entry)

        # If no image in the feed, try to extract Open Graph image
        if not image_url:
            image_url = extract_og_image(entry.link)

        entry_data = {
            'title': bleach.clean(entry.title, strip=True),
            'summary': bleach.clean(entry.summary, tags=['p', 'br', 'strong', 'em', 'ul', 'ol', 'li', 'a'], attributes=['href'], strip=True),
            'link': entry.link,
            'image': image_url
        }
        print(f"adding {entry_data['title']}: {entry_data['image']}")
        r.set(f"rss:{entry.id}", json.dumps(entry_data))

if __name__ == "__main__":
    main()
