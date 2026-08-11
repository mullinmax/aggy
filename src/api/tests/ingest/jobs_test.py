from config import config
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


def test_rescrape_source_persists_newly_added_image_embedding(
    monkeypatch, existing_source, existing_item_strict
):
    """An image embedding computed during a re-scrape is written back even when
    nothing else about the item changed — the whole point of retrying an item
    whose image fetch failed the first time.

    The item starts with a vector from an older model, so the re-scrape adds a
    key to an existing dict. add_image_embedding mutates that dict in place, so
    sharing it with the stored item (rather than copying) makes the before/after
    comparison see no change and silently drop the new embedding."""
    existing_item_strict.update(image_embeddings={"old-clip-model": [0.1]})

    monkeypatch.setattr(jobs, "ingest_reddit_item", lambda item: None)
    monkeypatch.setattr(jobs, "ingest_open_graph_item", lambda item: None)
    monkeypatch.setattr(jobs, "ingest_mercury_item", lambda item: None)

    config.set("IMAGE_EMBED_HOST", "image-embed")
    config.set("IMAGE_EMBED_MODEL", "clip-model")

    # mirrors the real method, which mutates image_embeddings in place
    def fake_embed(self, model_name, force_refresh=False):
        if self.image_embeddings is None:
            self.image_embeddings = {}
        self.image_embeddings[model_name] = [0.5]

    monkeypatch.setattr("db.item.ItemBase.add_image_embedding", fake_embed)
    monkeypatch.setattr("ranking.engine.rank_feed", lambda feed: None)

    try:
        jobs.rescrape_source(existing_source)
    finally:
        config.config.pop("IMAGE_EMBED_HOST", None)
        config.config.pop("IMAGE_EMBED_MODEL", None)

    stored = ItemStrict.read(url_hash=existing_item_strict.url_hash)
    assert stored.image_embeddings == {"old-clip-model": [0.1], "clip-model": [0.5]}


def test_backfill_image_embeddings_embeds_missing(
    monkeypatch, existing_item_strict
):
    """The backfill embeds stored items whose preview image has no embedding for
    the current model, and persists the result."""
    config.set("IMAGE_EMBED_HOST", "image-embed")
    config.set("IMAGE_EMBED_MODEL", "clip-model")

    def fake_embed(self, model_name, force_refresh=False):
        self.image_embeddings = {model_name: [0.1, 0.2, 0.3]}

    monkeypatch.setattr("db.item.ItemBase.add_image_embedding", fake_embed)
    try:
        jobs.backfill_image_embeddings_job()
    finally:
        config.config.pop("IMAGE_EMBED_HOST", None)
        config.config.pop("IMAGE_EMBED_MODEL", None)

    stored = ItemStrict.read(url_hash=existing_item_strict.url_hash)
    assert stored.image_embeddings == {"clip-model": [0.1, 0.2, 0.3]}


def test_backfill_image_embeddings_covers_content_only_images(
    monkeypatch, existing_item_strict
):
    """Items with no image_url are still picked up when their content carries an
    image — that's all a reddit RSS entry has when the post JSON couldn't be
    fetched, and the UI shows it as the card's preview."""
    existing_item_strict.update(
        image_url=None,
        content='<p>hi</p><img src="http://example.com/from-content.jpg">',
    )
    config.set("IMAGE_EMBED_HOST", "image-embed")
    config.set("IMAGE_EMBED_MODEL", "clip-model")

    def fake_embed(self, model_name, force_refresh=False):
        self.image_embeddings = {model_name: [0.4]}

    monkeypatch.setattr("db.item.ItemBase.add_image_embedding", fake_embed)
    try:
        jobs.backfill_image_embeddings_job()
    finally:
        config.config.pop("IMAGE_EMBED_HOST", None)
        config.config.pop("IMAGE_EMBED_MODEL", None)

    stored = ItemStrict.read(url_hash=existing_item_strict.url_hash)
    assert stored.image_embeddings == {"clip-model": [0.4]}


def test_backfill_image_embeddings_noop_without_service(
    monkeypatch, existing_item_strict
):
    """With no service configured the backfill does nothing."""
    config.config.pop("IMAGE_EMBED_HOST", None)
    called = []
    monkeypatch.setattr(
        "db.item.ItemBase.add_image_embedding",
        lambda self, model_name, force_refresh=False: called.append(model_name),
    )

    jobs.backfill_image_embeddings_job()

    assert called == []
