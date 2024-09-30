import pytest
import uuid

from db.source import Source
from db.category import Category
from db.user import User


@pytest.fixture(scope="function")
def unique_source(unique_category: Category, unique_user: User) -> Source:
    """Generates unique source data for each test"""
    source = Source(
        user_hash=unique_user.name_hash,
        category_hash=unique_category.name_hash,
        name=f"Source Name {uuid.uuid4()}",
        url="http://example.com",
    )

    yield source

    if source.exists():
        source.delete()


@pytest.fixture(scope="function")
def existing_source(unique_source: Source, existing_category: Category) -> Source:
    """Generates existing source data for each test"""
    existing_category.add_source(unique_source)
    yield unique_source
