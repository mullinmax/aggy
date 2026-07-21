import pytest
import uuid

from db.list import UserList
from db.user import User


@pytest.fixture(scope="function")
def unique_list(existing_user: User) -> UserList:
    """A list whose owning user exists, so the FK to users is satisfied if
    the list is later persisted."""
    lst = UserList(
        user_hash=existing_user.name_hash,
        name=f"List Name {uuid.uuid4()}",
    )
    yield lst


@pytest.fixture(scope="function")
def existing_list(unique_list: UserList) -> UserList:
    if not unique_list.exists():
        unique_list.create()
    yield unique_list
