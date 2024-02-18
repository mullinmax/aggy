from flask import Flask, redirect, url_for
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect

import os
from routes.auth import auth_bp, login_manager
from routes.home import home_bp
from routes.category import category_bp
import logging 
# Environment variables for Redis
REDIS_HOST = os.getenv('REDIS_HOST')
REDIS_PORT = os.getenv('REDIS_PORT')
BLINDER_SECRET_KEY = os.getenv('BLINDER_SECRET_KEY')
# INGEST_HOST = os.getenv('INGEST_HOST')
# INGEST_PORT = os.getenv('INGEST_PORT')

app = Flask(__name__)
app.secret_key = os.getenv('BLINDER_SECRET_KEY')
app.logger.setLevel(logging.INFO)
csrf = CSRFProtect(app)
# Initialize Flask-Login
login_manager.init_app(app)

# Register the authentication Blueprint
app.register_blueprint(auth_bp)
app.register_blueprint(home_bp)
app.register_blueprint(category_bp)

# @app.route('/', defaults={'path': ''})
# @app.route('/<path:path>')
# def catch_all(path):
#     return redirect(url_for('home.home'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
