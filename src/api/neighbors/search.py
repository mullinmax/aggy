"""The graph walk itself, with no database in it.

Separated from ``graph.py`` deliberately: what makes a greedy walk correct --
where it terminates, that it never revisits a node, that the running top-k is
the top-k of everything it actually looked at -- is a property of the
algorithm, not of the schema. Kept pure, it can be tested against a graph built
by hand in a few lines, which is the only way to test the termination condition
at all.

The search is the standard navigable-small-world one: hold a candidate queue
ordered by similarity to the query, repeatedly expand the best unexplored
candidate, and stop once the best remaining candidate is no better than the
worst result already held. With a graph of nearest-neighbour links that walks
downhill towards the query and settles at a local minimum, visiting a few dozen
nodes rather than the whole feed.

It is approximate, and there is no pretending otherwise: an unlucky entry point
in a poorly-connected graph finds a worse neighbourhood than a scan would.
``width`` is the lever -- carrying more candidates than we ultimately keep is
what lets the walk cross a small ridge instead of stopping on top of it.
"""

import heapq
import json
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np


def parse_embedding(embeddings) -> Optional[np.ndarray]:
    """``items.embeddings`` is a JSONB dict of {model_name: vector}; take the
    first vector present, since one embedding model runs per deployment.

    Returns None for a row with no embedding, which every caller reads as "this
    article cannot take part in similarity" rather than as an error.
    """
    if not embeddings:
        return None
    if isinstance(embeddings, str):
        try:
            embeddings = json.loads(embeddings)
        except (TypeError, ValueError):
            return None
    if not isinstance(embeddings, dict):
        return None
    for vector in embeddings.values():
        if vector:
            return np.asarray(vector, dtype=float)
    return None


def embedding_model_name(embeddings) -> Optional[str]:
    """Which model produced the vector ``parse_embedding`` would return.

    Recorded alongside the links so a graph built from a since-replaced model
    is recognisable as such rather than silently mixed with a new one.
    """
    if isinstance(embeddings, str):
        try:
            embeddings = json.loads(embeddings)
        except (TypeError, ValueError):
            return None
    if not isinstance(embeddings, dict):
        return None
    for name, vector in embeddings.items():
        if vector:
            return name
    return None


def unit(vector) -> Optional[np.ndarray]:
    """An embedding scaled to length 1, or None if there is nothing to scale.

    Every similarity in the graph is a dot product of two of these, so the
    normalisation happens once per article per walk instead of once per
    comparison -- and cosine similarity of unit vectors *is* the dot product.
    """
    if vector is None:
        return None
    vec = np.asarray(vector, dtype=float)
    if vec.ndim != 1 or vec.size == 0:
        return None
    norm = float(np.linalg.norm(vec))
    if norm <= 0.0 or not np.isfinite(norm):
        return None
    return vec / norm


def similarity(a: Optional[np.ndarray], b: Optional[np.ndarray]) -> Optional[float]:
    """Cosine similarity of two already-normalised vectors, or None if either
    is missing or they came from different models (different lengths)."""
    if a is None or b is None or a.shape != b.shape:
        return None
    return float(np.dot(a, b))


def greedy_search(
    query: np.ndarray,
    entry_points: Iterable[str],
    neighbors_of: Callable[[str], Iterable[str]],
    vectors_of: Callable[[Sequence[str]], Dict[str, np.ndarray]],
    *,
    k: int = 5,
    width: Optional[int] = None,
    max_hops: int = 64,
    exclude: Iterable[str] = (),
) -> List[Tuple[str, float]]:
    """Walk the graph towards ``query`` and return its ``k`` nearest, best
    first, as (item hash, similarity) pairs.

    ``neighbors_of`` gives a node's stored links (both directions, so a node
    stays reachable after its own list has moved on) and ``vectors_of`` fetches
    unit vectors for a batch of nodes -- batched because each call is a
    database round trip, and expanding a node needs all of its neighbours at
    once anyway. A node ``vectors_of`` returns nothing for has no usable
    embedding; it is marked seen so it is not asked for twice, and it can still
    never be a result.

    ``width`` is how many candidates the walk carries; it defaults to ``k``.
    Above ``k`` it keeps runners-up alive as expansion candidates, which is
    what lets the walk step over a small ridge rather than stopping on it.
    ``max_hops`` bounds the expansions so a strange graph cannot make the walk
    unbounded.

    The result is the best of everything actually visited. That is a local
    minimum, not a guaranteed global one -- see the module docstring.
    """
    width = max(int(k), int(width or k))
    seen = set(exclude)
    # best-first results, similarity descending, at most `width` of them
    results: List[Tuple[float, str]] = []
    # candidates still to expand, as a min-heap of (-similarity, hash)
    candidates: List[Tuple[float, str]] = []

    def consider(hashes: Iterable[str]) -> List[str]:
        """Score a batch of nodes. Returns the ones that could be scored."""
        fresh = [h for h in dict.fromkeys(hashes) if h not in seen]
        if not fresh:
            return []
        # marked before the fetch, so a node with no embedding is asked for
        # once and then left alone
        seen.update(fresh)
        scored = []
        for url_hash, vector in vectors_of(fresh).items():
            sim = similarity(query, vector)
            if sim is None:
                continue
            heapq.heappush(candidates, (-sim, url_hash))
            results.append((sim, url_hash))
            scored.append(url_hash)
        # ties broken by hash so the same graph always answers the same way
        results.sort(key=lambda row: (-row[0], row[1]))
        del results[width:]
        return scored

    entry = [h for h in dict.fromkeys(entry_points) if h not in seen]
    scored_entries = set(consider(entry))

    hops = 0
    # An entry point with no usable embedding has no position of its own, so it
    # can never enter the candidate queue and the walk would end on the
    # doorstep. It is still a real node with real links, so follow them once:
    # a blind first hop is worth far more than no walk at all.
    for node in entry:
        if node in scored_entries or hops >= max_hops:
            continue
        hops += 1
        consider(neighbors_of(node))

    while candidates and hops < max_hops:
        neg_sim, current = heapq.heappop(candidates)
        # The local minimum: nothing left to explore is closer to the query
        # than the worst result we already hold, so expanding it would only
        # walk away. Only once we hold a full width of results -- before that
        # there is no "worst result" worth comparing against.
        if len(results) >= width and -neg_sim < results[-1][0]:
            break
        hops += 1
        consider(neighbors_of(current))

    return [(url_hash, sim) for sim, url_hash in results[:k]]
