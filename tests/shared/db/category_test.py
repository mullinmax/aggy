import pytest

from src.shared.db.category import Category


def test_category_creation(unique_category):
    """Tests creation of a category."""
    unique_category.create()
    assert unique_category.exists()

    user_categories_key = f"USER:{unique_category.user_hash}:CATEGORIES"
    with unique_category.redis_con() as r:
        all_user_categories = r.smembers(user_categories_key)
    assert unique_category.name_hash in all_user_categories

    unique_category.delete()
    assert not unique_category.exists()


def test_category_duplicate_creation(unique_category):
    """Tests that creating a duplicate category raises an exception."""
    unique_category.create()

    with pytest.raises(Exception) as e:
        unique_category.create()  # Attempt to create duplicate category
    assert "already exists" in str(e.value), "Should not allow duplicate categories"


def test_category_read(unique_category):
    """Tests reading a category back from the database."""
    unique_category.create()
    read_category = Category.read(
        user_hash=unique_category.user_hash, name_hash=unique_category.name_hash
    )
    assert read_category, "Category should be readable"
    assert read_category.name == unique_category.name, "Category name should match"


def test_category_read_all(unique_category):
    """Tests reading all categories for a user."""
    # Create multiple categories for testing
    for i in range(3):
        unique_category.name += f" {i}"
        unique_category.create()

    categories = Category.read_all(unique_category.user_hash)
    assert len(categories) == 3, "Should read all categories for a user"

    for category in categories:
        assert (
            category.user_hash == unique_category.user_hash
        ), "Category should be for the correct user"


@pytest.mark.filterwarnings("ignore::UserWarning")
def test_get_all_items(unique_category, unique_item_strict):
    """Tests getting all items for a category."""
    unique_category.create()

    items = [unique_item_strict.model_copy() for i in range(3)]

    with unique_category.redis_con() as r:
        for i, item in enumerate(items):
            item.url = f"http://example.com/{i}"
            item.create()
            r.zadd(unique_category.items_key, {item.url_hash: i})

    act_items = unique_category.get_all_items()
    assert len(act_items) == 3, "Should get all items for a category"
    for item in act_items:
        assert item.url_hash in [
            i.url_hash for i in items
        ], "Should get the correct items"

    unique_category.delete()

    assert not unique_category.exists()
