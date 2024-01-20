from flask import Flask, render_template
import redis
import json
import bleach

app = Flask(__name__)

# Environment variables for Redis
REDIS_HOST = 'blinder-db'
REDIS_PORT = 6379

# Connect to Redis
r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

@app.route('/')
def index():
    # Retrieve keys for all feed items
    keys = r.keys('rss:*')
    
    # Fetch all feed items and sanitize
    feed_items = []
    for key in keys:
        item = json.loads(r.get(key))
        item['title'] = bleach.clean(item['title'], strip=True)
        item['summary'] = bleach.clean(item['summary'], tags=['p', 'br', 'strong', 'em', 'ul', 'ol', 'li', 'a'], attributes=['href'], strip=True)
        feed_items.append(item)

    return render_template('index.html', feed_items=feed_items)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
