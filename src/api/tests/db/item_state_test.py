import pytest

from db.item_state import ItemState


def test_create_item_state(existing_item_state):
    assert existing_item_state.exists(), "ItemState should exist after creation"


def test_delete_item_state(existing_item_state):
    existing_item_state.delete()
    assert not existing_item_state.exists(), "ItemState should not exist after deletion"


def test_update_item_state(existing_item_state):
    assert existing_item_state.is_read, "ItemState is_read should be True"
    existing_item_state.is_read = False
    existing_item_state.update()
    assert not existing_item_state.is_read, "ItemState is_read should be updated"


def test_read_item_state(existing_item_state):
    read_item_state = ItemState.read(
        user_hash=existing_item_state.user_hash,
        category_hash=existing_item_state.category_hash,
        item_url_hash=existing_item_state.item_url_hash,
    )
    assert read_item_state, "ItemState should be readable"
    assert (
        read_item_state.is_read == existing_item_state.is_read
    ), "ItemState is_read should match"
    assert (
        read_item_state.score == existing_item_state.score
    ), "ItemState score should match"
    assert (
        read_item_state.user_hash == existing_item_state.user_hash
    ), "ItemState user_hash should match"
    assert (
        read_item_state.category_hash == existing_item_state.category_hash
    ), "ItemState category_hash should match"
    assert (
        read_item_state.item_url_hash == existing_item_state.item_url_hash
    ), "ItemState item_url_hash should match"
    assert read_item_state.key == existing_item_state.key, "ItemState key should match"
    assert (
        read_item_state == existing_item_state
    ), "ItemState should match existing_item_state"
    assert read_item_state.exists(), "ItemState should exist"


@pytest.mark.parametrize(
    "score,is_read,expected_score,expected_is_read",
    [
        (1, False, 1, False),
        (None, False, 0.5, False),
        (1, None, 1, True),
    ],
)
def test_set_state(
    existing_item_state, score, is_read, expected_score, expected_is_read
):
    assert existing_item_state.is_read, "ItemState is_read should be True"
    assert existing_item_state.score == 0.5, "ItemState score should be 0.5"

    ItemState.set_state(
        user_hash=existing_item_state.user_hash,
        category_hash=existing_item_state.category_hash,
        item_url_hash=existing_item_state.item_url_hash,
        score=score,
        is_read=is_read,
    )

    read_item_state = ItemState.read(
        user_hash=existing_item_state.user_hash,
        category_hash=existing_item_state.category_hash,
        item_url_hash=existing_item_state.item_url_hash,
    )

    assert read_item_state.is_read == expected_is_read, "ItemState is_read should match"
    assert read_item_state.score == expected_score, "ItemState score should match"
    if score is not None:
        assert (
            read_item_state.score_date != existing_item_state.score_date
        ), "ItemState score_date should be updated"
    else:
        assert (
            read_item_state.score_date == existing_item_state.score_date
        ), "ItemState score_date should not be updated"


def test_read_non_existent_item_state(unique_item_state):
    assert not unique_item_state.exists(), "ItemState should not exist before creation"
    read_item_state = ItemState.read(
        user_hash=unique_item_state.user_hash,
        category_hash=unique_item_state.category_hash,
        item_url_hash=unique_item_state.item_url_hash,
    )
    assert read_item_state is None, "ItemState should not be readable"


def test_create_item_state_with_bad_user_hash(unique_item_state):
    unique_item_state.user_hash = "bad_user_hash"
    with pytest.raises(Exception) as e:
        unique_item_state.create()

    assert "User" in str(e.value), "Should not create ItemState with bad user_hash"


def test_create_item_state_with_bad_category_hash(unique_item_state, existing_user):
    unique_item_state.category_hash = "bad_category_hash"
    with pytest.raises(Exception) as e:
        unique_item_state.create()
    assert "Category" in str(
        e.value
    ), "Should not create ItemState with bad category_hash"


def test_create_item_state_with_bad_item_url_hash(
    unique_item_state, existing_user, existing_category
):
    unique_item_state.item_url_hash = "bad_item_url_hash"
    with pytest.raises(Exception) as e:
        unique_item_state.create()
    assert "Item" in str(e.value), "Should not create ItemState with bad item_url_hash"
