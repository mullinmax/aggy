import pytest

from src.shared.db.user import User


@pytest.fixture(scope="function")
def unique_user(unique_category):
    user = User(
        username="example_user",
        is_superuser=False,
    )

    yield user

    if user.exists():
        user.delete()


@pytest.fixture(scope="function")
def unique_user_w_password(unique_category):
    user = User(
        username="example_user",
        is_superuser=False,
    )

    user.set_password("password")

    yield user

    if user.exists():
        user.delete()


@pytest.fixture(scope="function")
def unique_super_user(unique_category):
    user = User(
        username="example_user",
        is_superuser=True,
    )

    yield user

    if user.exists():
        user.delete()
