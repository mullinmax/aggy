import pytest

from config import config
from db.base import get_db_con
from db.item import ImageEmbedError, ItemLoose, ItemStrict
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


@pytest.fixture
def image_embed_configured():
    """Point the backfill at an image-embedding service, with tight retry
    settings so a test can watch an item give up."""
    settings = {
        "IMAGE_EMBED_HOST": "image-embed",
        "IMAGE_EMBED_MODEL": "clip-model",
        "IMAGE_EMBED_BACKFILL_BATCH_SIZE": 10,
        "IMAGE_EMBED_BACKFILL_CONCURRENCY": 2,
        "IMAGE_EMBED_MAX_ATTEMPTS": 2,
        "IMAGE_EMBED_RETRY_MINUTES": 60,
        "IMAGE_EMBED_MAX_RETRY_MINUTES": 60,
    }
    for key, value in settings.items():
        config.set(key, value)
    yield
    for key in settings:
        config.config.pop(key, None)


def _embed_state(url_hash: str) -> dict:
    """The item's image-embedding bookkeeping, straight from the row."""
    with get_db_con() as cur:
        cur.execute(
            "SELECT image_embed_attempts, image_embed_failed_at, "
            "image_embed_error FROM items WHERE url_hash = %s",
            (url_hash,),
        )
        return dict(cur.fetchone())


def test_backfill_image_embeddings_embeds_missing(
    monkeypatch, existing_item_strict, image_embed_configured
):
    """The backfill embeds stored items whose preview image has no embedding for
    the current model, and persists the result."""
    monkeypatch.setattr(jobs, "embed_image", lambda image_url: [0.1, 0.2, 0.3])

    jobs.backfill_image_embeddings_job()

    stored = ItemStrict.read(url_hash=existing_item_strict.url_hash)
    assert stored.image_embeddings == {"clip-model": [0.1, 0.2, 0.3]}


def test_backfill_image_embeddings_keeps_other_models(
    monkeypatch, existing_item_strict, image_embed_configured
):
    """A backfilled vector is merged into whatever the item already had, rather
    than replacing the column — switching models must not throw away the old
    embeddings other code may still be scoring against."""
    existing_item_strict.update(image_embeddings={"old-clip-model": [0.9]})
    monkeypatch.setattr(jobs, "embed_image", lambda image_url: [0.5])

    jobs.backfill_image_embeddings_job()

    stored = ItemStrict.read(url_hash=existing_item_strict.url_hash)
    assert stored.image_embeddings == {"old-clip-model": [0.9], "clip-model": [0.5]}


def test_backfill_image_embeddings_covers_content_only_images(
    monkeypatch, existing_item_strict, image_embed_configured
):
    """Items with no image_url are still picked up when their content carries an
    image — that's all a reddit RSS entry has when the post JSON couldn't be
    fetched, and the UI shows it as the card's preview."""
    existing_item_strict.update(
        image_url=None,
        content='<p>hi</p><img src="http://example.com/from-content.jpg">',
    )
    embedded = []

    def fake_embed(image_url):
        embedded.append(image_url)
        return [0.4]

    monkeypatch.setattr(jobs, "embed_image", fake_embed)

    jobs.backfill_image_embeddings_job()

    assert embedded == ["http://example.com/from-content.jpg"]
    stored = ItemStrict.read(url_hash=existing_item_strict.url_hash)
    assert stored.image_embeddings == {"clip-model": [0.4]}


def test_backfill_image_embeddings_noop_without_service(
    monkeypatch, existing_item_strict
):
    """With no service configured the backfill does nothing."""
    config.config.pop("IMAGE_EMBED_HOST", None)
    called = []
    monkeypatch.setattr(jobs, "embed_image", lambda image_url: called.append(image_url))

    jobs.backfill_image_embeddings_job()

    assert called == []


def test_backfill_records_failure_and_backs_off(
    monkeypatch, existing_item_strict, image_embed_configured
):
    """A failed item is counted and held back from the next pass.

    This is what keeps the backfill moving: without the attempt on the row, the
    same newest-first batch of unfetchable pictures is re-selected and re-failed
    every single run, and the backlog behind it is never reached."""

    def fail(image_url):
        raise ImageEmbedError("could not fetch image: HTTP 403")

    monkeypatch.setattr(jobs, "embed_image", fail)

    jobs.backfill_image_embeddings_job()

    state = _embed_state(existing_item_strict.url_hash)
    assert state["image_embed_attempts"] == 1
    assert "HTTP 403" in state["image_embed_error"]
    assert state["image_embed_failed_at"] is not None

    # the retry backoff hasn't elapsed, so an immediate second pass leaves it
    # alone rather than burning the batch on it again
    tried = []
    monkeypatch.setattr(jobs, "embed_image", lambda image_url: tried.append(image_url))

    jobs.backfill_image_embeddings_job()

    assert tried == []
    assert _embed_state(existing_item_strict.url_hash)["image_embed_attempts"] == 1


def test_backfill_retries_once_the_backoff_has_elapsed(
    monkeypatch, existing_item_strict, image_embed_configured
):
    """Image hosts fail transiently, so a failed item comes back around — just
    not immediately."""
    with get_db_con() as cur:
        cur.execute(
            "UPDATE items SET image_embed_attempts = 1, "
            "image_embed_failed_at = NOW() - interval '2 hours' "
            "WHERE url_hash = %s",
            (existing_item_strict.url_hash,),
        )

    monkeypatch.setattr(jobs, "embed_image", lambda image_url: [0.7])

    jobs.backfill_image_embeddings_job()

    stored = ItemStrict.read(url_hash=existing_item_strict.url_hash)
    assert stored.image_embeddings == {"clip-model": [0.7]}
    # succeeding clears the history, so a later model change starts it fresh
    state = _embed_state(existing_item_strict.url_hash)
    assert state["image_embed_attempts"] == 0
    assert state["image_embed_error"] is None


