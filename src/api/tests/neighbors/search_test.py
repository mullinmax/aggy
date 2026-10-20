"""The graph walk, against graphs built by hand. No database.

These are the properties that make a greedy walk usable as a nearest-neighbour
search: that it finds the nearest node when the graph leads to it, that it
stops rather than wandering, that it never asks about a node twice, and that
being approximate means missing a result rather than returning a wrong one.
"""

import numpy as np
import pytest

from neighbors.search import (
    embedding_model_name,
    greedy_search,
    parse_embedding,
    similarity,
    unit,
)


def _vec(*values) -> np.ndarray:
    return unit(np.asarray(values, dtype=float))


def _graph(nodes: dict, edges: dict):
    """A (neighbors_of, vectors_of, calls) triple over a hand-built graph.

    ``calls`` records every batch the walk asked for, so a test can assert on
    what it *did not* look at -- which is the entire point of walking instead
    of scanning.
    """
    calls = []

    def neighbors_of(node):
        return edges.get(node, ())

    def vectors_of(hashes):
        calls.append(tuple(hashes))
        return {h: nodes[h] for h in hashes if h in nodes}

    return neighbors_of, vectors_of, calls


def test_walks_a_chain_to_the_nearest_node():
    # A ring of directions, chained so each node links only to its immediate
    # neighbours: reaching the far end means actually walking it.
    angles = np.linspace(0.0, np.pi / 2, 8)
    nodes = {f"n{i}": _vec(np.cos(a), np.sin(a)) for i, a in enumerate(angles)}
    edges = {f"n{i}": [f"n{i - 1}", f"n{i + 1}"] for i in range(8)}
    edges["n0"] = ["n1"]
    edges["n7"] = ["n6"]
    neighbors_of, vectors_of, _calls = _graph(nodes, edges)

    # the query sits on top of n7, entered from the opposite end of the chain
    found = greedy_search(
        nodes["n7"], ["n0"], neighbors_of, vectors_of, k=3, width=3, max_hops=32
    )

    assert found[0][0] == "n7"
    assert found[0][1] == pytest.approx(1.0)
    # similarities come back descending
    assert [sim for _h, sim in found] == sorted(
        (sim for _h, sim in found), reverse=True
    )


def test_stops_without_visiting_the_whole_graph():
    """The walk exists to avoid a scan, so it has to actually avoid one."""
    # One tight cluster around the query and a far-away cloud, joined by a
    # single edge pointing away from the query.
    nodes = {"near0": _vec(1.0, 0.0), "near1": _vec(0.99, 0.14)}
    edges = {"near0": ["near1"], "near1": ["near0", "far0"]}
    for i in range(50):
        nodes[f"far{i}"] = _vec(-1.0, 0.02 * i)
        edges[f"far{i}"] = [f"far{j}" for j in range(50) if j != i]
    neighbors_of, vectors_of, calls = _graph(nodes, edges)

    found = greedy_search(
        nodes["near0"], ["near0"], neighbors_of, vectors_of, k=2, width=2, max_hops=64
    )

    assert {h for h, _sim in found} == {"near0", "near1"}
    looked_at = {h for batch in calls for h in batch}
    # the one far node the bridge edge exposes is scored and then declined;
    # the other forty-nine are never even asked about
    assert len([h for h in looked_at if h.startswith("far")]) <= 1


def test_never_asks_about_a_node_twice():
    """Re-fetching a node's vector on every edge that reaches it is the cost
    that turns a walk back into a scan."""
    nodes = {f"n{i}": _vec(1.0, 0.1 * i) for i in range(6)}
    # fully connected, so every node is reachable from every other
    edges = {h: [o for o in nodes if o != h] for h in nodes}
    neighbors_of, vectors_of, calls = _graph(nodes, edges)

    greedy_search(
        _vec(1.0, 0.0), ["n0"], neighbors_of, vectors_of, k=3, width=6, max_hops=64
    )

    asked = [h for batch in calls for h in batch]
    assert len(asked) == len(set(asked))


