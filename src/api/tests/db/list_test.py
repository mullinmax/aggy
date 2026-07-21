import pytest

from db.list import UserList


def test_create_list(existing_list):
    assert existing_list.exists(), "List should exist after creation"


def test_create_duplicate_list_raises(existing_list):
    dup = UserList(user_hash=existing_list.user_hash, name=existing_list.name)
    with pytest.raises(ValueError):
        dup.create()


def test_create_list_bad_user():
    lst = UserList(user_hash="nope", name="My List")
    with pytest.raises(Exception):
        lst.create()


def test_delete_list(existing_list):
    existing_list.delete()
    assert not existing_list.exists(), "List should not exist after deletion"


def test_read_list(existing_list):
    read = UserList.read(existing_list.user_hash, existing_list.name_hash)
    assert read is not None
    assert read.name == existing_list.name
    assert read.name_hash == existing_list.name_hash


def test_read_missing_list(existing_user):
    assert UserList.read(existing_user.name_hash, "missing") is None


def test_read_all_lists(existing_user):
    a = UserList(user_hash=existing_user.name_hash, name="Alpha")
    b = UserList(user_hash=existing_user.name_hash, name="Beta")
    a.create()
    b.create()
    lists = UserList.read_all(existing_user.name_hash)
    names = {lst.name for lst in lists}
    assert {"Alpha", "Beta"} <= names


def test_add_and_remove_item(existing_list, existing_item_strict):
    item_hash = existing_item_strict.url_hash
    assert not existing_list.contains(item_hash)
    assert existing_list.item_count() == 0

    existing_list.add_item(item_hash)
    assert existing_list.contains(item_hash)
    assert existing_list.item_count() == 1

    # adding again is idempotent
    existing_list.add_item(item_hash)
    assert existing_list.item_count() == 1

    existing_list.remove_item(item_hash)
    assert not existing_list.contains(item_hash)
    assert existing_list.item_count() == 0


def test_items_returns_added_items(existing_list, existing_item_strict):
    existing_list.add_item(existing_item_strict.url_hash)
    items = existing_list.items()
    assert len(items) == 1
    assert items[0].url_hash == existing_item_strict.url_hash


def test_set_item_membership(existing_user, existing_item_strict):
    a = UserList(user_hash=existing_user.name_hash, name="Alpha")
    b = UserList(user_hash=existing_user.name_hash, name="Beta")
    c = UserList(user_hash=existing_user.name_hash, name="Gamma")
    a.create()
    b.create()
    c.create()
    item_hash = existing_item_strict.url_hash

    UserList.set_item_membership(
        existing_user.name_hash, item_hash, [a.name_hash, b.name_hash]
    )
    assert a.contains(item_hash)
    assert b.contains(item_hash)
    assert not c.contains(item_hash)

    # re-submitting a different selection replaces membership
    UserList.set_item_membership(
        existing_user.name_hash, item_hash, [c.name_hash]
    )
    assert not a.contains(item_hash)
    assert not b.contains(item_hash)
    assert c.contains(item_hash)

    # an empty selection clears membership
    UserList.set_item_membership(existing_user.name_hash, item_hash, [])
    assert not c.contains(item_hash)


def test_set_item_membership_ignores_foreign_hashes(
    existing_user, existing_item_strict
):
    a = UserList(user_hash=existing_user.name_hash, name="Alpha")
    a.create()
    item_hash = existing_item_strict.url_hash

    # "bogus" is not one of the user's lists and must be ignored, not inserted
    UserList.set_item_membership(
        existing_user.name_hash, item_hash, [a.name_hash, "bogus"]
    )
    assert a.contains(item_hash)
    assert a.item_count() == 1


def test_delete_list_cascades_membership(existing_list, existing_item_strict):
    existing_list.add_item(existing_item_strict.url_hash)
    existing_list.delete()
    # a fresh list of the same name starts empty (membership was removed)
    remade = UserList(user_hash=existing_list.user_hash, name=existing_list.name)
    remade.create()
    assert remade.item_count() == 0
