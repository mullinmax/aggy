import pytest

from db.source import Source


def test_create_source(unique_source):
    unique_source.create()
    assert unique_source.exists()

    unique_source.delete()
    assert not unique_source.exists()


def test_duplicate_source_creation(unique_source):
    unique_source.create()

    with pytest.raises(Exception) as e:
        unique_source.create()  # Attempt to create duplicate source
    assert "Cannot create duplicate source" in str(
        e.value
    ), "Should not allow duplicate sources"


def test_read_source(unique_source):
    unique_source.create()
    read_source = Source.read(
        user_hash=unique_source.user_hash,
        feed_hash=unique_source.feed_hash,
        source_hash=unique_source.name_hash,
    )
    assert read_source, "Source should be readable"
    assert read_source.name == unique_source.name, "Source name should match"
    assert read_source.url == unique_source.url, "Source url should match"
    assert (
        read_source.user_hash == unique_source.user_hash
    ), "Source user_hash should match"
    assert (
        read_source.feed_hash == unique_source.feed_hash
    ), "Source feed_hash should match"


def test_source_add_items(unique_source, unique_item_strict):
    unique_source.create()
    unique_item_strict.create()
    unique_source.add_items(items=[unique_item_strict])
    assert (
        unique_item_strict in unique_source.query_items()
    ), "Item should be in source items"


def test_count_items(unique_source, unique_item_strict):
    unique_source.create()
    unique_item_strict.create()
    assert unique_source.count_items() == 0, "Should not count items in source"
    unique_source.add_items(unique_item_strict)
    assert unique_source.count_items() == 1, "Should count items in source"
