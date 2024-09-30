import pytest

from db.category import Category


def test_key(unique_category):
    """Tests the key property."""
    assert (
        unique_category.key
        == f"USER:{unique_category.user_hash}:CATEGORY:{unique_category.name_hash}"
    )


def test_items_key(unique_category):
    """Tests the items_key property."""
    assert (
        unique_category.items_key
        == f"USER:{unique_category.user_hash}:CATEGORY:{unique_category.name_hash}:ITEMS"
    )


def test_sources_key(unique_category):
    """Tests the sources_key property."""
    assert (
        unique_category.sources_key
        == f"USER:{unique_category.user_hash}:CATEGORY:{unique_category.name_hash}:SOURCES"
    )


def test_category_creation(existing_user, existing_category):
    """Tests creation of a category."""
    assert existing_category.exists()

    assert existing_category in existing_user.categories

    existing_category.delete()
    assert not existing_category.exists()


def test_category_duplicate_creation(unique_category):
    """Tests that creating a duplicate category raises an exception."""
    unique_category.create()

    with pytest.raises(Exception) as e:
        unique_category.create()  # Attempt to create duplicate category
    assert "already exists" in str(e.value), "Should not allow duplicate categories"


def test_category_read(unique_category):
    """Tests reading a category back from the database."""
    unique_category.create()
    read_category = Category.read(
        user_hash=unique_category.user_hash, name_hash=unique_category.name_hash
    )
    assert read_category is not None, "Category should be readable"
    assert read_category.name == unique_category.name, "Category name should match"


def test_category_read_all(unique_category):
    """Tests reading all categories for a user."""
    # Create multiple categories for testing
    for i in range(3):
        unique_category.name += f" {i}"
        unique_category.create()

    categories = Category.read_all(unique_category.user_hash)
    assert len(categories) == 3, "Should read all categories for a user"

    for category in categories:
        assert (
            category.user_hash == unique_category.user_hash
        ), "Category should be for the correct user"


@pytest.mark.filterwarnings("ignore::UserWarning")
def test_get_items(unique_category, unique_item_strict):
    """Tests getting all items for a category."""
    unique_category.create()

    items = [unique_item_strict.model_copy() for i in range(3)]

    with unique_category.db_con() as r:
        for i, item in enumerate(items):
            item.url = f"http://example.com/{i}"
            item.create()
            r.zadd(unique_category.items_key, {item.url_hash: i})

    act_items = unique_category.query_items()
    assert len(act_items) == 3, "Should get all items for a category"
    for item in act_items:
        assert item.url_hash in [
            i.url_hash for i in items
        ], "Should get the correct items"

    unique_category.delete()

    assert not unique_category.exists()


def test_sources(unique_category, unique_source):
    """Tests adding and removing sources from a category."""
    unique_category.create()

    unique_category.add_source(unique_source)
    assert unique_source.name_hash in unique_category.source_hashes
    assert len(unique_category.source_hashes) == 1
    assert unique_source in unique_category.sources
    assert unique_source.exists()

    unique_category.delete_source(unique_source)
    assert unique_source.name_hash not in unique_category.source_hashes
    assert not unique_source.exists()


def test_delete_category_removes_sources(unique_category, unique_source):
    """Tests that deleting a category removes its sources."""
    unique_category.create()
    unique_category.add_source(unique_source)

    with unique_category.db_con() as r:
        assert r.exists(unique_category.sources_key)
        assert not r.exists(unique_category.items_key)
        assert r.exists(unique_category.key)
        assert r.exists(unique_source.key)

    unique_category.delete()
    assert not unique_source.exists()
    assert not unique_category.exists()
    with unique_category.db_con() as r:
        assert not r.exists(unique_category.sources_key)
        assert not r.exists(unique_category.items_key)
        assert not r.exists(unique_category.key)
        assert not r.exists(unique_source.key)


def test_remove_items(unique_category, unique_item_strict):
    """Tests removing items from a category."""
    unique_category.create()
    unique_item_strict.create()
    unique_category.add_items(unique_item_strict)

    assert unique_item_strict in unique_category.query_items()

    unique_category.remove_items(unique_item_strict)
    assert unique_item_strict not in unique_category.query_items()
    assert unique_item_strict.exists()

    unique_category.delete()
    assert not unique_category.exists()
    assert unique_item_strict.exists()
