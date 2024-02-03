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

@app.route('/add_feed', methods=['GET', 'POST'])
def add_feed():
    if request.method == 'POST':
        feed_name = request.form.get('feed_name')
        feed_url = request.form.get('feed_url')
        feed_category = request.form.get('feed_category')

        if feed_name and feed_url:
            # Construct the feed object
            feed_data = {
                'name': feed_name,
                'url': feed_url,
                'category': feed_category
            }

            # Save to Redis
            r.set(f"feed:{feed_name}", json.dumps(feed_data))

            return redirect(url_for('index'))

    return render_template('add_feed.html')

@app.route('/')
def index():
    # Retrieve keys for all feed items
    keys = r.keys('rss:*')
    
    # Fetch all feed items and sanitize
    feed_items = []
    for key in keys:
        item = json.loads(r.get(key))

        # Sanitize each string field
        for field, value in item.items():
            if isinstance(value, str):
                item[field] = bleach.clean(value, strip=True)

        feed_items.append(item)

    return render_template('index.html', feed_items=feed_items)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
