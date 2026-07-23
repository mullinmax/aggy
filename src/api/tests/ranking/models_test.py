"""Pure-python tests for the vote-prediction models (no database)."""

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from ranking.models import (
    DeepMLPModel,
    GlobalMeanModel,
    GradientBoostModel,
    ItemFeatures,
    KNNEmbeddingModel,
    LogisticVoteModel,
    MLPModel,
    RandomForestModel,
    RandomModel,
    RidgeModel,
    SVRModel,
    SourceMeanModel,
    all_models,
    evaluate_models,
)


def make_item(idx, embedding, label=None, source="src", author="alice"):
    return ItemFeatures(
        url_hash=f"item{idx}",
        embedding=np.asarray(embedding, dtype=float),
        source=source,
        author=author,
        date_published=datetime.now(timezone.utc) - timedelta(days=idx),
        has_image=idx % 2 == 0,
        label=label,
    )


def two_cluster_data(n=30, dim=8, seed=0):
    """Upvoted items cluster around +e0, downvoted around -e0."""
    rng = np.random.default_rng(seed)
    items = []
    for i in range(n):
        label = 1.0 if i % 2 == 0 else -1.0
        center = np.zeros(dim)
        center[0] = label * 5
        emb = center + rng.normal(0, 0.5, dim)
        items.append(
            make_item(i, emb, label=label, source="up" if label > 0 else "down")
        )
    return items


def test_global_mean_predicts_mean():
    items = [
        make_item(i, [1, 0], label=lab) for i, lab in enumerate([1.0, 1.0, -1.0, 1.0])
    ]
    model = GlobalMeanModel()
    model.fit(items)
    scores, confs = model.predict(items)
    assert scores == pytest.approx(np.full(4, 0.5))
    assert (confs >= 0).all() and (confs <= 1).all()


def test_source_mean_separates_sources():
    items = [
        make_item(0, [1], label=1.0, source="good"),
        make_item(1, [1], label=1.0, source="good"),
        make_item(2, [1], label=-1.0, source="bad"),
        make_item(3, [1], label=-1.0, source="bad"),
    ]
    model = SourceMeanModel()
    model.fit(items)
    scores, _ = model.predict(
        [make_item(4, [1], source="good"), make_item(5, [1], source="bad")]
    )
    assert scores[0] > 0 > scores[1]


def test_knn_predicts_nearest_vote():
    items = two_cluster_data()
    model = KNNEmbeddingModel()
    model.fit(items)
    up_probe = make_item(100, [5, 0, 0, 0, 0, 0, 0, 0])
    down_probe = make_item(101, [-5, 0, 0, 0, 0, 0, 0, 0])
    scores, confs = model.predict([up_probe, down_probe])
    assert scores[0] > 0.5
    assert scores[1] < -0.5
    assert (confs > 0).all()


def test_knn_without_embedding_falls_back():
    items = two_cluster_data(n=10)
    model = KNNEmbeddingModel()
    model.fit(items)
    probe = ItemFeatures(url_hash="noemb")
    scores, confs = model.predict([probe])
    assert -1 <= scores[0] <= 1
    assert confs[0] <= 0.1


def test_ridge_learns_direction():
    items = two_cluster_data(n=40)
    model = RidgeModel()
    model.fit(items)
    scores, _ = model.predict(
        [
            make_item(100, [5, 0, 0, 0, 0, 0, 0, 0]),
            make_item(101, [-5, 0, 0, 0, 0, 0, 0, 0]),
        ]
    )
    assert scores[0] > 0 > scores[1]
    assert (np.abs(scores) <= 1).all()


def test_image_embedding_is_a_distinct_feature():
    """With identical text, the image embedding alone must move the score, so
    the picture is genuinely weighed apart from the words and the has-image
    flag."""
    items = []
    for i in range(40):
        liked = i % 2 == 0
        items.append(
            ItemFeatures(
                url_hash=f"img{i}",
                embedding=np.array([0.3, 0.3]),  # constant text for everyone
                image_embedding=np.array([1.0, 0.0] if liked else [-1.0, 0.0]),
                has_image=True,
                label=1.0 if liked else -1.0,
            )
        )
    model = RidgeModel()
    model.fit(items)
    same_text = np.array([0.3, 0.3])
    liked = ItemFeatures(
        url_hash="cl", embedding=same_text, image_embedding=np.array([1.0, 0.0]),
        has_image=True,
    )
    disliked = ItemFeatures(
        url_hash="cd", embedding=same_text, image_embedding=np.array([-1.0, 0.0]),
        has_image=True,
    )
    scores, _ = model.predict([liked, disliked])
    assert scores[0] > scores[1]


def test_missing_image_embedding_is_backward_compatible():
    """A feed with no image embeddings still trains and predicts (the image
    block is simply zero-width)."""
    items = two_cluster_data(n=20)  # none carry an image embedding
    model = RidgeModel()
    model.fit(items)
    scores, _ = model.predict(_up_down_probes())
    assert scores[0] > 0 > scores[1]


def _up_down_probes():
    return [
        make_item(100, [5, 0, 0, 0, 0, 0, 0, 0]),
        make_item(101, [-5, 0, 0, 0, 0, 0, 0, 0]),
    ]


def test_mlp_learns_direction():
    items = two_cluster_data(n=40)
    model = MLPModel(epochs=200)
    model.fit(items)
    scores, _ = model.predict(_up_down_probes())
    assert scores[0] > 0 > scores[1]


