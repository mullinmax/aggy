import feedparser

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

def parse_feed(feed_key):
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    # get url from feed
    url = r.hget(feed_key, 'url')
    if not url:
        logging.error(f'unable to find url for feed_key {feed_key}')

    feed = feedparser.parse(feed_url)
    for entry in feed.entries:
        hashed_url = hashlib.sha256(entry.url.encode()).hexdigest()
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
        r.sadd(f"{feed_key}:ITEMS", item_key)
        logging.info(f"Added {item_key} to {feed_key}")
