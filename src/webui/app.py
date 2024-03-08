from flask import Flask, redirect, url_for
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect


from routes.auth import auth_bp, login_manager
from routes.home import home_bp
from routes.category import category_bp
from routes.feed import feed_bp
import logging 

import config

app = Flask(__name__)
app.secret_key = config.BLINDER_SECRET_KEY
app.logger.setLevel(logging.INFO)
csrf = CSRFProtect(app)

# Initialize Flask-Login
login_manager.init_app(app)

# Register the authentication Blueprint
app.register_blueprint(auth_bp)
app.register_blueprint(home_bp)
app.register_blueprint(category_bp)
app.register_blueprint(feed_bp)

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def catch_all(path):
    app.logger.error(f'rerouting unknown route to home: {path}')
    return redirect(url_for('home.home'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
