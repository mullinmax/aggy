"""Vote-prediction models.

Each model learns from the user's past votes (-1..1) on items in a feed and
predicts a (score, confidence) pair for unseen items. A whole zoo of
methodologies is implemented — from a random-guessing baseline and a trivial
global mean, through classic
regressors (source averages, kNN, ridge, logistic, SVR) and tree ensembles
(random forest, gradient boosting), up to shallow and deep neural nets — and
`ranking.engine` cross-validates them all, keeps stats for each, and ranks the
feed with whichever performs best at the current amount of training data.

The heavier learners are scikit-learn estimators wrapped behind a tiny
`VoteModel` adapter, so they're the standard, well-optimized implementations
rather than hand-rolled numpy. The neural nets are `MLPRegressor`s; "deep
learning / more hidden layers" is literally a longer `hidden_layer_sizes`
tuple, which is how the shallow `neural_net` and the multi-layer
`deep_neural_net` differ. (torch was considered for the deep net, but the only
proxy-reachable wheel drags in gigabytes of unused CUDA libraries, so we keep
the image lean and let sklearn's MLP do the deep net on CPU.)

All models consume `ItemFeatures`: the article's text embedding, a separate
image (thumbnail) embedding, and scalar side information (source, author, post
age, image/media presence). The text and image embeddings occupy distinct
blocks in the design matrix, each with its own present/absent flag, so a
picture is weighed independently of the words. When a deployment has no vision
model configured the image block is simply zero-width and the has-image
presence flag carries the signal on its own.
"""

import hashlib
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, List, Optional, Sequence, Tuple

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVR

AUTHOR_BUCKETS = 8
SOURCE_BUCKETS = 16


def _bucket(text: Optional[str], buckets: int) -> Optional[int]:
    # stable across processes, unlike builtin hash() with PYTHONHASHSEED
    if not text:
        return None
    digest = hashlib.blake2b(text.encode(), digest_size=4).digest()
    return int.from_bytes(digest, "big") % buckets


@dataclass
class ItemFeatures:
    url_hash: str
    embedding: Optional[np.ndarray] = None
    image_embedding: Optional[np.ndarray] = None
    source: Optional[str] = None
    author: Optional[str] = None
    date_published: Optional[datetime] = None
    has_image: bool = False
    has_media: bool = False
    label: Optional[float] = None  # user's vote, when known
    label_date: Optional[datetime] = None

    def age_days(self, now: Optional[datetime] = None) -> Optional[float]:
        """Age of the post, measured at vote time for labeled items (what the
        user actually saw) and at `now` for candidates."""
        if self.date_published is None:
            return None
        ref = self.label_date or now or datetime.now(timezone.utc)
        published = self.date_published
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        if ref.tzinfo is None:
            ref = ref.replace(tzinfo=timezone.utc)
        return max((ref - published).total_seconds() / 86400.0, 0.0)


def _aux_vector(item: ItemFeatures, now: datetime) -> np.ndarray:
    """Scalar side-features shared by the parametric models."""
    age = item.age_days(now)
    vec = np.zeros(4 + SOURCE_BUCKETS + AUTHOR_BUCKETS)
    vec[0] = np.log1p(age) if age is not None else 0.0
    vec[1] = 1.0 if age is None else 0.0  # unknown-date flag
    vec[2] = 1.0 if item.has_image else 0.0
    vec[3] = 1.0 if item.has_media else 0.0
    s = _bucket(item.source, SOURCE_BUCKETS)
    if s is not None:
        vec[4 + s] = 1.0
    a = _bucket(item.author, AUTHOR_BUCKETS)
    if a is not None:
        vec[4 + SOURCE_BUCKETS + a] = 1.0
    return vec


def _unit_or_zeros(vector, dim: int) -> Tuple[np.ndarray, float]:
    """L2-normalize an embedding to a fixed length, or return zeros plus a
    "missing" flag when it's absent or the wrong size."""
    if vector is not None and len(vector) == dim:
        v = np.asarray(vector, dtype=float)
        norm = np.linalg.norm(v)
        if norm > 0:
            return v / norm, 1.0
    return np.zeros(dim), 0.0


def _embedding_or_zeros(item: ItemFeatures, dim: int) -> Tuple[np.ndarray, float]:
    return _unit_or_zeros(item.embedding, dim)


