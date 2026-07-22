import logging

from constants import SOURCE_READ_INTERVAL_MINUTES
from db.base import get_db_con
from db.feed import Feed
from db.item import ItemLoose
from db.source import Source
from ingest.source import ingest_source
from ingest.item.reddit import ingest_reddit_item
from ingest.item.open_graph import ingest_open_graph_item
from ingest.item.mercury import ingest_mercury_item
from db.user import User
from utils import get_ollama_connection
from config import config

# Item fields whose text feeds the embedding prompt (see ItemBase.__str__):
# a change in any of them means the stored embedding is stale.
_EMBEDDING_TEXT_FIELDS = (
    "title",
    "author",
    "date_published",
    "domain",
    "excerpt",
    "content",
)

# Item fields re-collected by a re-scrape. A change in any of them is worth
# persisting, and — for voted items — worth retraining the feed's models on.
_RESCRAPE_FIELDS = _EMBEDDING_TEXT_FIELDS + ("image_url", "media")


def source_ingestion_scheduling_job() -> None:
    users = User.read_all()
    for user in users:
        for feed in user.feeds:
            for source in feed.sources:
                source.trigger_ingest(now=False)


def source_ingestion_job() -> None:
    """Pop the next due source and ingest it.

    Mirrors the previous Redis ZMPOP-based queue: pick the source with the
    smallest ``next_ingest_at``, only proceed if it's actually due, and then
    bump its next ingest time forward.

    All time comparison happens in SQL so it is done against the database
    clock; ``next_ingest_at`` is a TIMESTAMPTZ and comparing it to a naive
    Python ``datetime.now()`` silently pushes ingestion hours into the
    future whenever the app and database timezones differ.
    """
    with get_db_con() as cur:
        cur.execute(
            "SELECT user_hash, feed_hash, name_hash FROM sources "
            "WHERE next_ingest_at <= NOW() + interval '1 minute' "
            "ORDER BY next_ingest_at ASC LIMIT 1 FOR UPDATE SKIP LOCKED"
        )
        row = cur.fetchone()

        if not row:
            return

        cur.execute(
            "UPDATE sources SET next_ingest_at = NOW() + "
            "make_interval(mins => COALESCE(ingest_interval_minutes, %s)) "
            "WHERE user_hash = %s AND feed_hash = %s AND name_hash = %s",
            (
                SOURCE_READ_INTERVAL_MINUTES,
                row["user_hash"],
                row["feed_hash"],
                row["name_hash"],
            ),
        )

    source = None
    try:
        source = Source.read(
            user_hash=row["user_hash"],
            feed_hash=row["feed_hash"],
            source_hash=row["name_hash"],
        )
        logging.info(f"Ingesting source '{source.name}' ({source.url})")
        ingest_source(source=source)
        source.mark_ingested()
    except Exception as e:
        logging.exception(f"Ingesting of source {row['name_hash']} failed: {e}")
        if source is not None:
            source.mark_ingest_error(str(e))
        return


def ingest_source_now(source: Source) -> None:
    """Ingest a freshly-added source immediately (outside the schedule).

    Pushes the next scheduled run out first so the interval job doesn't
    double-ingest, then runs the ingest inline.
    """
    source.push_next_ingest()
    try:
        logging.info(f"Ingesting new source '{source.name}' ({source.url})")
        ingest_source(source=source)
        source.mark_ingested()
    except Exception as e:
        logging.exception(f"Initial ingest of source '{source.name}' failed: {e}")
        source.mark_ingest_error(str(e))


def _feeds_with_votes_on(url_hash: str) -> set:
    """(user_hash, feed_hash) pairs that have cast a vote on this item."""
    with get_db_con() as cur:
        cur.execute(
            "SELECT DISTINCT user_hash, feed_hash FROM item_states "
            "WHERE item_url_hash = %s AND score IS NOT NULL",
            (url_hash,),
        )
        return {(row["user_hash"], row["feed_hash"]) for row in cur.fetchall()}


