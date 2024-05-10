def test_exists(existing_category, existing_user):
    assert existing_category.exists()
    assert existing_user.exists()
    assert existing_user.categories == [existing_category]