def _embedding_dim(items: Sequence[ItemFeatures], attr: str) -> int:
    """Length of the first present embedding of the given kind, else 0 — so a
    feed with no image embeddings simply contributes a zero-width image block."""
    for item in items:
        vec = getattr(item, attr)
        if vec is not None:
            return len(vec)
    return 0


def _design_matrix(
    items: Sequence[ItemFeatures], dim: int, image_dim: int, now: datetime
) -> np.ndarray:
    """Feature rows: [text embedding | has-text | image embedding | has-image |
    scalar side features]. Text and image occupy separate blocks, each with its
    own present/absent flag, so the model weighs the picture independently of
    the words (and of the mere has-image flag in the side features)."""
    rows = []
    for item in items:
        emb, has_emb = _embedding_or_zeros(item, dim)
        img_emb, has_img_emb = _unit_or_zeros(item.image_embedding, image_dim)
        rows.append(
            np.concatenate(
                [emb, [has_emb], img_emb, [has_img_emb], _aux_vector(item, now)]
            )
        )
    return np.asarray(rows)


class VoteModel:
    """Interface: fit on labeled items, predict (score, confidence) arrays."""

    name: str = "base"
    min_labels: int = 1
    # Whether this model may be picked to actually order the feed. A model with
    # `rankable = False` still gets cross-validated and reported in the stats UI
    # (as a yardstick to compare the real models against) but is never chosen as
    # the winner.
    rankable: bool = True

    def fit(self, items: Sequence[ItemFeatures]) -> None:
        raise NotImplementedError

    def predict(self, items: Sequence[ItemFeatures]) -> Tuple[np.ndarray, np.ndarray]:
        raise NotImplementedError


class RandomModel(VoteModel):
    """Chance baseline: ignore the features and guess a uniformly random vote in
    [-1, 1]. It learns nothing, so it's the yardstick every real model should
    beat — the stats UI shows it purely so you can see how far ahead the chosen
    model is. Never used to actually rank a feed (`rankable = False`)."""

    name = "random"
    rankable = False

    def __init__(self, seed: int = 0):
        self.seed = seed

    def fit(self, items):
        # Nothing to learn; seed a generator so the cross-validated metrics are
        # reproducible instead of jittering on every recompute.
        self.rng = np.random.default_rng(self.seed)

    def predict(self, items):
        n = len(items)
        scores = self.rng.uniform(-1.0, 1.0, n)
        return scores, np.full(n, 0.05)


class GlobalMeanModel(VoteModel):
    """Baseline: predict the mean of all votes."""

    name = "global_mean"

    def fit(self, items):
        labels = [i.label for i in items]
        self.mean = float(np.mean(labels)) if labels else 0.0

    def predict(self, items):
        n = len(items)
        return np.full(n, self.mean), np.full(n, 0.1)


class SourceMeanModel(VoteModel):
    """Mean vote per source, falling back to the global mean."""

    name = "source_mean"

    def fit(self, items):
        self.global_mean = float(np.mean([i.label for i in items])) if items else 0.0
        by_source: dict = {}
        for i in items:
            by_source.setdefault(i.source, []).append(i.label)
        self.source_means = {s: float(np.mean(v)) for s, v in by_source.items()}
        self.source_counts = {s: len(v) for s, v in by_source.items()}

    def predict(self, items):
        scores, confs = [], []
        for i in items:
            if i.source in self.source_means:
                n = self.source_counts[i.source]
                # shrink toward the global mean when a source has few votes
                w = n / (n + 3.0)
                scores.append(
                    w * self.source_means[i.source] + (1 - w) * self.global_mean
                )
                confs.append(min(0.2 + 0.1 * n, 0.8))
            else:
                scores.append(self.global_mean)
                confs.append(0.1)
        return np.asarray(scores), np.asarray(confs)


