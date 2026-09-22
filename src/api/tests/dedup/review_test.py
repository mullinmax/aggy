"""Judging duplicate pairs: the queue, what a verdict does, and the model.

Detection collapses a pair when one cosine clears a constant somebody picked by
hand. These cover the loop that replaces that constant with your own answers:
which pairs you are asked about, what clicking the check or the x actually does
to the feed, and the point at which enough answers become a model that decides
for the pairs you never looked at.
"""

import json
import math
from datetime import datetime, timedelta, timezone


from config import config
from db.base import get_db_con
from db.item import ItemLoose
from dedup import detect, review, verdict
from dedup.labels import label_count, label_for, labeled_pairs, pair_key, record_label
from dedup.model import model_for, pair_features, train
from neighbors.graph import neighbor_graph_job
from tests.testing_utils import build_api_request_args


def _add(feed, url, angle=None, title="Title", published=None, author="Someone"):
    """An article in the feed, optionally with a text embedding placed on the
    unit circle so two articles are as alike as their angles are close."""
    item = ItemLoose(
        url=url,
        title=title,
        author=author,
        domain="example.com",
        excerpt="words",
        content="<p>words</p>",
        date_published=published or datetime.now(timezone.utc),
    )
    item.create()
    feed.add_items(item)
    if angle is not None:
        with get_db_con() as cur:
            cur.execute(
                "UPDATE items SET embeddings = %s WHERE url_hash = %s",
                (
                    json.dumps({"test-model": [math.cos(angle), math.sin(angle)]}),
                    item.url_hash,
                ),
            )
    return item


def _with_override(cfg, key, value):
    """config.get_int with one key forced, leaving every other key alone."""
    real = cfg.get_int

    def get_int(name, *args, **kwargs):
        if name == key:
            return value
        return real(name, *args, **kwargs)

    return get_int


def _group_of(user, url_hash):
    with get_db_con() as cur:
        cur.execute(
            "SELECT group_hash, signal FROM item_duplicates "
            "WHERE user_hash = %s AND item_url_hash = %s AND group_hash IS NOT NULL",
            (user.name_hash, url_hash),
        )
        return cur.fetchone()


# ---------- the pair is unordered ----------


def test_a_pair_is_the_same_pair_whichever_way_round_it_came(
    existing_user, existing_feed
):
    """Which article was on the left of the screen carries no meaning, so a
    verdict given one way round is the same row as one given the other."""
    a = _add(existing_feed, "https://outlet-a.com/one")
    b = _add(existing_feed, "https://outlet-b.com/two")

    record_label(existing_user.name_hash, a.url_hash, b.url_hash, True)
    record_label(existing_user.name_hash, b.url_hash, a.url_hash, False)

    assert label_count(existing_user.name_hash) == (0, 1)
    with get_db_con() as cur:
        # and looking it up either way round finds the one answer
        assert label_for(cur, existing_user.name_hash, a.url_hash, b.url_hash) is False
        assert label_for(cur, existing_user.name_hash, b.url_hash, a.url_hash) is False


def test_pair_key_sorts():
    assert pair_key("b", "a") == ("a", "b") == pair_key("a", "b")


# ---------- what the x and the check do ----------


def test_rejecting_a_collapse_puts_the_article_back(existing_user, existing_feed):
    """The click has to do what it looks like it does: the hidden article
    returns to the feed rather than waiting on a model to change its mind."""
    a = _add(existing_feed, "https://outlet-a.com/story", angle=0.0)
    b = _add(existing_feed, "https://outlet-b.com/rewrite", angle=0.01)
    neighbor_graph_job()

    group = _group_of(existing_user, a.url_hash)["group_hash"]
    member = b.url_hash if group == a.url_hash else a.url_hash

    outcome = verdict.apply_verdict(
        existing_user.name_hash, member, group, is_duplicate=False
    )

    assert outcome == "split"
    assert _group_of(existing_user, member) is None
    # the article it was hidden behind keeps its own row, so the group it
    # anchors still exists for anything else in it
    assert _group_of(existing_user, group) is not None


