from flask import Blueprint, render_template, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from shared.db.category import Category

home_bp = Blueprint("home", __name__, template_folder="templates")


@home_bp.route("/home")
@login_required
def home():
    user_hash = current_user.name_hash
    current_app.logger.info(f"User hash: {user_hash}")
    current_app.logger.info(f"current_user: {current_user}")
    if not user_hash:
        flash("User identification failed.")
        return redirect(url_for("auth.login"))

    categories = Category.read_all(user_hash=user_hash)
    return render_template("home.html", categories=categories)
