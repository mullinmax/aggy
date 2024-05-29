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


def test_feeds_key(unique_category):
    """Tests the feeds_key property."""
    assert (
        unique_category.feeds_key
        == f"USER:{unique_category.user_hash}:CATEGORY:{unique_category.name_hash}:FEEDS"
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
    assert read_category, "Category should be readable"
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


def test_feeds(unique_category, unique_feed):
    """Tests adding and removing feeds from a category."""
    unique_category.create()

    unique_category.add_feed(unique_feed)
    assert unique_feed.name_hash in unique_category.feed_hashes
    assert len(unique_category.feed_hashes) == 1
    assert unique_feed in unique_category.feeds
    assert unique_feed.exists()

    unique_category.delete_feed(unique_feed)
    assert unique_feed.name_hash not in unique_category.feed_hashes
    assert not unique_feed.exists()


def test_delete_category_removes_feeds(unique_category, unique_feed):
    """Tests that deleting a category removes its feeds."""
    unique_category.create()
    unique_category.add_feed(unique_feed)

    with unique_category.db_con() as r:
        assert r.exists(unique_category.feeds_key)
        assert not r.exists(unique_category.items_key)
        assert r.exists(unique_category.key)
        assert r.exists(unique_feed.key)

    unique_category.delete()
    assert not unique_feed.exists()
    assert not unique_category.exists()
    with unique_category.db_con() as r:
        assert not r.exists(unique_category.feeds_key)
        assert not r.exists(unique_category.items_key)
        assert not r.exists(unique_category.key)
        assert not r.exists(unique_feed.key)
