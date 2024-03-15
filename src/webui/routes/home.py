from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_required, current_user
from shared.db import r, Category

home_bp = Blueprint("home", __name__, template_folder="templates")


@home_bp.route("/home")
@login_required
def home():
    user_hash = current_user.id
    if not user_hash:
        flash("User identification failed.")
        return redirect(url_for("auth.login"))

    categories = Category.read_all(user_hash=user_hash)
    return render_template("home.html", categories=categories)


def get_all_categories():
    # This function needs to retrieve all categories from Redis
    # Here's a simple placeholder implementation
    category_keys = r.keys("CATEGORY:*")
    categories = [r.get(key) for key in category_keys]
    return categories
