from flask import request, jsonify, Blueprint, current_app
from flask_login import login_required, current_user
from shared.db.feed import Feed
from shared.db.category import Category

# Define the blueprint
feed_bp = Blueprint("feed", __name__, url_prefix="/feed")


@feed_bp.route("/add", methods=["POST"])
@login_required
def add_feed():
    try:
        feed_name = request.form.get("feedName")
        feed_url = request.form.get("feedUrl")
        category_hash = request.form.get("categoryHash")

        current_app.logger.info(f"{feed_name=} {feed_url=} {category_hash=}")

        # Create and save the new feed
        feed = Feed(
            user_hash=current_user.name_hash,
            name=feed_name,
            url=feed_url,
            category_hash=category_hash,
        )

        category = Category.read(
            user_hash=current_user.name_hash, name_hash=category_hash
        )

        category.add_feed(feed)

        return jsonify({"message": "Feed added successfully"}), 201

    except Exception as e:
        current_app.logger.info(str(e))
        return jsonify({"error": str(e)}), 400
