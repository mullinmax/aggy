from flask import Flask, redirect, url_for
from flask_wtf.csrf import CSRFProtect


from routes.auth import auth_bp, login_manager
from routes.home import home_bp
from routes.category import category_bp
from routes.feed import feed_bp
import logging

from shared.config import config
from shared.db.base import db_init

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


@app.errorhandler(404)
def page_not_found(e):
    app.logger.error("rerouting unknown route to home")
    return redirect(url_for("home.home"))


@app.errorhandler(500)
def internal_error(error):
    app.logger.error(f"Internal server error: {error}")
    return redirect(url_for("home.home")), 500


if __name__ == "__main__":
    db_init(flush=False)
    from waitress import serve

    serve(app, host="0.0.0.0", port=5000)
