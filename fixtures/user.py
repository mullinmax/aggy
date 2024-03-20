import pytest
import uuid

from src.shared.db.user import User


@pytest.fixture(scope="function")
def unique_user(unique_category):
    user = User(
        name="example_user" + str(uuid.uuid4()),
    )

    yield user

    if user.exists():
        user.delete()