def rescrape_source(source: Source) -> None:
    """Re-scrape a source's existing items for content, images, and preview
    media, and regenerate embeddings, WITHOUT re-fetching the RSS feed.

    Each item's scrapers (reddit / open graph / mercury) are re-run and merged
    over the stored item, so gaps get backfilled and better content/media wins
    while nothing already stored is lost. When an item's re-collected data
    actually changed and the item carries a vote, the affected feeds are
    re-ranked so their models retrain on the fresh features.
    """
    from ranking.engine import rank_feed  # local import avoids an import cycle

    embedding_model = config.get("OLLAMA_EMBEDDING_MODEL", None)
    image_embed_host = config.get("IMAGE_EMBED_HOST", None)
    image_embed_model = config.get("IMAGE_EMBED_MODEL")
    feeds_to_rerank: set = set()

    for item in source.query_items():
        try:
            before = {f: getattr(item, f) for f in _RESCRAPE_FIELDS}

            merged = ItemLoose.merge_instances(
                items=[
                    item,
                    ingest_reddit_item(item),
                    ingest_open_graph_item(item),
                    ingest_mercury_item(item),
                ]
            )
            # merge_instances doesn't carry embeddings over; keep the existing
            # ones so a re-scrape never drops them
            merged.embeddings = item.embeddings
            merged.image_embeddings = item.image_embeddings

            after = {f: getattr(merged, f) for f in _RESCRAPE_FIELDS}
            text_changed = any(
                after[f] != before[f] for f in _EMBEDDING_TEXT_FIELDS
            )
            image_changed = after["image_url"] != before["image_url"]

            embedding_changed = False
            if text_changed and embedding_model is not None:
                try:
                    merged.add_embedding(
                        model_name=embedding_model, force_refresh=True
                    )
                    embedding_changed = merged.embeddings != item.embeddings
                except Exception as e:
                    logging.error(f"Error re-embedding item {item.url}: {e}")

            if image_changed and image_embed_host is not None:
                try:
                    merged.add_image_embedding(
                        model_name=image_embed_model, force_refresh=True
                    )
                    embedding_changed = (
                        embedding_changed
                        or merged.image_embeddings != item.image_embeddings
                    )
                except Exception as e:
                    logging.error(f"Error re-embedding image {item.url}: {e}")

            if after == before and not embedding_changed:
                continue  # nothing changed, leave the row untouched

            merged.update()  # persist (overwrites the existing row)

            # a changed, voted-on item means the models that trained on its old
            # features are now stale — schedule those feeds to retrain
            feeds_to_rerank |= _feeds_with_votes_on(item.url_hash)
        except Exception as e:
            logging.exception(f"Re-scrape of item {item.url} failed: {e}")

    for user_hash, feed_hash in feeds_to_rerank:
        feed = Feed.read(user_hash=user_hash, name_hash=feed_hash)
        if feed is None:
            continue
        try:
            rank_feed(feed)
        except Exception as e:
            logging.exception(f"Re-ranking feed {feed.name} after re-scrape failed: {e}")

    logging.info(
        f"Re-scraped source '{source.name}': "
        f"{len(feeds_to_rerank)} feed(s) retrained"
    )


def download_embedding_model_job() -> None:
    embedding_model = config.get("OLLAMA_EMBEDDING_MODEL", None)

    if embedding_model is None:
        return

    ollama = get_ollama_connection()

    models = ollama.list()
    if embedding_model not in models:
        ollama.pull(embedding_model)


def backfill_image_embeddings_job() -> None:
    """One-shot at startup: embed the preview image of every stored item that's
    missing an embedding for the current CLIP model. New items are embedded at
    ingest time, but this catches everything scraped before the service existed
    (or before the model changed). No-op when the service isn't configured."""
    image_embed_host = config.get("IMAGE_EMBED_HOST", None)
    if image_embed_host is None:
        return
    model_name = config.get("IMAGE_EMBED_MODEL")

    with get_db_con() as cur:
        cur.execute(
            "SELECT url_hash FROM items WHERE image_url IS NOT NULL "
            "AND (image_embeddings IS NULL "
            "OR NOT jsonb_exists(image_embeddings, %s))",
            (model_name,),
        )
        url_hashes = [row["url_hash"] for row in cur.fetchall()]

    if not url_hashes:
        return

    logging.info(f"Backfilling image embeddings for {len(url_hashes)} item(s)...")
    done = 0
    for url_hash in url_hashes:
        item = ItemLoose.read(url_hash)
        if item is None:
            continue
        try:
            item.add_image_embedding(model_name=model_name)
            if item.image_embeddings and model_name in item.image_embeddings:
                item.update()
                done += 1
        except Exception as e:
            logging.error(f"Error backfilling image embedding for {item.url}: {e}")

    logging.info(f"Image embedding backfill complete: {done}/{len(url_hashes)} embedded.")