class KNNEmbeddingModel(VoteModel):
    """Similarity-weighted vote of the k most similar already-voted articles.

    With limited training data this is usually the strongest model: the
    nearest labeled post is simply the best available evidence.
    """

    name = "knn_embedding"
    min_labels = 1

    def __init__(self, k: int = 5):
        self.k = k

    def fit(self, items):
        labeled = [i for i in items if i.embedding is not None]
        self.fallback = float(np.mean([i.label for i in items])) if items else 0.0
        if not labeled:
            self.matrix = None
            return
        dim = len(labeled[0].embedding)
        rows, labels = [], []
        for i in labeled:
            emb, ok = _embedding_or_zeros(i, dim)
            if ok:
                rows.append(emb)
                labels.append(i.label)
        self.matrix = np.asarray(rows) if rows else None
        self.labels = np.asarray(labels) if rows else None
        self.dim = dim

    def predict(self, items):
        scores, confs = [], []
        for item in items:
            if self.matrix is None or item.embedding is None:
                scores.append(self.fallback)
                confs.append(0.05)
                continue
            emb, ok = _embedding_or_zeros(item, self.dim)
            if not ok:
                scores.append(self.fallback)
                confs.append(0.05)
                continue
            sims = self.matrix @ emb  # rows are unit vectors
            k = min(self.k, len(sims))
            top = np.argsort(sims)[-k:]
            top_sims = np.clip(sims[top], 0.0, None)
            top_labels = self.labels[top]
            if top_sims.sum() <= 1e-9:
                scores.append(self.fallback)
                confs.append(0.05)
                continue
            weights = top_sims / top_sims.sum()
            pred = float(np.dot(weights, top_labels))
            # confident when neighbors are close AND agree with each other
            agreement = 1.0 - float(np.dot(weights, np.abs(top_labels - pred))) / 2.0
            confs.append(float(np.clip(top_sims.max() * agreement, 0.0, 1.0)))
            scores.append(pred)
        return np.asarray(scores), np.asarray(confs)


class _SklearnModel(VoteModel):
    """Adapter: build the design matrix, fit a scikit-learn regressor (behind a
    StandardScaler when the estimator is scale-sensitive), and turn its output
    into a clipped (score, confidence) pair. Subclasses just supply
    `_build_estimator` plus `name`/`min_labels`.

    Confidence is a monotone function of |score|: a prediction near the
    extremes reads as a confident like/dislike, one near zero as a shrug. It's
    a display signal for the "most certain" sort, not a calibrated probability.
    """

    use_scaler = True

    def _build_estimator(self):
        raise NotImplementedError

    def _dim(self, items):
        return _embedding_dim(items, "embedding")

    def fit(self, items):
        self.now = datetime.now(timezone.utc)
        self.dim = self._dim(items)
        self.image_dim = _embedding_dim(items, "image_embedding")
        X = _design_matrix(items, self.dim, self.image_dim, self.now)
        y = np.asarray([i.label for i in items], dtype=float)
        estimator = self._build_estimator()
        self.model = (
            make_pipeline(StandardScaler(), estimator) if self.use_scaler else estimator
        )
        self.model.fit(X, y)

    def predict(self, items):
        X = _design_matrix(items, self.dim, self.image_dim, self.now)
        scores = np.clip(self.model.predict(X), -1.0, 1.0)
        confs = np.clip(0.1 + 0.8 * np.abs(scores), 0.0, 1.0)
        return scores, confs


class RidgeModel(_SklearnModel):
    """L2-regularized linear regression on [embedding | side features]."""

    name = "ridge"
    min_labels = 5

    def __init__(self, alpha: float = 10.0):
        self.alpha = alpha

    def _build_estimator(self):
        return Ridge(alpha=self.alpha)


class SVRModel(_SklearnModel):
    """Support-vector regression with an RBF kernel: a non-linear model that
    stays well-behaved on modest data and captures smooth structure the linear
    models can't."""

    name = "svr"
    min_labels = 12

    def __init__(self, C: float = 1.0, epsilon: float = 0.1, gamma: str = "scale"):
        self.C = C
        self.epsilon = epsilon
        self.gamma = gamma

    def _build_estimator(self):
        return SVR(kernel="rbf", C=self.C, epsilon=self.epsilon, gamma=self.gamma)


class RandomForestModel(_SklearnModel):
    """Bagged regression trees over [embedding | side features]. Robust with
    modest data and captures non-linear, feature-interaction structure the
    linear models miss. Trees are scale-invariant, so no scaler."""

    name = "random_forest"
    # above the leave-one-out CV cutoff (40) so it always evaluates with cheap
    # 5-fold; with few votes the simpler models (kNN especially) already win.
    min_labels = 45
    use_scaler = False

    def __init__(
        self, n_trees: int = 200, max_depth: Optional[int] = None, seed: int = 0
    ):
        self.n_trees = n_trees
        self.max_depth = max_depth
        self.seed = seed

    def _build_estimator(self):
        return RandomForestRegressor(
            n_estimators=self.n_trees,
            max_depth=self.max_depth,
            min_samples_leaf=1,
            random_state=self.seed,
            n_jobs=1,
        )


