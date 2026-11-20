"""The replay harness, checked on feeds whose taste was planted by hand.

The harness is only worth trusting on real votes if it can tell a good method
from a useless one when the right answer is known, and if it cannot be fooled
by a method that peeks at the future.
"""

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from ranking.experiments import diagnostics, metrics, replay
from ranking.experiments.methods import (
    ExperimentModel,
    OpensAsNeutralModel,
    experiment_models,
)
from ranking.models import ItemFeatures, KNNEmbeddingModel, RandomModel

START = datetime(2026, 1, 1, tzinfo=timezone.utc)
NO_REST = dict(rest_fraction=0.0)


def planted_feed(n=120, dim=16, seed=0, drift_at=None):
    """Votes with a taste a model can find: two clusters of articles, one
    upvoted and one downvoted. With `drift_at` the taste flips part way."""
    rng = np.random.default_rng(seed)
    centres = rng.normal(size=(2, dim)) * 3.0
    items = []
    for index in range(n):
        cluster = int(rng.integers(2))
        liked = cluster == 0
        if drift_at is not None and index >= drift_at:
            liked = not liked
        items.append(
            ItemFeatures(
                url_hash=f"item-{seed}-{index}",
                embedding=centres[cluster] + rng.normal(size=dim),
                source=f"source-{cluster}",
                date_published=START + timedelta(hours=index - 2),
                label=1.0 if liked else -1.0,
                label_date=START + timedelta(hours=index),
            )
        )
    return items


def _by_method(rows):
    return {row["method"]: row for row in rows}


def _summary(blocks, methods):
    calibrated = {m.name: replay.is_calibrated(m) for m in methods}
    return _by_method(replay.summarize(blocks, calibrated, n_boot=50))


# --- metrics ---------------------------------------------------------------


def test_auc_is_one_for_a_perfect_order_and_half_for_a_constant():
    labels = np.array([1.0, 0.0, -1.0, 1.0])
    assert metrics.auc(np.array([0.9, 0.2, 0.1, 0.8]), labels) == 1.0
    assert metrics.auc(np.array([0.1, 0.8, 0.9, 0.2]), labels) == 0.0
    # every article tied: no order was predicted, so no credit and no blame
    assert metrics.auc(np.zeros(4), labels) == 0.5


def test_auc_is_undefined_without_both_kinds_of_vote():
    assert metrics.auc(np.array([0.1, 0.2]), np.array([1.0, 1.0])) is None
    assert metrics.auc(np.array([0.1, 0.2]), np.array([0.0, -1.0])) is None


def test_top_k_counts_only_upvotes_among_the_highest_ranked():
    rng = np.random.default_rng(0)
    labels = np.array([1.0, 1.0, 0.0, -1.0, 1.0, -1.0])
    scores = np.array([0.9, 0.8, 0.7, 0.1, 0.2, 0.3])
    assert metrics.top_k_hit_rate(scores, labels, 3, rng) == pytest.approx(2 / 3)


def test_ndcg_credits_a_neutral_above_a_downvote():
    rng = np.random.default_rng(0)
    labels = np.array([1.0, 0.0, -1.0])
    good = metrics.ndcg(np.array([3.0, 2.0, 1.0]), labels, 10, rng)
    worse = metrics.ndcg(np.array([3.0, 1.0, 2.0]), labels, 10, rng)
    assert good == pytest.approx(1.0)
    assert worse < good


# --- the replay ------------------------------------------------------------


def test_a_feed_with_too_few_votes_is_not_replayed():
    assert replay.replay_feed(planted_feed(n=12), [KNNEmbeddingModel()]) == []


def test_blocks_cover_every_vote_after_the_warmup_exactly_once():
    items = planted_feed(n=100)
    config = replay.ReplayConfig(warmup=10, max_blocks=6, **NO_REST)
    blocks = replay.replay_feed(items, [KNNEmbeddingModel()], config)
    assert len(blocks) == 6
    assert sum(len(b.labels) for b in blocks) == 90
    # each block is trained on strictly more than the one before
    assert [b.train_n for b in blocks] == sorted({b.train_n for b in blocks})


def test_a_real_method_beats_chance_on_a_planted_taste():
    methods = [RandomModel(), KNNEmbeddingModel()]
    blocks = replay.replay_feed(planted_feed(), methods, replay.ReplayConfig(**NO_REST))
    rows = _summary(blocks, methods)
    assert rows["knn_embedding"]["auc"] > 0.9
    assert 0.3 < rows["random"]["auc"] < 0.7
    assert rows["knn_embedding"]["top5_hit_rate"] > rows["random"]["top5_hit_rate"]