def test_a_rejected_pair_is_never_collapsed_again(existing_user, existing_feed):
    """Your answer is an instruction, not a hint. A later pass re-examines the
    split article and must leave it alone, however close the two vectors are."""
    a = _add(existing_feed, "https://outlet-a.com/story", angle=0.0)
    b = _add(existing_feed, "https://outlet-b.com/rewrite", angle=0.001)
    neighbor_graph_job()

    group = _group_of(existing_user, a.url_hash)["group_hash"]
    member = b.url_hash if group == a.url_hash else a.url_hash
    verdict.apply_verdict(existing_user.name_hash, member, group, is_duplicate=False)

    # force the re-sweep to pick the split article straight back up
    with get_db_con() as cur:
        cur.execute(
            "UPDATE item_duplicates SET checked_at = NOW() - INTERVAL '365 days' "
            "WHERE user_hash = %s AND item_url_hash = %s",
            (existing_user.name_hash, member),
        )
    neighbor_graph_job()

    assert _group_of(existing_user, member) is None


def test_confirming_a_near_miss_collapses_it_now(existing_user, existing_feed):
    """The other half of the same promise. These two sit under the cutoff, so
    detection left them both in the feed; saying they are one story has to
    collapse them rather than only be remembered."""
    a = _add(existing_feed, "https://outlet-a.com/story", angle=0.0)
    b = _add(existing_feed, "https://outlet-b.com/rewrite", angle=0.45)
    neighbor_graph_job()
    assert _group_of(existing_user, a.url_hash) is None

    outcome = verdict.apply_verdict(
        existing_user.name_hash, b.url_hash, a.url_hash, is_duplicate=True
    )

    assert outcome == "grouped"
    group = _group_of(existing_user, a.url_hash)
    assert group["group_hash"] == _group_of(existing_user, b.url_hash)["group_hash"]
    # recorded as yours, not as something a signal measured
    assert group["signal"] == "confirmed"


def test_confirming_a_pair_already_collapsed_changes_nothing(
    existing_user, existing_feed
):
    a = _add(existing_feed, "https://outlet-a.com/story", angle=0.0)
    b = _add(existing_feed, "https://outlet-b.com/rewrite", angle=0.01)
    neighbor_graph_job()
    group = _group_of(existing_user, a.url_hash)["group_hash"]
    member = b.url_hash if group == a.url_hash else a.url_hash

    assert (
        verdict.apply_verdict(existing_user.name_hash, member, group, is_duplicate=True)
        == "unchanged"
    )
    assert _group_of(existing_user, member)["group_hash"] == group


def test_one_verdict_never_merges_two_groups(existing_user, existing_feed):
    """A pair is a pair. Merging would assert that every member of one group is
    the same story as every member of the other, which is the transitive
    closure the star topology exists to prevent."""
    a = _add(existing_feed, "https://a.com/1?utm_source=x", angle=0.0)
    _add(existing_feed, "https://a.com/1?utm_source=y", angle=0.0)
    c = _add(existing_feed, "https://c.com/2?utm_source=x", angle=2.0)
    _add(existing_feed, "https://c.com/2?utm_source=y", angle=2.0)
    neighbor_graph_job()

    left = _group_of(existing_user, a.url_hash)["group_hash"]
    right = _group_of(existing_user, c.url_hash)["group_hash"]
    assert left != right

    outcome = verdict.apply_verdict(
        existing_user.name_hash, a.url_hash, c.url_hash, is_duplicate=True
    )

    assert outcome == "unchanged"
    assert _group_of(existing_user, a.url_hash)["group_hash"] == left
    assert _group_of(existing_user, c.url_hash)["group_hash"] == right
    # the label is still recorded, so detection can act on it honestly later
    with get_db_con() as cur:
        assert label_for(cur, existing_user.name_hash, a.url_hash, c.url_hash) is True


