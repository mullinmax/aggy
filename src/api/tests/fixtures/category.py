import pytest
import uuid

from db.category import Category
from db.user import User


@pytest.fixture(scope="function")
def unique_category(unique_user: User) -> Category:
    """Generates unique category data for each test, assuming a Redis connection fixture."""
    category = Category(
        user_hash=unique_user.name_hash,
        name=f"Category Name {uuid.uuid4()}",
    )

    yield category

    if category.exists():
        category.delete()


@pytest.fixture(scope="function")
def existing_category(unique_category: Category) -> Category:
    """Generates existing category data for each test, assuming a Redis connection fixture."""
    unique_category.create()
    yield unique_category
