import logging
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

from constants import SOURCE_READ_INTERVAL_MINUTES
from db.base import get_db_con
from db.feed import Feed
from db.item import (
    ImageEmbedError,
    ItemLoose,
    embed_image,
    embeddable_image_url,
    image_embed_backfill_candidates,
    record_image_embed_failure,
    reset_image_embed_attempts,
    save_image_embedding,
)
from db.source import Source
from db.source_attempt import (
    OUTCOME_ERROR,
    OUTCOME_OK,
    OUTCOME_SKIPPED,
    prune_attempts,
    record_attempt,
)
from ingest import host_circuit
from ingest.backends import UNSCHEDULED_KINDS, get_backend
from ingest.host_circuit import HostUnavailable, source_host
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
                # a manual source (saved links) has no URL to poll
                if not get_backend(source.kind).scheduled:
                    continue
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
            "AND kind <> ALL(%s) "
            "ORDER BY next_ingest_at ASC LIMIT 1 FOR UPDATE SKIP LOCKED",
            (UNSCHEDULED_KINDS,),
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
        _ingest_with_circuit(source)
        source.mark_ingested()
    except HostUnavailable as e:
        # Not a failure of this source: its site is in cooldown and was never
        # contacted. Logged at info because a broken site produces one of these
        # per source per cycle, and they are the breaker working, not news.
        logging.info(f"Skipping source '{source.name}': {e}")
        source.mark_ingest_error(str(e))
        return
    except Exception as e:
        logging.exception(f"Ingesting of source {row['name_hash']} failed: {e}")
        if source is not None:
            source.mark_ingest_error(str(e))
        return


def _ingest_with_circuit(source: Source) -> None:
    """Ingest a source, reporting the outcome to the per-site breaker.

    Feed sources are exempt: they read another feed out of our own database
    rather than fetching a site, so there is no host whose reliability they
    could speak to.
    """
    if source.is_feed_source:
        ingest_source(source=source)
        return

    host = source_host(str(source.url))

    try:
        host_circuit.check(str(source.url))
    except HostUnavailable:
        record_attempt(
            user_hash=source.user_hash,
            feed_hash=source.feed_hash,
            source_hash=source.name_hash,
            host=host,
            outcome=OUTCOME_SKIPPED,
        )
        raise

    try:
        ingest_source(source=source)
    except Exception as e:
        host_circuit.record_failure(str(source.url))
        record_attempt(
            user_hash=source.user_hash,
            feed_hash=source.feed_hash,
            source_hash=source.name_hash,
            host=host,
            outcome=OUTCOME_ERROR,
            error=str(e),
        )
        raise

    host_circuit.record_success(str(source.url))
    record_attempt(
        user_hash=source.user_hash,
        feed_hash=source.feed_hash,
        source_hash=source.name_hash,
        host=host,
        outcome=OUTCOME_OK,
    )