def test_excludes_the_query_article_itself():
    nodes = {"self": _vec(1.0, 0.0), "other": _vec(0.9, 0.4)}
    edges = {"self": ["other"], "other": ["self"]}
    neighbors_of, vectors_of, _calls = _graph(nodes, edges)

    found = greedy_search(
        nodes["self"],
        ["self", "other"],
        neighbors_of,
        vectors_of,
        k=5,
        exclude=("self",),
    )

    assert [h for h, _sim in found] == ["other"]


def test_a_node_with_no_embedding_is_skipped_not_scored():
    """An article whose embedding failed is still a node in the graph. It must
    not be returned, and must not stop the walk reaching what is behind it."""
    nodes = {"bridge": _vec(0.0, 1.0), "target": _vec(1.0, 0.0)}
    edges = {"start": ["bridge"], "bridge": ["target"]}
    neighbors_of, vectors_of, _calls = _graph(nodes, edges)

    found = greedy_search(
        _vec(1.0, 0.0), ["start"], neighbors_of, vectors_of, k=3, width=3
    )

    assert "start" not in {h for h, _sim in found}
    assert "target" in {h for h, _sim in found}


def test_an_unreachable_nearest_is_missed_rather_than_faked():
    """The walk is approximate and the docstring says so. An island the graph
    does not connect to is simply not found -- it is never returned with a made
    up similarity, and the walk still answers with what it did reach."""
    nodes = {
        "entry": _vec(1.0, 0.0),
        "reachable": _vec(0.95, 0.3),
        "island": _vec(1.0, 0.001),
    }
    edges = {"entry": ["reachable"], "reachable": ["entry"], "island": []}
    neighbors_of, vectors_of, _calls = _graph(nodes, edges)

    found = greedy_search(
        _vec(1.0, 0.0), ["entry"], neighbors_of, vectors_of, k=3, width=3
    )

    assert "island" not in {h for h, _sim in found}
    assert {h for h, _sim in found} == {"entry", "reachable"}


def test_max_hops_bounds_the_walk():
    """A strange graph must not be able to turn one placement into a scan."""
    nodes = {f"n{i}": _vec(np.cos(i * 0.01), np.sin(i * 0.01)) for i in range(200)}
    # a chain that improves forever, so only the hop ceiling ends the walk
    edges = {f"n{i}": [f"n{i + 1}"] for i in range(199)}
    neighbors_of, vectors_of, calls = _graph(nodes, edges)

    greedy_search(
        nodes["n199"], ["n0"], neighbors_of, vectors_of, k=3, width=3, max_hops=5
    )

    # the entry point plus at most five expansions
    assert len(calls) <= 6


@pytest.mark.parametrize(
    "stored,expected_length",
    [
        ({"nomic": [1.0, 0.0, 0.0]}, 3),
        ('{"nomic": [1.0, 0.0]}', 2),  # JSONB that came back as text
        ({"nomic": None, "other": [1.0]}, 1),  # skip an empty vector
    ],
)
def test_parse_embedding_reads_what_the_column_holds(stored, expected_length):
    assert len(parse_embedding(stored)) == expected_length


@pytest.mark.parametrize("stored", [None, {}, {"nomic": []}, "not json", 7])
def test_parse_embedding_reads_nothing_as_no_embedding(stored):
    assert parse_embedding(stored) is None


def test_embedding_model_name_matches_the_vector_parse_returns():
    stored = {"empty": [], "nomic-embed-text": [1.0, 0.0]}
    assert embedding_model_name(stored) == "nomic-embed-text"


def test_unit_rejects_a_vector_that_cannot_be_scaled():
    assert unit(None) is None
    assert unit([0.0, 0.0]) is None
    assert unit([]) is None


def test_similarity_of_different_models_is_no_answer_rather_than_a_wrong_one():
    """Two embeddings of different lengths came from different models. Their
    cosine distance is meaningless, so there must not be one."""
    assert similarity(_vec(1.0, 0.0), _vec(1.0, 0.0, 0.0)) is None
    assert similarity(_vec(1.0, 0.0), None) is None
    assert similarity(_vec(1.0, 0.0), _vec(1.0, 0.0)) == pytest.approx(1.0)