def test_rejecting_a_near_miss_records_without_changing_anything(
    existing_user, existing_feed
):
    a = _add(existing_feed, "https://outlet-a.com/story", angle=0.0)
    b = _add(existing_feed, "https://outlet-b.com/other", angle=0.45)
    neighbor_graph_job()

    outcome = verdict.apply_verdict(
        existing_user.name_hash, b.url_hash, a.url_hash, is_duplicate=False
    )

    assert outcome == "unchanged"
    assert label_count(existing_user.name_hash) == (0, 1)


# ---------- the queue ----------


def test_the_queue_offers_both_collapsed_pairs_and_near_misses(
    existing_user, existing_feed
):
    """The mix is the point. A queue of nothing but collapsed pairs produces
    labels that are almost all "yes", and a model trained on those learns
    nothing about where the line belongs."""
    collapsed_a = _add(existing_feed, "https://a.com/story", angle=0.0)
    _add(existing_feed, "https://b.com/rewrite", angle=0.005)
    near_a = _add(existing_feed, "https://c.com/story", angle=2.0)
    _add(existing_feed, "https://d.com/other", angle=2.45)
    neighbor_graph_job()

    pairs = review.review_pairs(existing_user.name_hash, existing_feed.name_hash)
    kinds = {pair["grouped"] for pair in pairs}

    assert kinds == {True, False}, [
        (p["grouped"], round(p["similarity"], 3)) for p in pairs
    ]
    hashes = {p["candidate_hash"] for p in pairs} | {p["anchor_hash"] for p in pairs}
    assert collapsed_a.url_hash in hashes
    assert near_a.url_hash in hashes


def test_the_queue_leads_with_the_pairs_it_is_least_sure_about(
    existing_user, existing_feed
):
    """A pair the cutoff is confident about teaches a model very little
    whichever way it is answered; a pair sitting on the line teaches it where
    the line is."""
    _add(existing_feed, "https://a.com/1", angle=0.0)
    _add(existing_feed, "https://b.com/1", angle=0.001)  # far above the cutoff
    _add(existing_feed, "https://c.com/2", angle=2.0)
    _add(existing_feed, "https://d.com/2", angle=2.38)  # just under it
    neighbor_graph_job()

    pairs = review.review_pairs(existing_user.name_hash, existing_feed.name_hash)
    threshold = config.get_float("DUPLICATE_SIMILARITY_THRESHOLD")
    distances = [abs(pair["similarity"] - threshold) for pair in pairs]

    assert distances == sorted(distances)


def test_a_pair_you_have_judged_is_not_offered_again(existing_user, existing_feed):
    a = _add(existing_feed, "https://a.com/story", angle=0.0)
    b = _add(existing_feed, "https://b.com/rewrite", angle=0.005)
    neighbor_graph_job()

    before = review.review_pairs(existing_user.name_hash, existing_feed.name_hash)
    assert before

    record_label(existing_user.name_hash, a.url_hash, b.url_hash, True)
    after = review.review_pairs(existing_user.name_hash, existing_feed.name_hash)

    assert not any(
        pair_key(pair["candidate_hash"], pair["anchor_hash"])
        == pair_key(a.url_hash, b.url_hash)
        for pair in after
    )


def test_a_collapsed_pair_is_always_offered_against_its_representative(
    existing_user, existing_feed
):
    """Rejecting takes the candidate out of the group, so the candidate must
    never be the row that makes the group exist."""
    _add(existing_feed, "https://a.com/1?utm_source=x")
    _add(existing_feed, "https://a.com/1?utm_source=y")
    _add(existing_feed, "https://a.com/1?utm_source=z")
    neighbor_graph_job()

    pairs = review.review_pairs(existing_user.name_hash, existing_feed.name_hash)
    assert pairs
    for pair in pairs:
        if not pair["grouped"]:
            continue
        group = _group_of(existing_user, pair["candidate_hash"])["group_hash"]
        assert pair["anchor_hash"] == group
        assert pair["candidate_hash"] != group


