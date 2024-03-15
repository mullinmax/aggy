from flask import Blueprint, request, jsonify, current_app, render_template
from flask_login import login_required, current_user
from shared.db import Category, Feed

# Define the blueprint
category_bp = Blueprint("category", __name__, url_prefix="/category")


@category_bp.route("/create", methods=["POST"])
@login_required
def create_category():
    # Assuming the username_hash is stored in the session upon login
    user_hash = current_user.id
    category_name = request.form.get("name")
    if not category_name:
        return jsonify({"error": "Category name is required"}), 400

    # Create and save the new category
    try:
        category = Category(user_hash=user_hash, name=category_name)
        category_key = category.create()
        return jsonify(
            {"message": "Category created successfully", "category_key": category_key}
        ), 201
    except Exception as e:
        current_app.logger.info(str(e))
        return jsonify({"error": str(e)}), 400


@category_bp.route("/list", methods=["GET"])
@login_required
def list_categories():
    user_hash = current_user.id
    categories = Category.read_all(user_hash=user_hash)
    return jsonify(categories), 200


@category_bp.route("/<name_hash>", methods=["GET"])
@login_required
def view_category(name_hash):
    # try:
    user_hash = current_user.id
    current_app.logger.info(f"Requested URL: {request.url}")
    current_app.logger.info(f"{user_hash=} {name_hash=}")
    category = Category.read(user_hash, name_hash)
    feeds = Feed.read_all(user_hash)
    items = category.get_all_items()
    return render_template(
        "view_category.html", category=category, feeds=feeds, items=items
    )
    # except Exception as e:
    #     logging.error(e)
    #     return redirect(url_for('home.home'))
