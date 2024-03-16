# import pytest
# from unittest.mock import patch
# from src.shared.db.category import Category
# from src.shared.db.item import ItemStrict

# @pytest.fixture
# def user_hash():
#     return "test_user_hash"

# @pytest.fixture
# def category_data():
#     return {"user_hash": "test_user_hash", "name": "Test Category"}

# @pytest.fixture
# def item_data():
#     return {
#         "url": "https://example.com/",
#         "title": "Example Title",
#         "content": "<p>Example Content</p>",
#         "author": "Author Name",
#         "image_url": "https://example.com/image.jpg",
#         "domain": "example.com",
#         "excerpt": "Example excerpt",
#         "date_published": "2021-01-01T00:00:00",
#     }

# ### Test Cases

# @pytest.mark.parametrize("name", ["Category 1", "Category 2"])
# def test_category_creation(name, user_hash, monkeypatch):
#     # Mock the Redis 'exists' and 'hset' calls
#     monkeypatch.setattr("src.shared.db.category.r.exists", lambda _: False)
#     monkeypatch.setattr("src.shared.db.category.r.hset", lambda *_: None)
#     monkeypatch.setattr("src.shared.db.category.r.sadd", lambda *_: None)

#     category = Category(user_hash=user_hash, name=name)
#     category_key = category.create()

#     assert category_key == category.__key__, "Category key should match the generated key"

# def test_duplicate_category_creation_raises_exception(category_data, monkeypatch):
#     # Mock Redis 'exists' to simulate an existing category
#     monkeypatch.setattr("src.shared.db.category.r.exists", lambda _: True)

#     with pytest.raises(Exception, match=r".*already exists"):
#         category = Category(**category_data)
#         category.create()

# def test_category_read(user_hash, category_data, monkeypatch):
#     # Mock Redis 'hgetall' to return category data
#     monkeypatch.setattr("src.shared.db.category.r.hgetall", lambda _: category_data)

#     name_hash = "some_hash"
#     category = Category.read(user_hash, name_hash)

#     assert isinstance(category, Category), "Should return a Category instance"
#     assert category.name == category_data["name"], "Category name should match"

# def test_get_all_items_in_category(category_data, item_data, monkeypatch):
#     # Mock Redis 'zrange' to return a list of item URL hashes
#     monkeypatch.setattr("src.shared.db.category.r.zrange", lambda *_: ["item_url_hash"])
#     # Mock ItemStrict.read to return an item
#     monkeypatch.setattr("src.shared.db.item.ItemStrict.read", lambda _: ItemStrict(**item_data))

#     category = Category(**category_data)
#     items = category.get_all_items()

#     assert len(items) == 1, "Should retrieve one item"
#     assert items[0].title == item_data["title"], "Retrieved item title should match"