def prune_ingest_attempts_job() -> None:
    """Drop ingest attempts that have aged out of the retention window."""
    try:
        deleted = prune_attempts()
    except Exception as e:
        logging.error(f"Pruning ingest attempt history failed: {e}")
        return
    if deleted:
        logging.info(f"Pruned {deleted} ingest attempt(s) from history")


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

    backend = get_backend(source.kind)
    embedding_model = config.get("OLLAMA_EMBEDDING_MODEL", None)
    image_embed_host = config.get("IMAGE_EMBED_HOST", None)
    image_embed_model = config.get("IMAGE_EMBED_MODEL")
    feeds_to_rerank: set = set()

    for item in source.query_items():
        try:
            before = {f: getattr(item, f) for f in _RESCRAPE_FIELDS}

            if backend.enrich:
                merged = ItemLoose.merge_instances(
                    items=[
                        item,
                        ingest_reddit_item(item),
                        ingest_open_graph_item(item),
                        ingest_mercury_item(item),
                    ]
                )
            else:
                # the generic scrapers have nothing to offer a backend that
                # says so, and the sites it reaches refuse them anyway
                merged = ItemLoose(**item.dict())
            # merge_instances doesn't carry embeddings over; keep the existing
            # ones so a re-scrape never drops them. Copied rather than shared:
            # add_embedding mutates the dict in place, so handing `merged` the
            # same object would also mutate `item` and leave the two comparing
            # equal — a freshly computed embedding would then look like "no
            # change" and never get written back.
            merged.embeddings = dict(item.embeddings) if item.embeddings else None
            merged.image_embeddings = (
                dict(item.image_embeddings) if item.image_embeddings else None
            )

            # a re-collect is the one other time a backend gets to top an item
            # up, which is how items stored before it could do so get their
            # pictures
            merged = backend.enrich_item(merged) or merged

            after = {f: getattr(merged, f) for f in _RESCRAPE_FIELDS}
            text_changed = any(after[f] != before[f] for f in _EMBEDDING_TEXT_FIELDS)
            image_changed = after["image_url"] != before["image_url"]

            embedding_changed = False
            if text_changed and embedding_model is not None:
                try:
                    merged.add_embedding(model_name=embedding_model, force_refresh=True)
                    embedding_changed = merged.embeddings != item.embeddings
                except Exception as e:
                    logging.error(f"Error re-embedding item {item.url}: {e}")

            # a re-scrape that turns up a different picture clears the old
            # one's failure history: those failures say nothing about the new
            # URL, and an item that had exhausted its retries would otherwise
            # stay out of the backfill queue forever
            if image_changed:
                reset_image_embed_attempts(item.url_hash)

            # a re-scrape is also a chance to fill in an embedding that never
            # landed (the image host was down, rate-limiting us, or refusing
            # the request), which no amount of unchanged re-scraping would
            # otherwise retry
            image_missing = image_embed_model not in (merged.image_embeddings or {})
            if (image_changed or image_missing) and image_embed_host is not None:
                try:
                    merged.add_image_embedding(
                        model_name=image_embed_model, force_refresh=image_changed
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
            logging.exception(
                f"Re-ranking feed {feed.name} after re-scrape failed: {e}"
            )

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


def _backfill_one_image(row: dict) -> tuple:
    """Embed one candidate row's preview image.

    Returns ``(embedding_or_None, error_or_None)``. Runs on a worker thread and
    takes no database connection of its own — results are written by the caller
    — so a wide fan-out can't drain the pool.
    """
    try:
        image_url = embeddable_image_url(row["image_url"], row["content"])
        if not image_url:
            # the candidate query matches "<img" anywhere in the content, which
            # a sanitized body can carry without a usable src; count it as a
            # failure so the row backs off instead of being re-picked each pass
            return None, "no embeddable image url"
        return embed_image(image_url), None
    except ImageEmbedError as e:
        return None, str(e)
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def _failure_summary(reasons: Counter) -> str:
    """The handful of reasons that account for a run's failures.

    One log line per failed image would bury everything else at this batch size,
    but "1,431 failed" on its own says nothing about whether the image hosts are
    rate-limiting us or the URLs are simply dead — which is the first thing
    worth knowing when coverage stops climbing.
    """
    return ", ".join(f"{count}x {reason}" for reason, count in reasons.most_common(3))


def _failure_reason(error: str) -> str:
    """Collapse a failure to something worth counting across a run.

    The stored error names the URLs it tried, which is exactly what makes every
    message unique and useless to tally; the parenthesised detail at the end is
    the part that repeats.
    """
    detail = error.rsplit("(", 1)[-1].rstrip(")").strip()
    return detail or error


def backfill_image_embeddings_job() -> None:
    """Embed the preview image of stored items missing an embedding for the
    current CLIP model.

    New items are embedded at ingest time, so this catches everything scraped
    before the service existed (or before the model changed) — plus every item
    whose image download failed at the time. Image hosts fail transiently (rate
    limits, timeouts, CDN hiccups), so a failed item is worth retrying; but
    plenty of them fail *permanently* — expired reddit signed URLs, deleted
    images, hosts that answer a scraper with HTML. Each attempt is therefore
    recorded on the row, and a failing item backs off exponentially before it is
    offered again, then drops out of the queue once it has burned through its
    attempts. Without that, a batch of permanently broken images is re-selected
    and re-failed on every single pass and the backlog behind them is never
    reached.

    Items are fetched a few at a time: the work is almost entirely waiting on
    image hosts, and a serial loop over a five-figure backlog never catches up.

    No-op when the service isn't configured.
    """
    if config.get("IMAGE_EMBED_HOST", None) is None:
        return

    model_name = config.get("IMAGE_EMBED_MODEL")
    rows = image_embed_backfill_candidates(
        model_name=model_name,
        limit=config.get_int("IMAGE_EMBED_BACKFILL_BATCH_SIZE"),
        max_attempts=config.get_int("IMAGE_EMBED_MAX_ATTEMPTS"),
        retry_minutes=config.get_float("IMAGE_EMBED_RETRY_MINUTES"),
        max_retry_minutes=config.get_float("IMAGE_EMBED_MAX_RETRY_MINUTES"),
    )

    if not rows:
        return

    concurrency = max(1, config.get_int("IMAGE_EMBED_BACKFILL_CONCURRENCY"))
    logging.info(
        f"Backfilling image embeddings for {len(rows)} item(s) "
        f"({concurrency} at a time)..."
    )

    embedded = 0
    reasons: Counter = Counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(_backfill_one_image, row): row for row in rows}
        for future in as_completed(futures):
            row = futures[future]
            embedding, error = future.result()
            try:
                if embedding is not None:
                    save_image_embedding(row["url_hash"], model_name, embedding)
                    embedded += 1
                else:
                    record_image_embed_failure(row["url_hash"], error)
                    reasons[_failure_reason(error)] += 1
            except Exception as e:
                logging.error(
                    f"Error recording image embedding result for {row['url']}: {e}"
                )

    failed = sum(reasons.values())
    logging.info(
        f"Image embedding backfill complete: {embedded} embedded, {failed} failed"
        + (f" ({_failure_summary(reasons)})" if failed else "")
    )
