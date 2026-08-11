import logging

import pytest

from config import config
from db.item import ItemStrict
from ingest.source import ingest_source

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Example feed</title>
    <item>
      <title>An article</title>
      <link>http://example.com/an-article</link>
      <description>Some words about something.</description>
    </item>
  </channel>
</rss>
"""


class FakeResponse:
    status_code = 200
    headers: dict = {}

    def __init__(self, content: bytes):
        self.content = content


@pytest.fixture
def offline_ingest(monkeypatch):
    """Serve one canned RSS entry and stub out every network-bound scraper, so
    ingest_source exercises its own bookkeeping and nothing else."""
    monkeypatch.setattr(
        "ingest.source.requests.get", lambda url, **kw: FakeResponse(RSS.encode())
    )
    monkeypatch.setattr("ingest.source.ingest_reddit_item", lambda item: None)
    monkeypatch.setattr("ingest.source.ingest_open_graph_item", lambda item: None)
    monkeypatch.setattr("ingest.source.ingest_mercury_item", lambda item: None)
    # no embedding services in the test environment
    config.set("OLLAMA_EMBEDDING_MODEL", None)
    config.set("IMAGE_EMBED_HOST", None)
    yield


def test_ingest_source_stores_and_links_a_new_item(
    existing_source, existing_feed, offline_ingest
):
    ingest_source(existing_source)

    items = existing_source.query_items()
    assert [str(i.url) for i in items] == ["http://example.com/an-article"]
    assert len(existing_feed.query_items()) == 1


def test_ingest_source_is_idempotent_and_quiet(
    existing_source, existing_feed, offline_ingest, caplog
):
    """Re-reading a feed whose items are all stored used to log an "already
    exists" error for every entry, and abandon the rest of the loop body."""
    ingest_source(existing_source)

    with caplog.at_level(logging.ERROR):
        ingest_source(existing_source)

    assert caplog.records == []
    assert len(existing_source.query_items()) == 1
    assert len(existing_feed.query_items()) == 1


def test_ingest_source_links_an_item_another_feed_scraped_first(
    existing_source, existing_feed, unique_item_strict, offline_ingest
):
    """The item exists globally but this source has never seen it. Bailing out
    on the duplicate-create error left it permanently unlinked."""
    stored = unique_item_strict.model_copy()
    stored.url = "http://example.com/an-article"
    stored.create()

    assert existing_source.query_items() == []

    ingest_source(existing_source)

    assert len(existing_source.query_items()) == 1
    assert len(existing_feed.query_items()) == 1


def test_ingest_source_keeps_the_score_ranking_assigned(
    existing_source, existing_feed, offline_ingest
):
    """Re-linking on every check must not reset what ranking predicted."""
    ingest_source(existing_source)
    url_hash = existing_feed.query_items()[0].url_hash
    existing_feed.set_items_scores({url_hash: 9.0})

    ingest_source(existing_source)

    from db.base import get_db_con

    with get_db_con() as cur:
        cur.execute(
            "SELECT score FROM feed_items "
            "WHERE user_hash = %s AND feed_hash = %s AND item_url_hash = %s",
            (existing_feed.user_hash, existing_feed.name_hash, url_hash),
        )
        assert cur.fetchone()["score"] == 9.0


def test_ingest_source_persists_an_embedding_added_to_a_stored_item(
    existing_source, existing_feed, offline_ingest, monkeypatch
):
    """An embedding computed for an already-stored item used to be discarded by
    the failed create(), so it was recomputed from scratch on every check."""
    ingest_source(existing_source)
    url_hash = existing_feed.query_items()[0].url_hash
    assert not ItemStrict.read(url_hash=url_hash).embeddings

    config.set("OLLAMA_EMBEDDING_MODEL", "test-embed")
    monkeypatch.setattr(
        ItemStrict,
        "add_embedding",
        lambda self, model_name, force_refresh=False: self.__setattr__(
            "embeddings", {model_name: [0.5]}
        ),
    )

    ingest_source(existing_source)

    assert ItemStrict.read(url_hash=url_hash).embeddings == {"test-embed": [0.5]}
