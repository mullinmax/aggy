from flask import Blueprint, request, redirect, url_for, render_template, session
import redis
import bcrypt
import os

# Create a Blueprint for authentication
auth_bp = Blueprint('auth', __name__)

# Environment variables for Redis
REDIS_HOST = os.getenv('REDIS_HOST')
REDIS_PORT = os.getenv('REDIS_PORT')

# Initialize Redis connection
r = redis.Redis(host=REDIS_HOST, port=int(REDIS_PORT), decode_responses=True)


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
            session['username'] = username
            return redirect(url_for('auth.login'))
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
        hashed_password = bcrypt.hashpw(password, bcrypt.gensalt(rounds=14))

        # Store username and hashed password in Redis
        r.set(user_key, hashed_password.decode('utf-8'))
        r.bgsave()
        return 'Registration successful! <a href="/login">Login now</a>'

    return render_template('register.html')

@auth_bp.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('auth.login'))