from flask import Blueprint, render_template, redirect, url_for
from flask_login import login_required
from ..forms import CategoryForm, FeedForm  # Adjust the import path as necessary

home_bp = Blueprint('home', __name__, template_folder='templates')

@home_bp.route('/home')
@login_required  # Require the user to be authenticated
def home():
    categories = {}  # Your logic to fetch categories
    if not categories:
        # Render a special template if no categories exist
        return render_template('no_categories.html', category_form=CategoryForm(), feed_form=FeedForm())
    # Regular rendering for the home page
    return render_template('home.html', categories=categories)