class GradientBoostModel(_SklearnModel):
    """Histogram gradient boosting: additive shallow trees on the loss
    gradient. Usually the strongest tree model once the feed is well-labeled.
    Scale-invariant, so no scaler."""

    name = "gradient_boost"
    min_labels = 45
    use_scaler = False

    def __init__(
        self,
        max_iter: int = 200,
        learning_rate: float = 0.1,
        max_leaf_nodes: int = 15,
        seed: int = 0,
    ):
        self.max_iter = max_iter
        self.learning_rate = learning_rate
        self.max_leaf_nodes = max_leaf_nodes
        self.seed = seed

    def _build_estimator(self):
        return HistGradientBoostingRegressor(
            max_iter=self.max_iter,
            learning_rate=self.learning_rate,
            max_leaf_nodes=self.max_leaf_nodes,
            l2_regularization=1.0,
            random_state=self.seed,
        )


class _MLPModel(_SklearnModel):
    """Shared plumbing for the neural-net models. `hidden` is the
    `hidden_layer_sizes` tuple — one entry per hidden layer — so a deeper net
    is just a longer tuple. Accepts a bare int for a single hidden layer."""

    activation = "relu"
    default_hidden: Sequence[int] = (64,)
    default_epochs = 500
    default_alpha = 1e-3
    learning_rate = 0.01
    use_scaler = True

    def __init__(self, hidden=None, epochs=None, alpha=None, seed: int = 0):
        chosen = self.default_hidden if hidden is None else hidden
        self.hidden = (chosen,) if isinstance(chosen, int) else tuple(chosen)
        self.epochs = epochs if epochs is not None else self.default_epochs
        self.alpha = alpha if alpha is not None else self.default_alpha
        self.seed = seed

    def _build_estimator(self):
        return MLPRegressor(
            hidden_layer_sizes=tuple(self.hidden),
            activation=self.activation,
            solver="adam",
            alpha=self.alpha,
            learning_rate_init=self.learning_rate,
            max_iter=self.epochs,
            random_state=self.seed,
        )

    def fit(self, items):
        # Not fully converging on a small feed is expected and harmless (the
        # cross-validated MAE decides whether the net competes at all), so we
        # don't want ConvergenceWarning spamming the ranking job's logs.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=ConvergenceWarning)
            super().fit(items)


class MLPModel(_MLPModel):
    """Shallow one-hidden-layer net. Eligible once there's enough data for it
    to beat the simpler models honestly."""

    name = "neural_net"
    min_labels = 20
    default_hidden = (64,)


class DeepMLPModel(_MLPModel):
    """A genuinely deep net: four ReLU hidden layers over the embedding plus
    side features, with stronger weight decay. Needs a good number of votes
    before it stops overfitting, so it only enters the contest once the feed is
    well-labeled (also keeping it above the leave-one-out CV cutoff) — at which
    point it can capture interactions the shallow net and the linear models
    can't."""

    name = "deep_neural_net"
    min_labels = 50
    default_hidden = (256, 128, 64, 32)
    default_epochs = 800
    default_alpha = 1e-2


class LogisticVoteModel(VoteModel):
    """Logistic regression on [embedding | side features]. Learns the
    probability that an article is upvoted and maps it back to a [-1, 1]
    score, so — unlike ridge — it saturates rather than extrapolating wildly
    on far-out embeddings."""

    name = "logistic"
    min_labels = 8

    def __init__(self, C: float = 1.0):
        self.C = C

    def _dim(self, items):
        return _embedding_dim(items, "embedding")

    def fit(self, items):
        self.now = datetime.now(timezone.utc)
        self.dim = self._dim(items)
        self.image_dim = _embedding_dim(items, "image_embedding")
        X = _design_matrix(items, self.dim, self.image_dim, self.now)
        labels = np.asarray([i.label for i in items], dtype=float)
        self.scaler = StandardScaler().fit(X)
        Xs = self.scaler.transform(X)
        y = (labels > 0).astype(int)  # "did the user react positively?"
        # a single observed class can't train a classifier; fall back to a
        # constant prediction of the mean vote in that (degenerate) case.
        if len(np.unique(y)) < 2:
            self.clf = None
            self.constant = float(np.clip(np.mean(labels), -1.0, 1.0))
            return
        self.clf = LogisticRegression(C=self.C, max_iter=1000).fit(Xs, y)

    def predict(self, items):
        X = _design_matrix(items, self.dim, self.image_dim, self.now)
        if self.clf is None:
            scores = np.full(len(items), self.constant)
            return scores, np.full(len(items), 0.1)
        p = self.clf.predict_proba(self.scaler.transform(X))[:, 1]
        scores = np.clip(2.0 * p - 1.0, -1.0, 1.0)
        confs = np.clip(0.1 + 0.8 * np.abs(scores), 0.0, 1.0)
        return scores, confs


