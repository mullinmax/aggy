from flask import Flask, request, jsonify, Blueprint, current_app
from flask_login import login_required, current_user
from shared.db import Feed
import json

# Define the blueprint
feed_bp = Blueprint('feed', __name__, url_prefix='/feed')

@feed_bp.route('/add', methods=['POST'])
@login_required
def add_feed():
    try:
        user_hash = current_user.id
        feed_name = request.form.get('feedName')
        feed_url = request.form.get('feedUrl')
        category_hashes = request.form.getlist('categories')
        
        current_app.logger.info(category_hashes)
        
        # Create and save the new feed
        feed = Feed(
            user_hash=user_hash,
            name=feed_name,
            url=feed_url,
            category_hashes=set(category_hashes)
        )
        feed_uuid = feed.create()

        return jsonify({'message': 'Feed added successfully', 'feed_uuid': feed_uuid}), 201

    except Exception as e:
        current_app.logger.info(str(e))
        return jsonify({'error': str(e)}), 400