def test_backfill_gives_up_after_max_attempts(
    monkeypatch, existing_item_strict, image_embed_configured
):
    """An item that has exhausted its attempts leaves the queue for good.

    Preview images do die permanently — expired reddit signatures, deleted
    uploads — and retrying them forever is what starved the rest of the
    backlog."""
    with get_db_con() as cur:
        cur.execute(
            "UPDATE items SET image_embed_attempts = %s, "
            "image_embed_failed_at = NOW() - interval '30 days' "
            "WHERE url_hash = %s",
            (
                config.get_int("IMAGE_EMBED_MAX_ATTEMPTS"),
                existing_item_strict.url_hash,
            ),
        )

    tried = []
    monkeypatch.setattr(jobs, "embed_image", lambda image_url: tried.append(image_url))

    jobs.backfill_image_embeddings_job()

    assert tried == []


def test_backfill_prefers_never_attempted_items(
    monkeypatch, existing_source, existing_feed, image_embed_configured
):
    """Items nobody has tried yet go before items already known to be difficult,
    so every pass spends its budget where it is most likely to land."""
    config.set("IMAGE_EMBED_BACKFILL_BATCH_SIZE", 1)

    tried_before = ItemStrict(
        url="http://example.com/tried-before",
        title="Tried before",
        domain="example.com",
        excerpt="x",
        content="x",
        image_url="http://example.com/old.jpg",
    )
    tried_before.create()
    never_tried = ItemStrict(
        url="http://example.com/never-tried",
        title="Never tried",
        domain="example.com",
        excerpt="x",
        content="x",
        image_url="http://example.com/new.jpg",
    )
    never_tried.create()

    with get_db_con() as cur:
        cur.execute(
            "UPDATE items SET image_embed_attempts = 1, "
            "image_embed_failed_at = NOW() - interval '30 days', "
            # older, so newest-first ordering alone wouldn't pick it either way
            "created_at = NOW() - interval '1 day' WHERE url_hash = %s",
            (tried_before.url_hash,),
        )

    tried = []

    def fake_embed(image_url):
        tried.append(image_url)
        return [0.1]

    monkeypatch.setattr(jobs, "embed_image", fake_embed)

    jobs.backfill_image_embeddings_job()

    assert tried == ["http://example.com/new.jpg"]


def test_backfill_advances_past_a_batch_of_broken_images(
    monkeypatch, existing_feed, image_embed_configured
):
    """The regression this is all for: a run's worth of unfetchable pictures no
    longer blocks the items behind them.

    Selection is newest-first, so before failures were recorded the newest batch
    of dead images was re-picked and re-failed on every pass and nothing older
    was ever reached, however long the job ran."""
    config.set("IMAGE_EMBED_BACKFILL_BATCH_SIZE", 2)

    broken = ["http://example.com/broken-a.jpg", "http://example.com/broken-b.jpg"]
    good = ["http://example.com/good-a.jpg", "http://example.com/good-b.jpg"]

    # older items first, so the two broken ones are the newest and therefore
    # what a newest-first pass reaches for
    for age_days, image_url in enumerate(good + broken[::-1]):
        item = ItemStrict(
            url=f"http://example.com/article-{age_days}",
            title="Title",
            domain="example.com",
            excerpt="Excerpt",
            content="Body",
            image_url=image_url,
        )
        item.create()
        existing_feed.add_items(item)
        with get_db_con() as cur:
            cur.execute(
                "UPDATE items SET created_at = NOW() - make_interval(days => %s) "
                "WHERE url_hash = %s",
                (len(good) + len(broken) - age_days, item.url_hash),
            )

    embedded = []

    def fake_embed(image_url):
        if image_url in broken:
            raise ImageEmbedError("could not fetch image: HTTP 404")
        embedded.append(image_url)
        return [0.1]

    monkeypatch.setattr(jobs, "embed_image", fake_embed)

    jobs.backfill_image_embeddings_job()
    assert embedded == []  # the newest two, both broken

    jobs.backfill_image_embeddings_job()
    assert sorted(embedded) == good


def test_rescrape_resets_attempts_when_the_image_changes(
    monkeypatch, existing_source, existing_item_strict
):
    """A re-scrape that turns up a different picture clears the old one's
    failures, so an item that had given up gets a fresh run at the new URL."""
    # a stored image_url always wins the merge, so the item has to be missing
    # one for a re-scrape to be able to change it
    existing_item_strict.update(image_url=None)

    with get_db_con() as cur:
        cur.execute(
            "UPDATE items SET image_embed_attempts = 5, "
            "image_embed_failed_at = NOW(), image_embed_error = 'HTTP 404' "
            "WHERE url_hash = %s",
            (existing_item_strict.url_hash,),
        )

    monkeypatch.setattr(jobs, "ingest_reddit_item", lambda item: None)
    monkeypatch.setattr(
        jobs,
        "ingest_open_graph_item",
        lambda item: ItemLoose(url=item.url, image_url="http://example.com/new.jpg"),
    )
    monkeypatch.setattr(jobs, "ingest_mercury_item", lambda item: None)
    monkeypatch.setattr(jobs.config, "get", lambda key, default=None: default)
    monkeypatch.setattr("ranking.engine.rank_feed", lambda feed: None)

    jobs.rescrape_source(existing_source)

    state = _embed_state(existing_item_strict.url_hash)
    assert state["image_embed_attempts"] == 0
    assert state["image_embed_error"] is None
