import pytest
from datetime import timedelta

from db.item_state import ItemState


@pytest.fixture(scope="function")
def unique_item_state(unique_item_strict, unique_user, unique_category):
    item_state = ItemState(
        item_url_hash=unique_item_strict.url_hash,
        user_hash=unique_user.name_hash,
        category_hash=unique_category.name_hash,
        score=0.5,
        score_date=unique_item_strict.date_published + timedelta(days=1),
        is_read=True,
    )

    yield item_state

    if item_state.exists():
        item_state.delete()


@pytest.fixture(scope="function")
def existing_item_state(
    unique_item_state, existing_feed, existing_category, existing_item_strict
):
    unique_item_state.create()
    yield unique_item_state
