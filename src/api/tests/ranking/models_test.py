"""Pure-python tests for the vote-prediction models (no database)."""

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from ranking.models import (
    GlobalMeanModel,
    ItemFeatures,
    KNNEmbeddingModel,
    MLPModel,
    RidgeModel,
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


def test_mlp_learns_direction():
    items = two_cluster_data(n=40)
    model = MLPModel(epochs=200)
    model.fit(items)
    scores, _ = model.predict(
        [
            make_item(100, [5, 0, 0, 0, 0, 0, 0, 0]),
            make_item(101, [-5, 0, 0, 0, 0, 0, 0, 0]),
        ]
    )
    assert scores[0] > 0 > scores[1]


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
