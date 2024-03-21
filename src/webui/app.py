from flask import Flask, redirect, url_for
from flask_wtf.csrf import CSRFProtect


from routes.auth import auth_bp, login_manager
from routes.home import home_bp
from routes.category import category_bp
from routes.feed import feed_bp
import logging

from shared.config import config

app = Flask(__name__)
app.secret_key = config.get("BLINDER_SECRET_KEY")
app.logger.setLevel(logging.INFO)
csrf = CSRFProtect(app)

# Initialize Flask-Login
login_manager.init_app(app)

# Register the authentication Blueprint
app.register_blueprint(auth_bp)
app.register_blueprint(home_bp)
app.register_blueprint(category_bp)
app.register_blueprint(feed_bp)


# @app.route("/reset-items")
# def reset_items():
#     try:
#         from shared.db import r

#         # delete all items
#         all_items = r.keys("ITEM:*")
#         for item in all_items:
#             r.delete(item)
#         app.logger.info(f"Deleted {len(all_items)} items")

#         # clear out all feeds
#         all_feed_items = r.keys("USER:*:FEED:*:ITEMS")
#         app.logger.info(f"found {len(all_feed_items)} feeds")
#         for feed_items in all_feed_items:
#             app.logger.info(f"resetting {feed_items}")
#             r.srem(*feed_items)
#         app.logger.info(f"Reset {len(all_feed_items)} feeds")

#         # clear out all categories
#         all_category_items = r.keys("USER:*:CATEGORY:*:ITEMS")
#         app.logger.info(f"found {len(all_category_items)} categories")
#         for category_items in all_category_items:
#             app.logger.info(f"resetting {category_items}")
#             r.zremrangebyrank(category_items, 0, -1)
#         app.logger.info(f"Reset {len(all_category_items)} categories")

#         # set all feeds to be parsed now
#         r.zunionstore(
#             config.get("FEEDS_TO_INGEST_KEY"),
#             keys={config.get("FEEDS_TO_INGEST_KEY"): 0},
#         )

#         # save db
#         r.bgsave()
#         return redirect(url_for("home.home"))
#     except Exception as e:
#         app.logger.error(e)
#         return redirect(url_for("home.home"))


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def catch_all(path):
    app.logger.error(f"rerouting unknown route to home: {path}")
    return redirect(url_for("home.home"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
