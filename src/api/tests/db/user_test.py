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


def test_read_user(unique_user):
    assert not unique_user.exists()
    unique_user.set_password("password")
    unique_user.create()
    assert unique_user.exists()
    user = User.read(name=unique_user.name)
    assert user.name == unique_user.name
    assert user.check_password("password")
    assert not user.check_password("wrong_password")


def test_read_user_by_name(unique_user):
    assert not unique_user.exists()
    unique_user.set_password("password")
    unique_user.create()
    assert unique_user.exists()
    user = User.read(name=unique_user.name)
    assert user is not None
    assert user.check_password("password")


def test_read_all():
    assert User.read_all() == []


def test_read_all_with_users(unique_user):
    assert not unique_user.exists()
    unique_user.set_password("password")
    unique_user.create()
    assert unique_user.exists()
    users = User.read_all()
    assert len(users) == 1
    assert users[0].name == unique_user.name
    assert users[0].check_password("password")


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


def test_create_user_twice(unique_user):
    assert not unique_user.exists()
    unique_user.set_password("password")
    unique_user.create()
    assert unique_user.exists()
    with pytest.raises(Exception) as e:
        unique_user.create()
    assert str(e.value) == f"User with name {unique_user.name} already exists"
    assert unique_user.exists()


def test_delete_user(unique_user):
    assert not unique_user.exists()
    unique_user.set_password("password")
    unique_user.create()
    assert unique_user.exists()
    unique_user.delete()
    assert not unique_user.exists()
    assert unique_user.categories == []


def test_delete_user_with_categories(unique_user, unique_category):
    assert not unique_user.exists()
    unique_user.set_password("password")
    unique_user.create()
    assert unique_user.exists()
    unique_category.user_hash = unique_user.name_hash
    unique_category.create()
    unique_user.add_category(unique_category)
    assert unique_category.exists()
    assert unique_user.categories == [unique_category]
    unique_user.delete()
    assert not unique_user.exists()
    assert unique_user.categories == []
    assert not unique_category.exists()


def test_remove_category_from_user(unique_user, unique_category):
    assert not unique_user.exists()
    unique_user.set_password("password")
    unique_user.create()
    assert unique_user.exists()
    unique_category.user_hash = unique_user.name_hash
    unique_category.create()
    unique_user.add_category(unique_category)
    assert unique_user.categories == [unique_category]
    unique_user.remove_category(unique_category)
    assert unique_user.categories == []
    assert not unique_category.exists()


def test_update_user(unique_user):
    assert not unique_user.exists()
    unique_user.set_password("password")
    unique_user.create()
    assert unique_user.exists()
    unique_user.set_password("new_password")
    unique_user.update()
    user = User.read(name=unique_user.name)
    assert user.name == unique_user.name
    assert user.check_password("new_password")
    assert not user.check_password("password")


def test_read_user_does_not_exist():
    expected_name_hash = User(name="example_user").name_hash
    with pytest.raises(Exception) as e:
        User.read(name="example_user")
    assert str(e.value) == f"User with name_hash {expected_name_hash} does not exist"


def test_created_time(unique_user):
    assert not unique_user.exists()
    unique_user.set_password("password")
    unique_user.create()
    assert unique_user.exists()
    assert unique_user.created is not None
    assert unique_user.updated is not None
    assert unique_user.created == unique_user.updated
    unique_user.set_password("new_password")
    unique_user.update()
    assert unique_user.created < unique_user.updated
    created = unique_user.created
    unique_user.delete()
    assert unique_user.created == created
    assert unique_user.updated > unique_user.created


def test_two_users_password_check(unique_user):
    assert not unique_user.exists()
    unique_user.set_password("password")
    unique_user.create()
    assert unique_user.exists()

    # make a new user
    unique_user2 = User(
        name="example_user2",
    )
    unique_user2.set_password("password2")
    unique_user2.create()
    assert unique_user2.exists()

    # make sure passwords don't work for eachother
    assert unique_user.check_password("password")
    assert not unique_user.check_password("password2")
    assert not unique_user2.check_password("password")
    assert unique_user2.check_password("password2")


def test_user_add_category(unique_user, unique_category):
    assert not unique_user.exists()
    unique_user.set_password("password")
    unique_user.create()
    assert unique_user.exists()
    unique_category.user_hash = unique_user.name_hash
    unique_user.add_category(unique_category)
    assert unique_user.categories == [unique_category]