# ---------- the model ----------


def _labelled_pair(feed, user, index, same):
    """A judged pair whose features point the way its label says.

    The same-story pairs share a headline, a moment and a picture-less site;
    the different ones are a day apart with unrelated headlines. The embedding
    angle is kept in the band the cutoff cannot separate, so the only thing
    that can be learned is the rest.
    """
    when = datetime.now(timezone.utc) - timedelta(days=index)
    if same:
        left = _add(
            feed,
            f"https://p{index}.com/a",
            angle=0.30,
            title="Rates held steady",
            published=when,
        )
        right = _add(
            feed,
            f"https://p{index}.com/b",
            angle=0.32,
            title="Rates held steady",
            published=when,
        )
    else:
        left = _add(
            feed,
            f"https://q{index}.com/a",
            angle=0.30,
            title="Budget talks stall",
            published=when,
        )
        right = _add(
            feed,
            f"https://q{index}.com/b",
            angle=0.32,
            title="Museum opens new wing",
            published=when + timedelta(days=1),
        )
    record_label(user.name_hash, left.url_hash, right.url_hash, same)
    return left, right


def test_no_model_until_there_are_enough_labels(existing_user, existing_feed):
    """Every install starts here, and one that never reviews anything stays
    here: the hand-picked constant keeps deciding, which is the old
    behaviour."""
    for i in range(3):
        _labelled_pair(existing_feed, existing_user, i, same=i % 2 == 0)

    assert train(labeled_pairs(existing_user.name_hash)) is None


def test_no_model_while_every_answer_points_the_same_way(
    existing_user, existing_feed, monkeypatch
):
    """A classifier that has only ever seen one answer has not learned a line,
    it has learned to say yes."""
    monkeypatch.setattr(
        config, "get_int", _with_override(config, "DUPLICATE_MODEL_MIN_LABELS", 4)
    )
    for i in range(6):
        _labelled_pair(existing_feed, existing_user, i, same=True)

    assert train(labeled_pairs(existing_user.name_hash)) is None


def test_a_model_appears_once_both_answers_are_in(
    existing_user, existing_feed, monkeypatch
):
    monkeypatch.setattr(
        config, "get_int", _with_override(config, "DUPLICATE_MODEL_MIN_LABELS", 6)
    )
    for i in range(8):
        _labelled_pair(existing_feed, existing_user, i, same=i % 2 == 0)

    model = train(labeled_pairs(existing_user.name_hash))

    assert model is not None
    assert model.report.confirmed == 4
    assert model.report.rejected == 4
    # it reports which signals separated the answers, strongest first
    assert model.report.coefficients
    weights = [abs(weight) for _name, weight in model.report.coefficients]
    assert weights == sorted(weights, reverse=True)


def test_the_model_is_refitted_when_a_label_is_added(
    existing_user, existing_feed, monkeypatch
):
    """The cache is keyed on the labels themselves rather than invalidated by
    hand, so a label written by the API is picked up by the detection pass
    whether or not they are the same process."""
    monkeypatch.setattr(
        config, "get_int", _with_override(config, "DUPLICATE_MODEL_MIN_LABELS", 6)
    )
    for i in range(8):
        _labelled_pair(existing_feed, existing_user, i, same=i % 2 == 0)

    first = model_for(existing_user.name_hash)
    assert first is not None
    assert model_for(existing_user.name_hash) is first  # not refitted for nothing

    _labelled_pair(existing_feed, existing_user, 99, same=False)
    second = model_for(existing_user.name_hash)

    assert second is not first
    assert second.report.rejected == 5