class _RecordsWhatItSaw(ExperimentModel):
    """Remembers the newest vote it was ever fitted on."""

    name = "spy"

    def __init__(self):
        self.pairs = []

    def fit(self, items):
        self.newest_seen = max(i.label_date for i in items)

    def predict(self, items):
        self.pairs.append((self.newest_seen, min(i.label_date for i in items)))
        return np.zeros(len(items)), np.zeros(len(items))


def test_a_method_is_never_fitted_on_a_vote_from_the_future():
    spy = _RecordsWhatItSaw()
    replay.replay_feed(planted_feed(), [spy], replay.ReplayConfig(**NO_REST))
    assert spy.pairs
    for newest_trained_on, oldest_predicted in spy.pairs:
        assert newest_trained_on < oldest_predicted


def test_account_methods_borrow_from_other_feeds_but_not_from_the_future():
    feed = planted_feed(n=60, seed=1)
    other = planted_feed(n=60, seed=2)

    class Spy(_RecordsWhatItSaw):
        name = "account_spy"
        scope = "account"

        def fit(self, items):
            super().fit(items)
            self.borrowed = sum(1 for i in items if i.url_hash.startswith("item-2-"))
            self.own = {i.url_hash for i in items}

        def predict(self, items):
            assert not self.own & {i.url_hash for i in items}
            return super().predict(items)

    spy = Spy()
    replay.replay_feed(
        feed, [spy], replay.ReplayConfig(**NO_REST), account_items=feed + other
    )
    assert spy.borrowed > 0
    for newest_trained_on, oldest_predicted in spy.pairs:
        assert newest_trained_on < oldest_predicted


def test_every_method_survives_a_replay_and_reports_a_score():
    """The whole roster, on a feed small enough to be quick. A method that
    raises is silently dropped from a real run, so this is where it shows."""
    methods = replay.build_methods(quick=True)
    feed = planted_feed(n=90)
    blocks = replay.replay_feed(
        feed,
        methods,
        replay.ReplayConfig(max_blocks=4, quick=True, **NO_REST),
        account_items=feed,
    )
    rows = _summary(blocks, methods)
    expected = {m.name for m in methods if not getattr(m, "uses_opens", False)}
    assert expected <= set(rows)
    # the strong blend needs the random forest, which a quick run leaves out
    assert set(replay.COMBINED) - {replay.BLEND_STRONG} <= set(rows)
    baselines = {"random", "global_mean", "newest_first", "oldest_first"}
    for name in expected - baselines:
        assert rows[name]["auc"] > 0.6, name


def test_methods_have_distinct_names():
    names = [m.name for m in replay.build_methods()]
    assert len(names) == len(set(names))
    assert not set(names) & set(replay.COMBINED)


def test_uncalibrated_methods_report_no_error_on_the_vote_scale():
    methods = [m for m in experiment_models() if m.name == "taste_profile"]
    blocks = replay.replay_feed(planted_feed(), methods, replay.ReplayConfig(**NO_REST))
    row = _summary(blocks, methods)["taste_profile"]
    assert row["auc"] is not None
    assert row["mae"] is None and row["three_way_accuracy"] is None


def test_the_comparison_with_the_baseline_names_a_clear_winner():
    methods = [RandomModel(), KNNEmbeddingModel()]
    blocks = replay.replay_feed(planted_feed(), methods, replay.ReplayConfig(**NO_REST))
    calibrated = {m.name: True for m in methods}
    rows = _by_method(replay.summarize(blocks, calibrated, baseline="random"))
    versus = rows["knn_embedding"]["vs_baseline"]
    assert versus["verdict"] == "better"
    assert versus["auc_diff"] > 0.3
    assert versus["auc_diff_range"][0] > 0
    assert rows["random"]["vs_baseline"] is None


def test_blocks_are_reported_by_how_much_there_was_to_learn_from():
    methods = [KNNEmbeddingModel()]
    blocks = replay.replay_feed(
        planted_feed(n=260), methods, replay.ReplayConfig(**NO_REST)
    )
    bands = _summary(blocks, methods)["knn_embedding"]["by_training_size"]
    assert set(bands) == {"under_50", "50_to_199", "200_plus"}


