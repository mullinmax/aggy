import pytest
import uuid
import hashlib

from src.shared.db.category import Category


@pytest.fixture(scope="function")
def unique_category_data():
    """Generates unique category data for each test, assuming a Redis connection fixture."""
    unique_id = str(uuid.uuid4())
    user_hash = hashlib.sha256(f"user_{unique_id}".encode()).hexdigest()
    return {
        "user_hash": user_hash,
        "name": f"Category Name {unique_id}",
    }


def test_category_creation(unique_category_data):
    """Tests creation of a category."""
    category = Category(**unique_category_data)
    assert category.exists()
    category.delete()
    assert not category.exists()


def test_category_duplicate_creation(unique_category_data):
    """Tests that creating a duplicate category raises an exception."""
    category = Category(**unique_category_data)
    category.create()  # First creation should succeed

    with pytest.raises(Exception) as e:
        category.create()  # Attempt to create duplicate category
    assert "already exists" in str(e.value), "Should not allow duplicate categories"


def test_category_read(unique_category_data):
    """Tests reading a category back from the database."""
    category = Category(**unique_category_data)

    read_category = Category.read(unique_category_data["user_hash"], category.name_hash)
    assert read_category, "Category should be readable"
    assert (
        read_category.name == unique_category_data["name"]
    ), "Category name should match"


def test_category_read_all(unique_category_data):
    """Tests reading all categories for a user."""
    # Create multiple categories for testing
    for i in range(3):
        category_data = unique_category_data.copy()
        category_data["name"] += f" {i}"
        category = Category(**category_data)
        category.create()

    categories = Category.read_all(unique_category_data["user_hash"])
    assert len(categories) == 3, "Should read all categories for a user"