def all_models() -> List[VoteModel]:
    """The full model zoo, cheap-and-simple first. `evaluate_models` runs each
    eligible one and the best MAE wins, so adding a model here just gives the
    feed another candidate — it never hurts a well-labeled feed and quietly
    sits out (null metrics) until it has enough votes to compete."""
    return [
        RandomModel(),
        GlobalMeanModel(),
        SourceMeanModel(),
        KNNEmbeddingModel(),
        RidgeModel(),
        LogisticVoteModel(),
        SVRModel(),
        RandomForestModel(),
        GradientBoostModel(),
        MLPModel(),
        DeepMLPModel(),
    ]


@dataclass
class ModelStats:
    model_name: str
    n_labels: int
    mae: Optional[float] = None
    rmse: Optional[float] = None
    sign_accuracy: Optional[float] = None
    chosen: bool = False
    extra: dict = field(default_factory=dict)


def evaluate_models(
    labeled: Sequence[ItemFeatures],
    models: Optional[List[VoteModel]] = None,
    on_model: Optional[Callable[[int, int, str], None]] = None,
) -> List[ModelStats]:
    """Cross-validate every eligible model on the labeled items.

    Uses leave-one-out below 40 labels (make the most of scarce votes),
    5-fold above. Models whose `min_labels` isn't met are reported with null
    metrics so the stats UI can show why they're not competing yet.

    `on_model(index, total, model_name)` is called as each model comes up, so
    a caller can report which one is training — this is the slow part of a
    retrain, and the progress bar in the UI is driven from here.
    """
    models = models if models is not None else all_models()
    n = len(labeled)
    results: List[ModelStats] = []

    for index, model in enumerate(models):
        if on_model is not None:
            on_model(index, len(models), model.name)
        if n < max(model.min_labels, 2):
            results.append(ModelStats(model_name=model.name, n_labels=n))
            continue

        indices = np.arange(n)
        folds = (
            [np.array([i]) for i in indices]
            if n <= 40
            else np.array_split(np.random.default_rng(0).permutation(indices), 5)
        )

        preds = np.zeros(n)
        try:
            for fold in folds:
                if len(fold) == 0:
                    continue
                train = [labeled[i] for i in indices if i not in set(fold)]
                test = [labeled[i] for i in fold]
                model.fit(train)
                scores, _ = model.predict(test)
                preds[fold] = scores
        except Exception:
            results.append(ModelStats(model_name=model.name, n_labels=n))
            continue

        actual = np.asarray([i.label for i in labeled])
        errors = np.abs(preds - actual)
        nonzero = actual != 0
        sign_acc = (
            float(np.mean(np.sign(preds[nonzero]) == np.sign(actual[nonzero])))
            if nonzero.any()
            else None
        )
        results.append(
            ModelStats(
                model_name=model.name,
                n_labels=n,
                mae=float(errors.mean()),
                rmse=float(np.sqrt((errors**2).mean())),
                sign_accuracy=sign_acc,
            )
        )

    # pick the winner: lowest MAE among models that both produced metrics and
    # are allowed to rank (the random baseline is reported but never chosen)
    rankable = {m.name for m in models if m.rankable}
    scored = [r for r in results if r.mae is not None and r.model_name in rankable]
    if scored:
        best = min(scored, key=lambda r: r.mae)
        best.chosen = True
    return results


def best_model(stats: List[ModelStats]) -> Optional[str]:
    for s in stats:
        if s.chosen:
            return s.model_name
    return None
