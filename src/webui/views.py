from flask import Blueprint, render_template, request, redirect, url_for, jsonify
from .models import Feed
from .util import trigger_feed_processing

main = Blueprint('main', __name__)

@main.route('/add_feed', methods=['GET', 'POST'])
def add_feed():
    if request.method == 'POST':
        feed_name = request.form.get('feed_name')
        feed_url = request.form.get('feed_url')
        feed_category = request.form.get('feed_category')
        feed_key = Feed.add_feed(feed_name, feed_url, feed_category)
        if trigger_feed_processing(feed_key):
            # Logging success
            pass
        else:
            # Logging failure
            pass
        return redirect(url_for('main.index'))

@main.route('/edit_feed/<feed_name>', methods=['POST'])
def edit_feed(feed_name):
    # Implement feed editing logic
    pass

@main.route('/delete_feed/<feed_name>', methods=['POST'])
def delete_feed(feed_name):
    Feed.delete_feed(feed_name)
    return jsonify({'status': 'success', 'message': f'Feed {feed_name} deleted successfully'})

# More routes...
