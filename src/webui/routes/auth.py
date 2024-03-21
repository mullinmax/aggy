from flask import (
    Blueprint,
    request,
    redirect,
    url_for,
    render_template,
    flash,
    jsonify,
)
from flask_login import LoginManager, login_user, logout_user

from shared.db.user import FlaskUser

# Create a Blueprint for authentication
auth_bp = Blueprint("auth", __name__)

# Initialize LoginManager
login_manager = LoginManager()
login_manager.login_view = "auth.login"


@login_manager.user_loader
def load_user(name):
    try:
        return FlaskUser.read(name)
    except Exception:
        return None


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """Login route for authenticating users."""
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        if not username or not password:
            return jsonify({"error": "Username and password are required"}), 400

        try:
            user = FlaskUser.read(username)
        except Exception:
            return jsonify({"error": "User does not exist"}), 404

        if user.check_password(password):
            login_user(user)
            return jsonify({"message": "Logged in successfully."}), 200
        else:
            return jsonify({"error": "Invalid username or password"}), 401

    return render_template("login.html")


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    """Route for registering new users."""
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        # Check if username and password are provided
        if not username or not password:
            return jsonify({"error": "Username and password are required"}), 400

        user = FlaskUser(name=username)
        if user.exists():
            return jsonify({"error": "User already exists"}), 400

        user.set_password(password)
        user.create()
        return jsonify({"message": "Registration successful! Please log in."}), 201

    # For GET request, render the registration form
    return render_template("register.html")


@auth_bp.route("/logout")
def logout():
    """Route for logging out users."""
    logout_user()
    flash("You have been logged out.")
    return redirect(url_for("auth.login"))
