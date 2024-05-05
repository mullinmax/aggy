import pytest
import uuid

from db.category import Category


@pytest.fixture(scope="function")
def unique_category():
    """Generates unique category data for each test, assuming a Redis connection fixture."""
    category = Category(
        user_hash=uuid.uuid4().hex,
        name=f"Category Name {uuid.uuid4()}",
    )

    yield category

    if category.exists():
        category.delete()
