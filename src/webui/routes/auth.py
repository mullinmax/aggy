from flask import Blueprint, request, redirect, url_for, render_template, session
from flask_login import login_user, logout_user, login_required, UserMixin, LoginManager
import redis
import bcrypt
import os
import logging

# Create a Blueprint for authentication
auth_bp = Blueprint('auth', __name__)

# Environment variables for Redis
REDIS_HOST = os.getenv('REDIS_HOST')
REDIS_PORT = os.getenv('REDIS_PORT')

# Initialize Redis connection
r = redis.Redis(host=REDIS_HOST, port=int(REDIS_PORT), decode_responses=True)

# Initialize LoginManager
login_manager = LoginManager()
login_manager.login_view = 'auth.login'

class User(UserMixin):
    def __init__(self, username):
        self.id = username

@login_manager.user_loader
def load_user(user_id):
    user_key = f'USER:{user_id}'
    if r.exists(user_key):  # Ensure `r` is your Redis connection
        return User(user_id)
    return None

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    # Check if user is already logged in
    if 'username' in session:
        return 'Logged in as %s <br> <a href="/logout">Logout</a>' % session['username']

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password'].encode('utf-8')
        user_key = f'USER:{username}'

        stored_password_hash = r.get(user_key)
        if stored_password_hash and bcrypt.checkpw(password, stored_password_hash.encode('utf-8')):
            user = User(username)
            login_user(user)  # Log in the user
            return redirect(url_for('home.home'))
        else:
            return 'Invalid username or password'
    return render_template('login.html')

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password'].encode('utf-8')
        user_key = f'USER:{username}'
        # Check if username already exists
        if r.get(user_key):
            return 'Username already exists'

        # Hash password
        hashed_password = bcrypt.hashpw(password, bcrypt.gensalt(rounds=13))

        # Store username and hashed password in Redis
        r.set(user_key, hashed_password.decode('utf-8'))
        r.bgsave()
        return redirect(url_for('auth.login'))

    return render_template('register.html')

@auth_bp.route('/logout')
def logout():
    logging.info('logging out user')
    logout_user()
    session.clear()
    return redirect(url_for('auth.login'))