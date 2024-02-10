from flask import Blueprint, render_template, redirect, url_for
from flask_login import login_required
from routes.feed_form import FeedForm
from routes.category_form import CategoryForm

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


@home_bp.route('/add_category', methods=['GET', 'POST'])
@login_required
def add_category():
    form = CategoryForm()
    if form.validate_on_submit():
        category_name = form.name.data
        # Create a unique key for the category in Redis
        category_key = f"CATEGORY:{category_name}"
        if r.exists(category_key):
            flash('Category already exists.', 'error')
        else:
            # Save the new category
            r.set(category_key, category_name)
            flash('Category added successfully.', 'success')
            return redirect(url_for('auth.dashboard'))  # Adjust the redirect as needed
    return render_template('category_form.html', form=form)

@home_bp.route('/add_feed', methods=['GET', 'POST'])
@login_required
def add_feed():
    form = FeedForm()
    # Dynamically populate the categories choices
    form.categories.choices = [(category, category) for category in get_all_categories()]
    if form.validate_on_submit():
        feed_name = form.name.data
        feed_url = form.url.data
        selected_categories = form.categories.data
        feed_key = f"FEED:{feed_name}"
        if r.exists(feed_key):
            flash('Feed already exists.', 'error')
        else:
            # Save the new feed with its categories and URL
            r.hmset(feed_key, {'url': feed_url, 'categories': ','.join(selected_categories)})
            flash('Feed added successfully.', 'success')
            return redirect(url_for('auth.dashboard'))  # Adjust the redirect as needed
    return render_template('feed_form.html', form=form)

def get_all_categories():
    # This function needs to retrieve all categories from Redis
    # Here's a simple placeholder implementation
    category_keys = r.keys('CATEGORY:*')
    categories = [r.get(key) for key in category_keys]
    return categories
