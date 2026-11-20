"""Candidate prediction methods that are not (yet) in the live model zoo.

Each is a `VoteModel`, so anything that proves itself in a replay can be moved
into `ranking.models.all_models` unchanged. Three extra attributes tell the
replay harness how to treat a method:

`calibrated` -- its scores are meant to be read on the vote scale (-1..1). A
method that only produces an ordering (a similarity, a margin) sets this False
and is scored on ranking metrics alone; an error in "votes" would be
meaningless for it.

`scope` -- "feed" methods learn from the feed being replayed. "account" methods
learn from the votes of every feed the account has, which is the point of them:
a small feed borrowing from a large one.

`heavy` -- slow enough to leave out of a quick run.

The goal every one of these is judged against is the same: put the articles
that will be upvoted first.
"""

from datetime import datetime, timezone
from typing import List, Optional, Sequence, Tuple

import numpy as np
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.preprocessing import StandardScaler

from ranking.models import (
    ItemFeatures,
    KNNEmbeddingModel,
    LogisticVoteModel,
    RidgeModel,
    VoteModel,
    _design_matrix,
    _embedding_dim,
    _unit_or_zeros,
)

from . import metrics


def _labels(items: Sequence[ItemFeatures]) -> np.ndarray:
    return np.asarray([float(i.label) for i in items], dtype=float)


def _unit_embeddings(
    items: Sequence[ItemFeatures], dim: int
) -> Tuple[np.ndarray, np.ndarray]:
    """Unit text embeddings as rows, and a mask of which rows have one."""
    rows = np.zeros((len(items), dim))
    present = np.zeros(len(items), dtype=bool)
    for index, item in enumerate(items):
        vector, ok = _unit_or_zeros(item.embedding, dim)
        rows[index] = vector
        present[index] = bool(ok)
    return rows, present


def _as_utc(moment: Optional[datetime]) -> Optional[datetime]:
    if moment is not None and moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment


def _recency_weights(items: Sequence[ItemFeatures], half_life_days: float):
    """Weight per item that halves for every `half_life_days` between its vote
    and the newest vote in the set. An undated vote is treated as the oldest."""
    dates = [_as_utc(i.label_date) for i in items]
    known = [d for d in dates if d is not None]
    if not known:
        return np.ones(len(items))
    newest, oldest = max(known), min(known)
    ages = np.asarray(
        [((newest - (d or oldest)).total_seconds()) / 86400.0 for d in dates]
    )
    return np.power(0.5, ages / half_life_days)