def test_mlp_accepts_multiple_hidden_layers():
    # a bare int and an explicit stack are both valid ways to size the net
    assert MLPModel(hidden=16).hidden == (16,)
    model = MLPModel(hidden=(12, 8), epochs=200)
    assert model.hidden == (12, 8)
    model.fit(two_cluster_data(n=40))
    scores, confs = model.predict(_up_down_probes())
    assert scores[0] > 0 > scores[1]
    assert (confs >= 0).all() and (confs <= 1).all()


def test_deep_mlp_learns_direction():
    # three hidden layers of ReLU units still recover the separation
    items = two_cluster_data(n=60)
    model = DeepMLPModel(hidden=(32, 16, 8), epochs=400)
    assert len(model.hidden) == 3
    model.fit(items)
    scores, confs = model.predict(_up_down_probes())
    assert scores[0] > 0 > scores[1]
    assert (np.abs(scores) <= 1).all()
    assert (confs >= 0).all() and (confs <= 1).all()


def test_logistic_learns_direction():
    items = two_cluster_data(n=40)
    model = LogisticVoteModel()
    model.fit(items)
    scores, confs = model.predict(_up_down_probes())
    assert scores[0] > 0 > scores[1]
    assert (np.abs(scores) <= 1).all()
    assert (confs >= 0).all() and (confs <= 1).all()


def test_svr_learns_direction():
    items = two_cluster_data(n=40)
    model = SVRModel()
    model.fit(items)
    scores, confs = model.predict(_up_down_probes())
    assert scores[0] > 0 > scores[1]
    assert (np.abs(scores) <= 1).all()
    assert (confs >= 0).all() and (confs <= 1).all()


def test_random_forest_learns_direction():
    items = two_cluster_data(n=40)
    model = RandomForestModel(n_trees=25)
    model.fit(items)
    scores, confs = model.predict(_up_down_probes())
    assert scores[0] > 0 > scores[1]
    assert (np.abs(scores) <= 1).all()
    assert (confs >= 0).all() and (confs <= 1).all()


def test_gradient_boost_learns_direction():
    items = two_cluster_data(n=40)
    model = GradientBoostModel(max_iter=60)
    model.fit(items)
    scores, confs = model.predict(_up_down_probes())
    assert scores[0] > 0 > scores[1]
    assert (np.abs(scores) <= 1).all()
    assert (confs >= 0).all() and (confs <= 1).all()


def test_random_model_predicts_in_range_and_reproducibly():
    items = two_cluster_data(n=20)
    model = RandomModel()
    model.fit(items)
    probes = _up_down_probes()
    scores, confs = model.predict(probes)
    assert (np.abs(scores) <= 1).all()
    assert (confs >= 0).all() and (confs <= 1).all()
    # same seed -> same guesses, so the stats don't jitter on every recompute
    again = RandomModel()
    again.fit(items)
    assert again.predict(probes)[0] == pytest.approx(scores)


def test_random_baseline_is_never_chosen():
    # separable data: real models beat chance, and the random baseline — even
    # if it got lucky — is excluded from winning because it's not rankable
    items = two_cluster_data(n=40)
    stats = evaluate_models(items)
    by_name = {s.model_name: s for s in stats}
    assert by_name["random"].mae is not None  # still reported for comparison
    assert not by_name["random"].chosen
    assert next(m for m in all_models() if m.name == "random").rankable is False


def test_evaluate_models_reports_all_and_picks_one():
    items = two_cluster_data(n=30)
    stats = evaluate_models(items)
    names = {s.model_name for s in stats}
    assert names == {m.name for m in all_models()}
    chosen = [s for s in stats if s.chosen]
    assert len(chosen) == 1
    # separable data: the winner must clearly beat the do-nothing baseline
    baseline = next(s for s in stats if s.model_name == "global_mean")
    assert chosen[0].mae < baseline.mae
    # knn should do very well on clustered embeddings
    knn = next(s for s in stats if s.model_name == "knn_embedding")
    assert knn.mae < 0.5
    assert knn.sign_accuracy > 0.8


def test_evaluate_all_models_when_well_labeled():
    # with plenty of votes every model (including the deep net) should be
    # eligible, produce real metrics, and one winner is chosen
    items = two_cluster_data(n=60)
    stats = evaluate_models(items)
    by_name = {s.model_name: s for s in stats}
    assert set(by_name) == {m.name for m in all_models()}
    for name in (
        "logistic",
        "svr",
        "random_forest",
        "gradient_boost",
        "neural_net",
        "deep_neural_net",
    ):
        assert by_name[name].mae is not None, f"{name} produced no metrics"
    chosen = [s for s in stats if s.chosen]
    assert len(chosen) == 1
    baseline = by_name["global_mean"]
    assert chosen[0].mae <= baseline.mae


def test_evaluate_models_with_few_labels():
    # 3 labels: heavy models are skipped (null metrics) but eval still works
    items = two_cluster_data(n=3)
    stats = evaluate_models(items)
    by_name = {s.model_name: s for s in stats}
    assert by_name["neural_net"].mae is None
    assert by_name["ridge"].mae is None
    assert by_name["knn_embedding"].mae is not None
    assert any(s.chosen for s in stats)


def test_evaluate_models_no_labels():
    stats = evaluate_models([])
    assert all(s.mae is None for s in stats)
    assert not any(s.chosen for s in stats)


def test_age_days_uses_vote_date_for_labeled_items():
    published = datetime.now(timezone.utc) - timedelta(days=10)
    item = ItemFeatures(
        url_hash="x",
        date_published=published,
        label=1.0,
        label_date=published + timedelta(days=2),
    )
    assert item.age_days() == pytest.approx(2.0, abs=0.01)