def test_recency_weighting_wins_when_the_taste_flips():
    """The reason the recency methods exist: after the flip, old votes point
    the wrong way, and a model that discounts them should recover first."""
    from ranking.experiments.methods import RecentKNNModel

    feed = planted_feed(n=200, drift_at=100)
    methods = [KNNEmbeddingModel(k=40), RecentKNNModel(half_life_days=0.5, k=40)]
    blocks = replay.replay_feed(feed, methods, replay.ReplayConfig(**NO_REST))
    rows = _summary(blocks, methods)
    assert rows[methods[1].name]["auc"] > rows["knn_embedding"]["auc"]


def test_opens_are_only_used_once_they_are_old_enough_and_still_unvoted():
    feed = planted_feed(n=60)
    cutoff_free = [
        ItemFeatures(
            url_hash=f"opened-{i}",
            embedding=np.ones(16),
            label=0.0,
            label_date=START + timedelta(hours=i),
        )
        for i in range(40)
    ]
    seen = []

    class Spy(OpensAsNeutralModel):
        min_opens = 1

        def fit(self, items):
            seen.append(list(self.extra_items))
            super().fit(items)

    replay.replay_feed(
        feed,
        [Spy()],
        replay.ReplayConfig(open_grace=timedelta(hours=5), **NO_REST),
        opened_items=cutoff_free + [feed[3]],
    )
    assert seen
    for extra in seen:
        # an article already voted on is a vote, not a quiet open
        assert all(i.url_hash.startswith("opened-") for i in extra)
    # the first block starts at vote 10 (hour 10): opens from hours 0-4 qualify
    assert {i.url_hash for i in seen[0]} == {f"opened-{i}" for i in range(5)}


def test_a_method_with_too_few_opens_sits_out():
    methods = [OpensAsNeutralModel()]
    blocks = replay.replay_feed(planted_feed(), methods, replay.ReplayConfig(**NO_REST))
    assert all("opens_as_neutral_knn" not in b.predictions for b in blocks)


def test_a_stop_request_ends_the_replay():
    with pytest.raises(replay.Cancelled):
        replay.replay_feed(
            planted_feed(), [KNNEmbeddingModel()], should_stop=lambda: True
        )


def test_the_llm_judge_is_rationed_and_scored_only_on_what_it_judged():
    from ranking.experiments.llm_judge import LLMJudgeModel

    feed = planted_feed(n=100)
    texts = {i.url_hash: (f"title {i.url_hash}", "excerpt") for i in feed}
    prompts = []

    def ask(prompt):
        prompts.append(prompt)
        return 0.9

    judge = LLMJudgeModel(texts, ask=ask, max_items=3)
    methods = [KNNEmbeddingModel(), judge]
    blocks = replay.replay_feed(feed, methods, replay.ReplayConfig(**NO_REST))
    judged = [b for b in blocks if "llm_judge" in b.predictions]
    assert len(judged) == judge.last_blocks
    assert len(prompts) == 3 * judge.last_blocks
    for block in judged:
        assert int((~np.isnan(block.predictions["llm_judge"])).sum()) == 3
    row = _summary(blocks, methods)["llm_judge"]
    assert row["predictions"] == 3 * judge.last_blocks
    # the prompt shows headlines, and never a vote the judge should not know
    assert "title item-0-" in prompts[0]


def test_an_unreachable_llm_is_dropped_rather_than_scored():
    from ranking.experiments.llm_judge import LLMJudgeModel

    def ask(prompt):
        raise ConnectionError("no model")

    methods = [LLMJudgeModel({}, ask=ask)]
    blocks = replay.replay_feed(planted_feed(), methods, replay.ReplayConfig(**NO_REST))
    assert all("llm_judge" not in b.predictions for b in blocks)


# --- round 2: the fixed rule, the blends and what a method may know ---------


def _live_trio():
    return [
        m
        for m in replay.build_methods(quick=True)
        if m.name in ("knn_embedding", "source_prior_knn", "svr")
    ]


def test_the_live_rule_ranks_with_the_model_its_ladder_names():
    blocks = replay.replay_feed(
        planted_feed(n=60),
        _live_trio(),
        replay.ReplayConfig(warmup=4, max_blocks=10, min_block=2, **NO_REST),
    )
    assert {b.rule_choice for b in blocks if b.train_n < 6} == {"knn_embedding"}
    assert {b.rule_choice for b in blocks if 6 <= b.train_n < 12} == {
        "source_prior_knn"
    }
    assert {b.rule_choice for b in blocks if b.train_n >= 12} == {"svr"}
    for block in blocks:
        assert np.array_equal(
            block.predictions[replay.LIVE_RULE], block.predictions[block.rule_choice]
        )


