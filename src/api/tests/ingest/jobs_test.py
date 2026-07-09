from db.item import ItemLoose, ItemStrict
from ingest import jobs


def test_rescrape_source_updates_changed_item_and_retrains(
    monkeypatch, existing_source, existing_item_strict, existing_item_state
):
    """A re-scrape that turns up new content persists it and, because the item
    carries a vote, retrains the feed that voted on it."""
    longer_content = existing_item_strict.content + " with a lot more detail now"

    # open graph turns up richer content; the other scrapers find nothing
    monkeypatch.setattr(jobs, "ingest_reddit_item", lambda item: None)
    monkeypatch.setattr(
        jobs,
        "ingest_open_graph_item",
        lambda item: ItemLoose(url=item.url, content=longer_content),
    )
    monkeypatch.setattr(jobs, "ingest_mercury_item", lambda item: None)
    # no embedding model configured, so no ollama round-trip
    monkeypatch.setattr(jobs.config, "get", lambda key, default=None: default)

    ranked = []
    monkeypatch.setattr(
        "ranking.engine.rank_feed", lambda feed: ranked.append(feed.name_hash)
    )

    jobs.rescrape_source(existing_source)

    # the richer content was written back
    stored = ItemStrict.read(url_hash=existing_item_strict.url_hash)
    assert longer_content in stored.content

    # the feed holding the vote was retrained exactly once
    assert ranked == [existing_item_state.feed_hash]


def test_rescrape_source_skips_unchanged_item(
    monkeypatch, existing_source, existing_item_strict, existing_item_state
):
    """When re-scraping turns up nothing new, the item is left alone and no
    retraining is triggered."""
    monkeypatch.setattr(jobs, "ingest_reddit_item", lambda item: None)
    monkeypatch.setattr(jobs, "ingest_open_graph_item", lambda item: None)
    monkeypatch.setattr(jobs, "ingest_mercury_item", lambda item: None)
    monkeypatch.setattr(jobs.config, "get", lambda key, default=None: default)

    ranked = []
    monkeypatch.setattr(
        "ranking.engine.rank_feed", lambda feed: ranked.append(feed.name_hash)
    )

    jobs.rescrape_source(existing_source)

    assert ranked == []