def _score_from_probability(p: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    scores = np.clip(2.0 * p - 1.0, -1.0, 1.0)
    return scores, np.clip(0.1 + 0.8 * np.abs(scores), 0.0, 1.0)


class ExperimentModel(VoteModel):
    calibrated = True
    scope = "feed"
    heavy = False


# ---------------------------------------------------------------------------
# sanity baseline


class NewestFirstModel(ExperimentModel):
    """No learning at all: the newer the article, the higher it ranks.

    A yardstick like the random model. If a learned method cannot beat simply
    reading the feed in date order, it is not earning its keep."""

    name = "newest_first"
    calibrated = False
    rankable = False

    def fit(self, items):
        pass

    def predict(self, items):
        ages = np.asarray([i.age_days() for i in items], dtype=object)
        known = [a for a in ages if a is not None]
        worst = (max(known) if known else 0.0) + 1.0
        scores = -np.asarray([worst if a is None else a for a in ages], dtype=float)
        return scores, np.full(len(items), 0.05)


# ---------------------------------------------------------------------------
# embedding profiles


class TasteProfileModel(ExperimentModel):
    """One vector for what you upvote and one for what you do not.

    The average embedding of the upvoted articles, and the average of the rest;
    an article scores by how much closer it sits to the first than the second.
    The textbook relevance-feedback profile: nothing to tune, nothing to
    overfit, and it works from the first handful of votes."""

    name = "taste_profile"
    min_labels = 4
    calibrated = False

    def fit(self, items):
        self.dim = _embedding_dim(items, "embedding")
        self.liked = self.other = None
        if not self.dim:
            return
        rows, present = _unit_embeddings(items, self.dim)
        up = metrics.is_upvote(_labels(items)) & present
        rest = ~metrics.is_upvote(_labels(items)) & present
        if up.any():
            self.liked = rows[up].mean(axis=0)
        if rest.any():
            self.other = rows[rest].mean(axis=0)

    def predict(self, items):
        scores = np.zeros(len(items))
        if self.dim:
            rows, _ = _unit_embeddings(items, self.dim)
            if self.liked is not None:
                scores += rows @ self.liked
            if self.other is not None:
                scores -= rows @ self.other
        return scores, np.full(len(items), 0.3)


class MultiInterestModel(ExperimentModel):
    """Several taste vectors instead of one.

    A single average blurs unrelated interests into a point that is close to
    none of them. This clusters the upvoted articles into a few groups (and the
    rest into a few more) and scores an article by its closest liked group
    against its closest not-liked group."""

    name = "multi_interest"
    min_labels = 16
    calibrated = False

    def __init__(self, per_cluster: int = 8, max_clusters: int = 6, seed: int = 0):
        self.per_cluster = per_cluster
        self.max_clusters = max_clusters
        self.seed = seed

    def _centres(self, rows: np.ndarray) -> Optional[np.ndarray]:
        if len(rows) == 0:
            return None
        k = int(np.clip(len(rows) // self.per_cluster, 1, self.max_clusters))
        if k == 1:
            centres = rows.mean(axis=0, keepdims=True)
        else:
            centres = (
                KMeans(n_clusters=k, n_init=3, random_state=self.seed)
                .fit(rows)
                .cluster_centers_
            )
        norms = np.linalg.norm(centres, axis=1, keepdims=True)
        return centres / np.where(norms > 0, norms, 1.0)

    def fit(self, items):
        self.dim = _embedding_dim(items, "embedding")
        self.liked = self.other = None
        if not self.dim:
            return
        rows, present = _unit_embeddings(items, self.dim)
        up = metrics.is_upvote(_labels(items))
        self.liked = self._centres(rows[up & present])
        self.other = self._centres(rows[~up & present])

    def predict(self, items):
        scores = np.zeros(len(items))
        if self.dim:
            rows, _ = _unit_embeddings(items, self.dim)
            if self.liked is not None:
                scores += (rows @ self.liked.T).max(axis=1)
            if self.other is not None:
                scores -= (rows @ self.other.T).max(axis=1)
        return scores, np.full(len(items), 0.3)


# ---------------------------------------------------------------------------
# recency


class RecentKNNModel(ExperimentModel):
    """Nearest voted articles, with recent votes counting for more.

    The live kNN treats a vote from last year exactly like one from yesterday.
    Here a neighbour's say is its similarity times a weight that halves every
    `half_life_days`, so the model follows a taste that moves."""

    def __init__(self, half_life_days: float = 30.0, k: int = 10):
        self.half_life_days = half_life_days
        self.k = k
        self.name = f"knn_recent_{int(half_life_days)}d"

    def fit(self, items):
        self.dim = _embedding_dim(items, "embedding")
        labels = _labels(items)
        self.fallback = float(labels.mean()) if len(labels) else 0.0
        self.matrix = None
        if not self.dim:
            return
        rows, present = _unit_embeddings(items, self.dim)
        if not present.any():
            return
        self.matrix = rows[present]
        self.labels = labels[present]
        self.weights = _recency_weights(items, self.half_life_days)[present]

    def predict(self, items):
        scores = np.full(len(items), self.fallback)
        confs = np.full(len(items), 0.05)
        if self.matrix is None:
            return scores, confs
        rows, present = _unit_embeddings(items, self.dim)
        k = min(self.k, len(self.labels))
        for index in np.flatnonzero(present):
            sims = self.matrix @ rows[index]
            top = np.argpartition(sims, -k)[-k:]
            weights = np.clip(sims[top], 0.0, None) * self.weights[top]
            if weights.sum() <= 1e-9:
                continue
            scores[index] = float(np.dot(weights, self.labels[top]) / weights.sum())
            confs[index] = float(np.clip(sims[top].max(), 0.0, 1.0))
        return scores, confs


class _MatrixModel(ExperimentModel):
    """Shared plumbing for methods that learn from the same design matrix the
    live sklearn models use (embeddings, side features, neighbour votes)."""

    use_neighbors = True

    def _prepare(self, items) -> np.ndarray:
        self.now = datetime.now(timezone.utc)
        self.dim = _embedding_dim(items, "embedding")
        self.image_dim = _embedding_dim(items, "image_embedding")
        # the fitted set's own votes only, exactly as in ranking.models: a
        # held-out article's label must not reach the features predicting it
        self.neighbor_labels = (
            {i.url_hash: float(i.label) for i in items if i.label is not None}
            if self.use_neighbors
            else None
        )
        return self._matrix(items)

    def _matrix(self, items) -> np.ndarray:
        return _design_matrix(
            items, self.dim, self.image_dim, self.now, self.neighbor_labels
        )


class RecentRidgeModel(_MatrixModel):
    """The live ridge regression, with recent votes weighted more heavily."""

    min_labels = 5

    def __init__(self, half_life_days: float = 30.0, alpha: float = 10.0):
        self.half_life_days = half_life_days
        self.alpha = alpha
        self.name = f"ridge_recent_{int(half_life_days)}d"

    def fit(self, items):
        X = self._prepare(items)
        weights = _recency_weights(items, self.half_life_days)
        self.scaler = StandardScaler().fit(X)
        self.model = Ridge(alpha=self.alpha).fit(
            self.scaler.transform(X), _labels(items), sample_weight=weights
        )

    def predict(self, items):
        raw = self.model.predict(self.scaler.transform(self._matrix(items)))
        scores = np.clip(raw, -1.0, 1.0)
        return scores, np.clip(0.1 + 0.8 * np.abs(scores), 0.0, 1.0)


# ---------------------------------------------------------------------------
# classifiers: predict the upvote itself rather than a number on the vote scale


class _UpvoteClassifier(_MatrixModel):
    """Learn "will this be upvoted?" directly, and rank by that probability."""

    def _build(self):
        raise NotImplementedError

    def _transform_fit(self, X: np.ndarray) -> np.ndarray:
        self.scaler = StandardScaler().fit(X)
        return self.scaler.transform(X)

    def _transform(self, X: np.ndarray) -> np.ndarray:
        return self.scaler.transform(X)

    def fit(self, items):
        X = self._transform_fit(self._prepare(items))
        y = metrics.is_upvote(_labels(items)).astype(int)
        # one class cannot train a classifier; predict its rate instead
        if len(np.unique(y)) < 2:
            self.clf = None
            self.constant = float(y.mean())
            return
        self.clf = self._build().fit(X, y)

    def predict(self, items):
        if self.clf is None:
            return _score_from_probability(np.full(len(items), self.constant))
        X = self._transform(self._matrix(items))
        return _score_from_probability(self.clf.predict_proba(X)[:, 1])


class LogisticNeighborsModel(_UpvoteClassifier):
    """The live logistic model, plus the neighbour-vote features.

    Every other matrix model in the zoo is told how you voted on an article's
    nearest neighbours. The logistic one never was. This is that model with the
    gap closed, to see whether it mattered."""

    name = "logistic_neighbors"
    min_labels = 8

    def _build(self):
        return LogisticRegression(C=1.0, max_iter=1000)


class PCALogisticModel(_UpvoteClassifier):
    """Logistic regression on a compressed embedding.

    A text embedding has hundreds of dimensions and a feed has far fewer votes,
    so a linear model on the raw vector mostly fits noise. Projecting onto the
    few directions the voted articles actually vary along first leaves it far
    fewer ways to be wrong."""

    name = "pca_logistic"
    min_labels = 12

    def __init__(self, components: int = 24):
        self.components = components

    def _build(self):
        return LogisticRegression(C=1.0, max_iter=1000)

    def _split(self, X: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        return X[:, : self.dim], X[:, self.dim :]

    def _transform_fit(self, X):
        text, rest = self._split(X)
        k = int(min(self.components, text.shape[1], max(len(X) - 1, 0)))
        self.pca = PCA(n_components=k, random_state=0).fit(text) if k >= 1 else None
        reduced = self.pca.transform(text) if self.pca is not None else text[:, :0]
        self.scaler = StandardScaler().fit(np.hstack([reduced, rest]))
        return self.scaler.transform(np.hstack([reduced, rest]))

    def _transform(self, X):
        text, rest = self._split(X)
        reduced = self.pca.transform(text) if self.pca is not None else text[:, :0]
        return self.scaler.transform(np.hstack([reduced, rest]))


class GradientBoostClassifierModel(_UpvoteClassifier):
    """Gradient-boosted trees asked the actual question (upvote or not) rather
    than asked to regress a vote and hoping the order comes out right."""

    name = "gradient_boost_upvote"
    min_labels = 45
    heavy = True

    def _transform_fit(self, X):
        return X  # trees are scale-invariant

    def _transform(self, X):
        return X

    def _build(self):
        return HistGradientBoostingClassifier(
            max_iter=150,
            learning_rate=0.1,
            max_leaf_nodes=15,
            l2_regularization=1.0,
            random_state=0,
        )


class ThreeWayModel(_MatrixModel):
    """Up, neutral and down as three separate outcomes.

    Regression treats "meh" as halfway between a downvote and an upvote. It may
    not be: an article can be unlike both. This predicts a probability for each
    and scores an article by P(up) minus P(down)."""

    name = "three_way"
    min_labels = 12

    def fit(self, items):
        X = self._prepare(items)
        self.scaler = StandardScaler().fit(X)
        labels = _labels(items)
        y = np.sign(labels).astype(int)
        if len(np.unique(y)) < 2:
            self.clf = None
            self.constant = float(np.clip(labels.mean(), -1.0, 1.0))
            return
        self.clf = LogisticRegression(C=1.0, max_iter=1000).fit(
            self.scaler.transform(X), y
        )

    def predict(self, items):
        if self.clf is None:
            scores = np.full(len(items), self.constant)
            return scores, np.full(len(items), 0.1)
        p = self.clf.predict_proba(self.scaler.transform(self._matrix(items)))
        classes = list(self.clf.classes_)
        up = p[:, classes.index(1)] if 1 in classes else 0.0
        down = p[:, classes.index(-1)] if -1 in classes else 0.0
        scores = np.clip(up - down, -1.0, 1.0)
        return scores, np.clip(p.max(axis=1), 0.0, 1.0)


class PairwiseRankerModel(_MatrixModel):
    """Learn the order, not the score.

    Trained on pairs of one upvoted article and one that was not: which of the
    two should rank higher? That is a linear classifier on the difference of
    their features, and its weights score a single article. The loss it
    minimises is the number of misordered pairs, which is the ranking AUC the
    experiments are scored on."""

    name = "pairwise_ranker"
    min_labels = 12
    calibrated = False

    def __init__(self, max_pairs: int = 3000, seed: int = 0):
        self.max_pairs = max_pairs
        self.seed = seed

    def fit(self, items):
        X = self._prepare(items)
        self.scaler = StandardScaler().fit(X)
        Xs = self.scaler.transform(X)
        up = np.flatnonzero(metrics.is_upvote(_labels(items)))
        rest = np.flatnonzero(~metrics.is_upvote(_labels(items)))
        self.weights = None
        if len(up) == 0 or len(rest) == 0:
            return
        rng = np.random.default_rng(self.seed)
        n_pairs = int(min(self.max_pairs, len(up) * len(rest)))
        winners = rng.choice(up, n_pairs)
        losers = rng.choice(rest, n_pairs)
        diffs = Xs[winners] - Xs[losers]
        # each pair is seen from both sides, so the classes are balanced and
        # the boundary passes through the origin (hence no intercept)
        flip = rng.random(n_pairs) < 0.5
        diffs[flip] *= -1.0
        clf = LogisticRegression(C=0.1, max_iter=500, fit_intercept=False)
        self.weights = clf.fit(diffs, (~flip).astype(int)).coef_[0]

    def predict(self, items):
        if self.weights is None:
            return np.zeros(len(items)), np.full(len(items), 0.05)
        scores = self.scaler.transform(self._matrix(items)) @ self.weights
        return scores, np.full(len(items), 0.3)


# ---------------------------------------------------------------------------
# priors


class SourcePriorKNNModel(ExperimentModel):
    """What you think of the source and the author, corrected by content.

    Starts from an average vote per source, shrunk toward the overall average
    when a source has few votes, then does the same for the author with what
    the source left unexplained. Whatever is still unexplained is predicted
    from the nearest voted articles. The live models see source and author only
    as hashed buckets, which collide once a feed has more than a few of them."""

    name = "source_prior_knn"
    min_labels = 6

    def __init__(self, shrink: float = 5.0, k: int = 10):
        self.shrink = shrink
        self.k = k

    def _shrunk(self, keys, values) -> dict:
        grouped: dict = {}
        for key, value in zip(keys, values):
            if key:
                grouped.setdefault(key, []).append(value)
        return {
            key: float(np.sum(v) / (len(v) + self.shrink)) for key, v in grouped.items()
        }

    def _prior(self, items) -> np.ndarray:
        return np.asarray(
            [
                self.mean
                + self.by_source.get(i.source, 0.0)
                + self.by_author.get(i.author, 0.0)
                for i in items
            ]
        )

    def fit(self, items):
        labels = _labels(items)
        self.mean = float(labels.mean()) if len(labels) else 0.0
        self.by_source = self._shrunk([i.source for i in items], labels - self.mean)
        after_source = labels - np.asarray(
            [self.mean + self.by_source.get(i.source, 0.0) for i in items]
        )
        self.by_author = self._shrunk([i.author for i in items], after_source)
        residual = labels - self._prior(items)
        self.dim = _embedding_dim(items, "embedding")
        self.matrix = None
        if self.dim:
            rows, present = _unit_embeddings(items, self.dim)
            if present.any():
                self.matrix = rows[present]
                self.residual = residual[present]

    def predict(self, items):
        scores = self._prior(items)
        if self.matrix is not None:
            rows, present = _unit_embeddings(items, self.dim)
            k = min(self.k, len(self.residual))
            for index in np.flatnonzero(present):
                sims = self.matrix @ rows[index]
                top = np.argpartition(sims, -k)[-k:]
                weights = np.clip(sims[top], 0.0, None)
                total = weights.sum()
                if total <= 1e-9:
                    continue
                # trust the correction more the closer and more numerous the
                # neighbours it came from
                trust = total / (total + 1.0)
                scores[index] += (
                    trust * float(np.dot(weights, self.residual[top])) / total
                )
        scores = np.clip(scores, -1.0, 1.0)
        return scores, np.clip(0.1 + 0.8 * np.abs(scores), 0.0, 1.0)


# ---------------------------------------------------------------------------
# tuning


def _time_split(items: Sequence[ItemFeatures], holdout: float = 0.25):
    """The newest quarter of the votes as a validation set, the rest to fit on.
    The same forward-in-time split the replay itself uses, one level down."""
    ordered = sorted(
        items,
        key=lambda i: (
            _as_utc(i.label_date) or datetime.min.replace(tzinfo=timezone.utc)
        ),
    )
    cut = int(round(len(ordered) * (1.0 - holdout)))
    return ordered[:cut], ordered[cut:]


class _TunedModel(ExperimentModel):
    """Pick one setting on an inner forward-in-time split, then fit on all.

    The live models run with settings chosen once, by hand, for no feed in
    particular. This asks the feed's own history which value orders its newest
    votes best."""

    candidates: Sequence[float] = ()

    def _make(self, value) -> VoteModel:
        raise NotImplementedError

    def fit(self, items):
        self.chosen = self.candidates[len(self.candidates) // 2]
        earlier, newest = _time_split(items)
        if len(earlier) >= 8 and len(newest) >= 4:
            actual = _labels(newest)
            best = None
            for value in self.candidates:
                try:
                    model = self._make(value)
                    model.fit(earlier)
                    predicted, _ = model.predict(newest)
                except Exception:
                    continue
                quality = metrics.auc(predicted, actual)
                if quality is None:
                    quality = -metrics.mae(predicted, actual)
                if best is None or quality > best:
                    best, self.chosen = quality, value
        self.model = self._make(self.chosen)
        self.model.fit(items)

    def predict(self, items):
        return self.model.predict(items)


class TunedKNNModel(_TunedModel):
    name = "knn_tuned"
    min_labels = 16
    candidates = (3, 5, 10, 20, 40)

    def _make(self, value):
        return KNNEmbeddingModel(k=int(value))


class TunedRidgeModel(_TunedModel):
    name = "ridge_tuned"
    min_labels = 16
    candidates = (1.0, 10.0, 100.0, 1000.0)

    def _make(self, value):
        return RidgeModel(alpha=float(value))


# ---------------------------------------------------------------------------
# account-wide: the same models, fitted on the votes of every feed you have


class AccountKNNModel(KNNEmbeddingModel):
    name = "account_knn"
    scope = "account"
    calibrated = True
    heavy = False


class AccountRidgeModel(RidgeModel):
    name = "account_ridge"
    scope = "account"
    calibrated = True
    heavy = False


class AccountLogisticModel(LogisticVoteModel):
    name = "account_logistic"
    scope = "account"
    calibrated = True
    heavy = False


# ---------------------------------------------------------------------------
# opens: articles you opened and never voted on, read as a quiet "neutral"


class OpensAsNeutralModel(ExperimentModel):
    """kNN that also learns from articles you opened and left unvoted.

    Most of what you look at never gets a vote, and "looked, did not upvote"
    is evidence of a kind. The replay hands this model those articles (via
    `extra_items`, labelled 0) on top of the real votes. It needs opens to
    have been recorded for a while before it can say anything; until then it
    is reported as not having enough data."""

    name = "opens_as_neutral_knn"
    uses_opens = True
    min_opens = 20

    def __init__(self, k: int = 5):
        self.model = KNNEmbeddingModel(k=k)
        self.extra_items: List[ItemFeatures] = []

    def fit(self, items):
        self.model.fit(list(items) + list(self.extra_items))

    def predict(self, items):
        return self.model.predict(items)


def experiment_models() -> List[VoteModel]:
    """Every new candidate, cheapest first. The live zoo is added by the
    replay harness, which also builds the methods that combine other methods
    (the pickers and the blends)."""
    return [
        NewestFirstModel(),
        TasteProfileModel(),
        MultiInterestModel(),
        RecentKNNModel(30.0),
        RecentRidgeModel(7.0),
        RecentRidgeModel(30.0),
        RecentRidgeModel(90.0),
        LogisticNeighborsModel(),
        PCALogisticModel(),
        ThreeWayModel(),
        PairwiseRankerModel(),
        SourcePriorKNNModel(),
        TunedKNNModel(),
        TunedRidgeModel(),
        AccountKNNModel(),
        AccountRidgeModel(),
        AccountLogisticModel(),
        GradientBoostClassifierModel(),
        OpensAsNeutralModel(),
    ]