def test_pair_features_do_not_depend_on_which_article_came_first(
    existing_user, existing_feed
):
    """ "Is this the same story" cannot depend on which one was asked about
    first, so every feature has to be symmetric."""
    when = datetime.now(timezone.utc)
    left = {
        "title": "Rates held steady",
        "url": "https://one.com/a",
        "author": "A",
        "published": when,
        "embeddings": None,
        "image_embeddings": None,
    }
    right = {
        "title": "Rates left unchanged",
        "url": "https://two.com/b",
        "author": "B",
        "published": when - timedelta(hours=5),
        "embeddings": None,
        "image_embeddings": None,
    }

    assert pair_features(left, right, 0.9) == pair_features(right, left, 0.9)


# ---------- the model decides, once there is one ----------
#
# A stub rather than a fitted model: what could silently break here is the
# wiring -- detection quietly going on consulting the constant while a model
# sits there unused -- and a real model would make that failure depend on how
# well it happened to fit rather than on whether it was asked.


class _StubModel:
    def __init__(self, probability):
        self._probability = probability
        self.asked = []

    def probability(self, features):
        self.asked.append(features)
        return self._probability


def test_the_model_can_collapse_a_pair_the_cutoff_declines(
    existing_user, existing_feed, monkeypatch
):
    """The whole point of the exercise. These two sit under the hand-picked
    cutoff, so today they both stay in the feed; a model that says they are one
    story has to be able to collapse them."""
    stub = _StubModel(1.0)
    monkeypatch.setattr(detect, "model_for", lambda user_hash: stub)

    a = _add(existing_feed, "https://a.com/story", angle=0.0)
    b = _add(existing_feed, "https://b.com/rewrite", angle=0.45)
    neighbor_graph_job()

    assert stub.asked, "detection never consulted the model"
    assert (
        _group_of(existing_user, a.url_hash)["group_hash"]
        == _group_of(existing_user, b.url_hash)["group_hash"]
    )


def test_the_model_can_decline_a_pair_the_cutoff_would_collapse(
    existing_user, existing_feed, monkeypatch
):
    """And the other direction, which is the one that matters for trust: the
    model is not a second opinion layered on top of the cutoff, it replaces
    it."""
    monkeypatch.setattr(detect, "model_for", lambda user_hash: _StubModel(0.0))

    a = _add(existing_feed, "https://a.com/story", angle=0.0)
    b = _add(existing_feed, "https://b.com/rewrite", angle=0.001)
    neighbor_graph_job()

    assert _group_of(existing_user, a.url_hash) is None
    assert _group_of(existing_user, b.url_hash) is None


def test_the_model_never_overrules_an_answer_you_gave(
    existing_user, existing_feed, monkeypatch
):
    """You looked at both articles, which is more than any signal here can do.
    A model certain they are the same story does not get to undo that."""
    monkeypatch.setattr(detect, "model_for", lambda user_hash: _StubModel(1.0))

    a = _add(existing_feed, "https://a.com/story", angle=0.0)
    b = _add(existing_feed, "https://b.com/rewrite", angle=0.001)
    record_label(existing_user.name_hash, a.url_hash, b.url_hash, False)

    neighbor_graph_job()

    assert _group_of(existing_user, a.url_hash) is None
    assert _group_of(existing_user, b.url_hash) is None


def test_the_three_authorities_in_order():
    """``same_story`` on its own: your answer, then the model, then the
    constant."""
    subject = {"url_hash": "a", "title": "t", "url": "https://a.com/x"}
    other = {"url_hash": "b", "title": "t", "url": "https://b.com/x"}
    threshold = config.get_float("DUPLICATE_SIMILARITY_THRESHOLD")

    # no model, no verdict: the constant, exactly as before any of this
    assert detect.same_story(subject, other, threshold + 0.01, None, None) is True
    assert detect.same_story(subject, other, threshold - 0.01, None, None) is False

    # a model, no verdict: the model, and the constant is not consulted
    assert detect.same_story(subject, other, 0.1, _StubModel(1.0), None) is True
    assert detect.same_story(subject, other, 0.99, _StubModel(0.0), None) is False

    # a verdict: yours, whatever either of the others would have said
    assert detect.same_story(subject, other, 0.99, _StubModel(1.0), False) is False
    assert detect.same_story(subject, other, 0.01, _StubModel(0.0), True) is True


