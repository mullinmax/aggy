import pytest
import uuid

from db.user import User


@pytest.fixture(scope="function")
def unique_user() -> User:
    user = User(
        name="example_user" + str(uuid.uuid4()),
    )

    user.set_password("password")

    yield user


@pytest.fixture(scope="function")
def existing_user(unique_user) -> User:
    if not unique_user.exists():
        unique_user.create()
    yield unique_user
