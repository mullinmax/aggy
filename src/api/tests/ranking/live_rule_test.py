"""Which model ranks a feed: a fixed rule on the number of votes, not the
winner of a bake-off. The comparison still exists, for the stats screen, and
only when it is asked for."""

import uuid

import pytest
from pydantic import HttpUrl

from db.item import ItemLoose
from db.item_state import ItemState
from ranking import engine, progress
from ranking.engine import (
    chosen_model_name,
    feed_ranking_job,
    feeds_needing_training,
    load_model_stats,
    rank_feed,
    training_steps,
    training_summary,
)
from ranking.explain import _winner_model
from ranking.models import LIVE_MODEL_LADDER, SVRModel, all_models, live_model_name


def _voted(user, feed, n):
    items = []
    for index in range(n):
        item = ItemLoose(
            url=HttpUrl(f"http://example.com/{uuid.uuid4()}/"),
            title="Title",
            author="Someone",
            domain="example.com",
            excerpt="words",
            content="<p>words</p>",
            embeddings={"test-model": [5.0 if index % 2 == 0 else -5.0, 0.1 * index]},
        )
        item.create()
        feed.add_items(item)
        ItemState.set_state(
            user_hash=user.name_hash,
            feed_hash=feed.name_hash,
            item_url_hash=item.url_hash,
            score=1 if index % 2 == 0 else -1,
            is_read=True,
        )
        items.append(item)
    return items


def _predicted_by(feed):
    with engine.get_db_con() as cur:
        cur.execute(
            "SELECT DISTINCT predicted_model FROM feed_items "
            "WHERE user_hash = %s AND feed_hash = %s",
            (feed.user_hash, feed.name_hash),
        )
        return {row["predicted_model"] for row in cur.fetchall()}


@pytest.mark.parametrize(
    "votes, model",
    [
        (0, None),
        (1, None),
        (2, "knn_embedding"),
        (5, "knn_embedding"),
        (6, "source_prior_knn"),
        (11, "source_prior_knn"),
        (12, "svr"),
        (5000, "svr"),
    ],
)
def test_the_rule_climbs_with_the_number_of_votes(votes, model):
    assert live_model_name(votes) == model


def test_every_rung_is_a_model_the_app_has():
    assert set(LIVE_MODEL_LADDER) <= {m.name for m in all_models() if m.rankable}


@pytest.mark.parametrize("votes", [4, 8, 14])
def test_a_retrain_fits_the_rules_model_and_compares_nothing(
    existing_user, existing_feed, monkeypatch, votes
):
    def fail(*args, **kwargs):
        raise AssertionError("a plain retrain cross-validated the models")

    monkeypatch.setattr(engine, "evaluate_models", fail)
    _voted(existing_user, existing_feed, votes)

    stats = rank_feed(existing_feed)

    expected = live_model_name(votes)
    assert [s.model_name for s in stats if s.chosen] == [expected]
    assert chosen_model_name(existing_feed) == expected
    assert _predicted_by(existing_feed) == {expected}
    summary = training_summary(existing_feed)
    assert summary["trained_model"] == expected
    assert summary["trained_labels"] == votes
    assert summary["votes_since_training"] == 0


def test_a_comparison_reports_every_model_but_the_rule_still_chooses(
    existing_user, existing_feed
):
    _voted(existing_user, existing_feed, 14)

    stats = rank_feed(existing_feed, bakeoff=True)

    assert {s.model_name for s in stats} == {m.name for m in all_models()}
    assert [s.model_name for s in stats if s.chosen] == ["svr"]
    assert any(s.mae is not None for s in stats if not s.chosen)
    assert _predicted_by(existing_feed) == {"svr"}


def test_a_retrain_keeps_the_last_comparisons_figures(existing_user, existing_feed):
    items = _voted(existing_user, existing_feed, 8)
    rank_feed(existing_feed, bakeoff=True)
    before = {row["model_name"]: row["mae"] for row in load_model_stats(existing_feed)}
    assert chosen_model_name(existing_feed) == "source_prior_knn"

    # enough new votes to move the feed up a rung
    more = _voted(existing_user, existing_feed, 6)
    rank_feed(existing_feed)

    after = {row["model_name"]: row for row in load_model_stats(existing_feed)}
    assert chosen_model_name(existing_feed) == "svr"
    assert [name for name, row in after.items() if row["chosen"]] == ["svr"]
    assert {name: row["mae"] for name, row in after.items()} == before
    assert training_summary(existing_feed)["trained_labels"] == len(items) + len(more)


def test_a_model_that_cannot_be_fitted_hands_over_to_the_next_rung(
    existing_user, existing_feed, monkeypatch
):
    def broken(self, items):
        raise ValueError("no")

    monkeypatch.setattr(SVRModel, "fit", broken)
    _voted(existing_user, existing_feed, 14)

    rank_feed(existing_feed)

    assert chosen_model_name(existing_feed) == "source_prior_knn"
    assert _predicted_by(existing_feed) == {"source_prior_knn"}


def test_a_feed_ranked_by_the_old_picker_is_moved_onto_the_rule_once(
    existing_user, existing_feed
):
    """Feeds trained before the rule existed carry whichever model had the
    lowest error. They are retrained without waiting for a new vote."""
    _voted(existing_user, existing_feed, 14)
    rank_feed(existing_feed, bakeoff=True)
    with engine.get_db_con() as cur:
        cur.execute(
            "UPDATE ranking_model_stats SET chosen = (model_name = 'ridge') "
            "WHERE user_hash = %s AND feed_hash = %s",
            (existing_feed.user_hash, existing_feed.name_hash),
        )
    progress.reset()
    assert existing_feed.name in {f.name for f in feeds_needing_training()}

    feed_ranking_job()

    assert chosen_model_name(existing_feed) == "svr"
    assert _predicted_by(existing_feed) == {"svr"}
    assert existing_feed.name not in {f.name for f in feeds_needing_training()}


def test_a_feed_left_with_nothing_to_rank_on_stops_asking_to_be_retrained(
    existing_user, existing_feed
):
    _voted(existing_user, existing_feed, 4)
    rank_feed(existing_feed)
    _voted(existing_user, existing_feed, 1)  # a vote the model has not seen
    assert existing_feed.name in {f.name for f in feeds_needing_training()}

    engine.save_live_choice(existing_feed, None, 0)

    assert chosen_model_name(existing_feed) is None
    assert existing_feed.name not in {f.name for f in feeds_needing_training()}


def test_a_plain_retrain_reports_three_steps():
    assert training_steps() == 3
    assert training_steps(bakeoff=True) == 3 + len(all_models())


def test_an_explanation_uses_the_rule_before_anything_was_trained(
    existing_user, existing_feed
):
    _voted(existing_user, existing_feed, 14)
    labeled = [
        f
        for f in engine.load_feed_features(existing_feed, labeled_only=True)
        if f.label is not None
    ]
    assert _winner_model(existing_feed, labeled).name == "svr"
