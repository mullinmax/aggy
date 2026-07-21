"""List membership acts as an extra positive vote for the ranking model."""

from db.item_state import ItemState
from db.list import UserList
from ranking.engine import _effective_label, load_feed_features


def test_effective_label_unvoted_listed_reads_as_upvote():
    assert _effective_label(None, None) is None
    assert _effective_label(None, "2021-01-01") == 1.0


def test_effective_label_downvote_plus_list_is_neutral():
    assert _effective_label(-1.0, "2021-01-01") == 0.0


def test_effective_label_upvote_stays_clamped():
    assert _effective_label(1.0, "2021-01-01") == 1.0


def test_effective_label_no_list_keeps_vote():
    assert _effective_label(-1.0, None) == -1.0
    assert _effective_label(0.0, None) == 0.0


def test_listed_item_becomes_positive_label(
    existing_user, existing_feed, existing_source, existing_item_strict
):
    # no vote yet -> no label
    features = {f.url_hash: f for f in load_feed_features(existing_feed)}
    assert features[existing_item_strict.url_hash].label is None

    # adding the item to a list gives it a positive label
    lst = UserList(user_hash=existing_user.name_hash, name="Favourites")
    lst.create()
    lst.add_item(existing_item_strict.url_hash)

    features = {f.url_hash: f for f in load_feed_features(existing_feed)}
    labeled = features[existing_item_strict.url_hash]
    assert labeled.label == 1.0
    assert labeled.label_date is not None


def test_explicit_vote_takes_precedence_over_list_date(
    existing_user, existing_feed, existing_source, existing_item_strict
):
    ItemState.set_state(
        user_hash=existing_user.name_hash,
        feed_hash=existing_feed.name_hash,
        item_url_hash=existing_item_strict.url_hash,
        score=-1,
        is_read=True,
    )
    lst = UserList(user_hash=existing_user.name_hash, name="Favourites")
    lst.create()
    lst.add_item(existing_item_strict.url_hash)

    features = {f.url_hash: f for f in load_feed_features(existing_feed)}
    labeled = features[existing_item_strict.url_hash]
    # downvote (-1) plus a list membership (+1) nets to neutral
    assert labeled.label == 0.0
