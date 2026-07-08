"""Vote-prediction models.

Each model learns from the user's past votes (-1..1) on items in a feed and
predicts a (score, confidence) pair for unseen items. Several methodologies
are implemented — from a trivial global mean up to a small neural net — and
`ranking.engine` cross-validates them all, keeps stats for each, and ranks the
feed with whichever performs best at the current amount of training data.

All models consume `ItemFeatures`: the article's text embedding plus scalar
side information (source, author, post age, media presence). Image/thumbnail
embeddings slot into the same structure once image embedding ingestion lands;
until then a has-image flag stands in.
"""

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional, Sequence, Tuple

import numpy as np

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


def _embedding_or_zeros(item: ItemFeatures, dim: int) -> Tuple[np.ndarray, float]:
    if item.embedding is not None and len(item.embedding) == dim:
        v = np.asarray(item.embedding, dtype=float)
        norm = np.linalg.norm(v)
        if norm > 0:
            return v / norm, 1.0
    return np.zeros(dim), 0.0


def _design_matrix(
    items: Sequence[ItemFeatures], dim: int, now: datetime
) -> np.ndarray:
    rows = []
    for item in items:
        emb, has_emb = _embedding_or_zeros(item, dim)
        rows.append(np.concatenate([emb, [has_emb], _aux_vector(item, now)]))
    return np.asarray(rows)


class VoteModel:
    """Interface: fit on labeled items, predict (score, confidence) arrays."""

    name: str = "base"
    min_labels: int = 1

    def fit(self, items: Sequence[ItemFeatures]) -> None:
        raise NotImplementedError

    def predict(self, items: Sequence[ItemFeatures]) -> Tuple[np.ndarray, np.ndarray]:
        raise NotImplementedError


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


class RidgeModel(VoteModel):
    """L2-regularized linear regression on [embedding | side features]."""

    name = "ridge"
    min_labels = 5

    def __init__(self, alpha: float = 10.0):
        self.alpha = alpha

    def _dim(self, items):
        for i in items:
            if i.embedding is not None:
                return len(i.embedding)
        return 0

    def fit(self, items):
        self.now = datetime.now(timezone.utc)
        self.dim = self._dim(items)
        self.mean = float(np.mean([i.label for i in items])) if items else 0.0
        X = _design_matrix(items, self.dim, self.now)
        y = np.asarray([i.label for i in items]) - self.mean
        # closed-form ridge: (X'X + aI)^-1 X'y
        n_feat = X.shape[1]
        self.weights = np.linalg.solve(X.T @ X + self.alpha * np.eye(n_feat), X.T @ y)

    def predict(self, items):
        X = _design_matrix(items, self.dim, self.now)
        raw = X @ self.weights + self.mean
        scores = np.clip(raw, -1.0, 1.0)
        confs = np.clip(np.abs(scores) * 0.8 + 0.1, 0.0, 1.0)
        return scores, confs


class MLPModel(VoteModel):
    """Tiny two-layer neural net (numpy, full-batch Adam). Only eligible once
    there's enough data for it to beat the simpler models honestly."""

    name = "neural_net"
    min_labels = 20

    def __init__(
        self, hidden: int = 16, epochs: int = 300, lr: float = 0.01, seed: int = 0
    ):
        self.hidden = hidden
        self.epochs = epochs
        self.lr = lr
        self.seed = seed

    def fit(self, items):
        self.now = datetime.now(timezone.utc)
        self.dim = 0
        for i in items:
            if i.embedding is not None:
                self.dim = len(i.embedding)
                break
        X = _design_matrix(items, self.dim, self.now)
        y = np.asarray([i.label for i in items], dtype=float)
        rng = np.random.default_rng(self.seed)
        n_in = X.shape[1]
        W1 = rng.normal(0, 1.0 / np.sqrt(n_in), (n_in, self.hidden))
        b1 = np.zeros(self.hidden)
        W2 = rng.normal(0, 1.0 / np.sqrt(self.hidden), (self.hidden, 1))
        b2 = np.zeros(1)
        params = [W1, b1, W2, b2]
        m = [np.zeros_like(p) for p in params]
        v = [np.zeros_like(p) for p in params]
        beta1, beta2, eps, decay = 0.9, 0.999, 1e-8, 1e-4
        n = len(y)
        for t in range(1, self.epochs + 1):
            h = np.tanh(X @ W1 + b1)
            out = np.tanh(h @ W2 + b2).ravel()
            err = out - y
            d_out = (2.0 / n) * err * (1 - out**2)
            gW2 = h.T @ d_out[:, None] + decay * W2
            gb2 = np.array([d_out.sum()])
            d_h = d_out[:, None] @ W2.T * (1 - h**2)
            gW1 = X.T @ d_h + decay * W1
            gb1 = d_h.sum(axis=0)
            for p, g, mi, vi in zip(params, [gW1, gb1, gW2, gb2], m, v):
                mi *= beta1
                mi += (1 - beta1) * g
                vi *= beta2
                vi += (1 - beta2) * g**2
                p -= (
                    self.lr
                    * (mi / (1 - beta1**t))
                    / (np.sqrt(vi / (1 - beta2**t)) + eps)
                )
        self.params = params

    def predict(self, items):
        W1, b1, W2, b2 = self.params
        X = _design_matrix(items, self.dim, self.now)
        h = np.tanh(X @ W1 + b1)
        scores = np.tanh(h @ W2 + b2).ravel()
        confs = np.clip(np.abs(scores) * 0.8 + 0.1, 0.0, 1.0)
        return scores, confs


def all_models() -> List[VoteModel]:
    return [
        GlobalMeanModel(),
        SourceMeanModel(),
        KNNEmbeddingModel(),
        RidgeModel(),
        MLPModel(),
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
    labeled: Sequence[ItemFeatures], models: Optional[List[VoteModel]] = None
) -> List[ModelStats]:
    """Cross-validate every eligible model on the labeled items.

    Uses leave-one-out below 40 labels (make the most of scarce votes),
    5-fold above. Models whose `min_labels` isn't met are reported with null
    metrics so the stats UI can show why they're not competing yet.
    """
    models = models if models is not None else all_models()
    n = len(labeled)
    results: List[ModelStats] = []

    for model in models:
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

    # pick the winner: lowest MAE among models that produced metrics
    scored = [r for r in results if r.mae is not None]
    if scored:
        best = min(scored, key=lambda r: r.mae)
        best.chosen = True
    return results


def best_model(stats: List[ModelStats]) -> Optional[str]:
    for s in stats:
        if s.chosen:
            return s.model_name
    return None
