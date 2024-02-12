from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_required, current_user
from routes.feed_form import FeedForm
from routes.category_form import CategoryForm
from db import r

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
        categories_key = f"USER:{current_user.id}:CATEGORIES"
        category_key = f"USER:{current_user.id}:CATEGORY:{category_name}"
        r.zadd(categories_key, {category_key:0}, nx=True) # Add to categories if not already in there
        r.bgsave()
        flash('Category added successfully.', 'success')
        return redirect(url_for('home.home'))  # Adjust the redirect as needed
    return render_template('category_form.html', form=form)

# @home_bp.route('/add_feed', methods=['GET', 'POST'])
# @login_required
# def add_feed():
#     form = FeedForm()
#     # Dynamically populate the categories choices
#     form.categories.choices = [(category, category) for category in get_all_categories()]
#     if form.validate_on_submit():
#         feed_name = form.name.data
#         feed_url = form.url.data
#         selected_categories = form.categories.data
#         category_key = "USER:{current_user.id}:CATEGORY:{}"
#         feed_key = f"USER:{current_user.id}:FEED:{feed_name}"

#         r.hmset(feed_key, {'url': feed_url, 'categories': ','.join(selected_categories)})
#         flash('Feed added successfully.', 'success')
#         return redirect(url_for('home.home'))  # Adjust the redirect as needed
#     return render_template('feed_form.html', feed_form=form)


@home_bp.route('/add_feed', methods=['GET', 'POST'])
@login_required
def add_feed():
    form = FeedForm()
    if form.validate_on_submit():
        feed_name = form.name.data
        feed_url = form.url.data
        category_name = form.category.data.strip()

        # Check if the category already exists; if not, create a new one
        category_key = f"USER:{current_user.id}:CATEGORY:{category_name}"
        if not r.exists(category_key):
            r.set(category_key, category_name)  # Create the new category

        feed_key = f"USER:{current_user.id}:FEED:{feed_name}"
        r.hmset(feed_key, {'url': feed_url, 'category': category_name})
        flash('Feed added successfully.', 'success')
        return redirect(url_for('home.home'))

    return render_template('feed_form.html', feed_form=form, categories=get_all_categories())


def get_all_categories():
    # This function needs to retrieve all categories from Redis
    # Here's a simple placeholder implementation
    category_keys = r.keys('CATEGORY:*')
    categories = [r.get(key) for key in category_keys]
    return categories
