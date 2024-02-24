from flask import Flask, Blueprint, request, redirect, url_for, render_template, flash, session, jsonify, current_app
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required
import redis
import bcrypt
import os
import hashlib
from db import r

# Create a Blueprint for authentication
auth_bp = Blueprint('auth', __name__)

# Initialize LoginManager
login_manager = LoginManager()
login_manager.login_view = 'auth.login'

def hash_username(username: str) -> str:
    """Hashes the username for storage and retrieval."""
    return hashlib.sha256(username.encode()).hexdigest()

class User(UserMixin):
    """User class for Flask-Login."""
    def __init__(self, username_hash, username):
        self.id = username_hash  # Use the hashed username as the user ID
        self.username = username  # Also store the plain username for convenience

@login_manager.user_loader
def load_user(username_hash):
    """Flask-Login hook to load a user from the session."""
    user_data = r.hgetall(f'USER:{username_hash}')
    if user_data:
        return User(username_hash, user_data['username'])
    return None

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Login route for authenticating users."""
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        if not username or not password:
            return jsonify({'error': 'Username and password are required'}), 400

        user_hash = hash_username(username)
        current_app.logger.info(user_hash)
        user_key = f'USER:{user_hash}'

        user_data = r.hgetall(user_key)
        stored_password_hash = user_data.get('password')
        if stored_password_hash and bcrypt.checkpw(password.encode('utf-8'), stored_password_hash.encode('utf-8')):
            user = User(user_hash, username)
            login_user(user)
            return jsonify({'message': 'Logged in successfully.'}), 200
        else:
            return jsonify({'error': 'Invalid username or password'}), 401

    return render_template('login.html')


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    """Route for registering new users."""
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        # Check if username and password are provided
        if not username or not password:
            return jsonify({'error': 'Username and password are required'}), 400

        hashed_username = hash_username(username)
        user_key = f'USER:{hashed_username}'

        if r.exists(user_key):
            return jsonify({'error': 'Username already exists'}), 409

        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        r.hset(user_key, mapping={'username': username, 'password': hashed_password})
        r.sadd('USERS', user_key)
        r.bgsave()
        return jsonify({'message': 'Registration successful! Please log in.'}), 201

    # For GET request, render the registration form
    return render_template('register.html')


@auth_bp.route('/logout')
def logout():
    """Route for logging out users."""
    logout_user()
    flash('You have been logged out.')
    return redirect(url_for('auth.login'))