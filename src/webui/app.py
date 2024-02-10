from flask import Flask
import os
from routes.auth import auth_bp
from routes.home import home_bp

# Environment variables for Redis
REDIS_HOST = os.getenv('REDIS_HOST')
REDIS_PORT = os.getenv('REDIS_PORT')
BLINDER_SECRET_KEY = os.getenv('BLINDER_SECRET_KEY')
# INGEST_HOST = os.getenv('INGEST_HOST')
# INGEST_PORT = os.getenv('INGEST_PORT')

app = Flask(__name__)
app.secret_key = os.getenv('BLINDER_SECRET_KEY')

# Register the authentication Blueprint
app.register_blueprint(auth_bp)
app.register_blueprint(home_bp)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
