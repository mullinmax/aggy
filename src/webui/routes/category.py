from flask import Blueprint, request, session, jsonify, flash, redirect, url_for, current_app
from flask_login import login_required, current_user
from db import Category  # Import your Category class here

# Define the blueprint
category_bp = Blueprint('category', __name__, url_prefix='/category')


@category_bp.route('/create', methods=['POST'])
@login_required
def create_category():
    current_app.logger.info('HELLO')
    # Assuming the username_hash is stored in the session upon login
    user_hash = current_user.id
    current_app.logger.info(user_hash)
    if not user_hash:
        flash('User identification failed.')
        return redirect(url_for('auth.login'))

    category_name = request.form.get('name')
    if not category_name:
        return jsonify({'error': 'Category name is required'}), 400

    # Create and save the new category
    try:
        category = Category(user_hash=user_hash, name=category_name)
        category_uuid = category.create()
        return jsonify({'message': 'Category created successfully', 'category_uuid': category_uuid}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@category_bp.route('/list', methods=['GET'])
@login_required
def list_categories():
    user_hash = session.get('user_hash')
    if not user_hash:
        flash('User identification failed.')
        return redirect(url_for('auth.login'))

    categories = Category.read_all(user=user_hash)
    return jsonify(categories), 200