# ---------- the routes ----------


def test_the_review_endpoint_serves_pairs_and_the_model_status(
    client, existing_user, existing_feed, token
):
    _add(existing_feed, "https://a.com/story", angle=0.0)
    _add(existing_feed, "https://b.com/rewrite", angle=0.005)
    neighbor_graph_job()

    args = build_api_request_args(
        path="/feed/duplicate_review",
        params={"feed_name_hash": existing_feed.name_hash},
        token=token,
    )
    body = client.get(**args).json()

    assert body["pairs"]
    pair = body["pairs"][0]
    assert pair["anchor"]["item_hash"] and pair["candidate"]["item_hash"]
    assert pair["anchor"]["item_hash"] != pair["candidate"]["item_hash"]
    # the page draws the feed's own cards, so both sides carry a whole article
    assert pair["anchor"]["item_content"] is not None
    assert "item_media" in pair["anchor"]
    # the page has to be able to explain itself before a model exists
    assert body["model"]["trained"] is False
    assert body["model"]["needed"] > 0
    assert body["model"]["confirmed"] == 0


def test_a_pair_carries_the_pictures_that_are_not_in_image_url(
    client, existing_feed, token
):
    """The bug this shape was changed for.

    An article's picture is not always in ``image_url``: from some sources it
    arrives as a media attachment, from others it is only in the body. A
    summary carrying ``image_url`` alone showed nothing at all for those, so
    half the pairs came up with a picture and half without -- on the one screen
    whose entire job is comparing two articles by eye.
    """
    a = _add(existing_feed, "https://a.com/story", angle=0.0)
    b = _add(existing_feed, "https://b.com/rewrite", angle=0.005)
    with get_db_con() as cur:
        for item in (a, b):
            cur.execute(
                "UPDATE items SET image_url = NULL, media = %s WHERE url_hash = %s",
                (
                    json.dumps(
                        [
                            {
                                "type": "video",
                                "url": "https://c.dn/v.mp4",
                                "poster": "https://c.dn/v.jpg",
                            }
                        ]
                    ),
                    item.url_hash,
                ),
            )
    neighbor_graph_job()

    args = build_api_request_args(
        path="/feed/duplicate_review",
        params={"feed_name_hash": existing_feed.name_hash},
        token=token,
    )
    body = client.get(**args).json()

    assert body["pairs"]
    for side in ("anchor", "candidate"):
        media = body["pairs"][0][side]["item_media"]
        assert media, f"{side} lost its media"
        assert media[0]["poster"] == "https://c.dn/v.jpg"


def test_the_verdict_endpoint_splits_and_reports(
    client, existing_user, existing_feed, token
):
    a = _add(existing_feed, "https://a.com/story", angle=0.0)
    b = _add(existing_feed, "https://b.com/rewrite", angle=0.005)
    neighbor_graph_job()
    group = _group_of(existing_user, a.url_hash)["group_hash"]
    member = b.url_hash if group == a.url_hash else a.url_hash

    args = build_api_request_args(
        path="/feed/duplicate_verdict",
        params={
            "feed_name_hash": existing_feed.name_hash,
            "candidate_hash": member,
            "anchor_hash": group,
            "is_duplicate": False,
        },
        token=token,
    )
    body = client.post(**args).json()

    assert body["outcome"] == "split"
    assert body["model"]["rejected"] == 1
    assert _group_of(existing_user, member) is None


def test_an_article_cannot_be_a_duplicate_of_itself(client, existing_feed, token):
    a = _add(existing_feed, "https://a.com/story")
    args = build_api_request_args(
        path="/feed/duplicate_verdict",
        params={
            "feed_name_hash": existing_feed.name_hash,
            "candidate_hash": a.url_hash,
            "anchor_hash": a.url_hash,
            "is_duplicate": True,
        },
        token=token,
    )
    assert client.post(**args).status_code == 422
