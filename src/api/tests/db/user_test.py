import pytest

from db.user import User


def test_create_user(unique_user):
    with unique_user.db_con() as r:
        assert not unique_user.exists()
        assert len(r.smembers("USERS")) == 0
        unique_user.set_password("password")
        unique_user.create()
        assert unique_user.exists()
        assert len(r.smembers("USERS")) == 1
        assert r.smembers("USERS") == {unique_user.name_hash}


def test_read_user(existing_user):
    assert existing_user.exists()
    user = User.read(name=existing_user.name)
    assert user == existing_user
    assert user.check_password("password")
    assert not user.check_password("wrong_password")


def test_read_user_by_name(existing_user):
    assert existing_user.exists()
    user = User.read(name=existing_user.name)
    assert user is not None
    assert user.check_password("password")


def test_read_all_no_users():
    assert User.read_all() == []


def test_read_all_with_users(existing_user):
    users = User.read_all()
    assert len(users) == 1
    assert users[0] == existing_user


def test_read_user_no_name_or_hash():
    with pytest.raises(Exception) as e:
        User.read()
    assert str(e.value) == "name or name_hash is required"


def test_create_user_no_password(unique_user):
    assert not unique_user.exists()
    unique_user.hashed_password = None
    with pytest.raises(Exception) as e:
        unique_user.create()
    assert str(e.value) == "Password is required to create a user"
    assert not unique_user.exists()


def test_create_user_twice(existing_user):
    assert existing_user.exists()
    with pytest.raises(Exception) as e:
        existing_user.create()
    assert str(e.value) == f"User with name {existing_user.name} already exists"
    assert existing_user.exists()


def test_delete_user(existing_user):
    assert existing_user.exists()
    existing_user.delete()
    assert not existing_user.exists()
    assert existing_user.categories == []


def test_delete_user_with_categories(existing_user, existing_category):
    assert existing_category.exists()
    assert existing_user.categories == [existing_category]
    existing_user.delete()
    assert not existing_user.exists()
    assert existing_user.categories == []
    assert not existing_category.exists()


def test_remove_category_from_user(existing_user, existing_category):
    assert existing_user.categories == [existing_category]
    existing_user.remove_category(existing_category)
    assert existing_user.categories == []
    assert not existing_category.exists()


def test_update_user(existing_user):
    assert not existing_user.check_password("new_password")
    assert existing_user.check_password("password")

    existing_user.set_password("new_password")
    existing_user.update()
    user = User.read(name=existing_user.name)

    assert user.name == existing_user.name
    assert user.check_password("new_password")
    assert not user.check_password("password")


def test_read_user_does_not_exist():
    expected_name_hash = User(name="example_user").name_hash
    with pytest.raises(Exception) as e:
        User.read(name="example_user")
    assert str(e.value) == f"User with name_hash {expected_name_hash} does not exist"


def test_two_users_password_check(existing_user):
    # make a new user
    unique_user = User(
        name="example_user2",
    )
    unique_user.set_password("password2")
    unique_user.create()
    assert unique_user.exists()

    # make sure passwords don't work for eachother
    assert existing_user.check_password("password")
    assert not existing_user.check_password("password2")
    assert not unique_user.check_password("password")
    assert unique_user.check_password("password2")


def test_user_add_category(existing_user, unique_category):
    unique_category.user_hash = existing_user.name_hash
    existing_user.add_category(unique_category)
    assert existing_user.categories == [unique_category]
    assert unique_category.exists()