def test_the_live_rule_steps_down_when_its_model_could_not_be_fitted():
    methods = [m for m in _live_trio() if m.name != "svr"]
    blocks = replay.replay_feed(
        planted_feed(n=60), methods, replay.ReplayConfig(**NO_REST)
    )
    assert {b.rule_choice for b in blocks} == {"source_prior_knn"}


def test_a_blend_needs_every_one_of_its_members():
    blocks = replay.replay_feed(
        planted_feed(n=60), _live_trio(), replay.ReplayConfig(**NO_REST)
    )
    rows = _summary(blocks, _live_trio())
    assert rows[replay.BLEND_SVR_PRIOR]["auc"] > 0.9
    # no random forest was fitted, so there is no strong blend to report
    assert replay.BLEND_STRONG not in rows


class _RecordsVoteTimes(ExperimentModel):
    name = "records_vote_times"

    def __init__(self):
        self.seen = []

    def fit(self, items):
        pass

    def predict(self, items):
        self.seen.append([i.label_date for i in items])
        return np.zeros(len(items)), np.zeros(len(items))


class _ToldVoteTimes(_RecordsVoteTimes):
    name = "told_vote_times"
    sees_vote_time = True


def test_a_method_is_not_told_when_the_articles_it_ranks_were_voted_on():
    """An article's age is measured at its vote. For the articles being
    predicted that is knowledge from the future, so they are all aged as of
    the start of their block."""
    blind, told = _RecordsVoteTimes(), _ToldVoteTimes()
    feed = planted_feed()
    blocks = replay.replay_feed(feed, [blind, told], replay.ReplayConfig(**NO_REST))
    assert blocks
    for dates in blind.seen:
        assert len(set(dates)) == 1
    assert any(len(set(dates)) > 1 for dates in told.seen)
    # and the feed's own articles were not changed to do it
    assert len({i.label_date for i in feed}) == len(feed)


# --- diagnostics -----------------------------------------------------------


def test_diagnostics_see_a_taste_the_embeddings_carry():
    found = diagnostics.diagnose(planted_feed(n=200))
    similar = found["similar_votes"]
    assert similar["compared"] == 200
    assert similar["nearest_agrees"] > 0.95
    assert similar["agreement_by_chance"] == pytest.approx(0.5, abs=0.05)
    assert found["coverage"]["text_embedding"] == 1.0
    assert found["coverage"]["stored_neighbors"] == 0.0
    assert found["sources"]["distinct"] == 2
    assert found["sources"]["upvote_rate_spread"] == pytest.approx(0.5)


def test_diagnostics_see_votes_that_ignore_the_embeddings():
    feed = planted_feed(n=300)
    rng = np.random.default_rng(1)
    for item in feed:
        item.label = 1.0 if rng.random() < 0.5 else -1.0
    similar = diagnostics.diagnose(feed)["similar_votes"]
    assert abs(similar["nearest_agrees"] - similar["agreement_by_chance"]) < 0.1


def test_diagnostics_spot_votes_cast_in_bulk():
    feed = planted_feed(n=80)
    for item in feed[:20]:
        item.label_date = START  # twenty votes in the same instant
    timing = diagnostics.diagnose(feed)["timing"]
    assert timing["in_one_minute_bursts"] == pytest.approx(20 / 80)
    assert timing["largest_burst_share"] == pytest.approx(20 / 80)
    assert len(timing["upvote_rate_by_quarter"]) == 4
    assert timing["days_with_votes"] >= 3


def test_diagnostics_say_how_the_labels_came_about():
    feed = planted_feed(n=40)
    origins = {
        item.url_hash: {
            "vote": None if index < 10 else 1,
            "listed": index < 20,
        }
        for index, item in enumerate(feed)
    }
    origin = diagnostics.diagnose(feed, origins)["label_origin"]
    assert origin == {"list_only": 0.25, "vote_and_list": 0.25, "vote_only": 0.5}


def test_diagnostics_name_no_source():
    text = str(diagnostics.diagnose(planted_feed()))
    assert "source-0" not in text and "item-0" not in text


def test_diagnostics_of_an_empty_feed_are_absent():
    assert diagnostics.diagnose([]) is None
