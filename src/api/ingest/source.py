import logging
import feedparser
import requests
from config import config
from db.item import ItemLoose, ItemStrict
from db.source import Source
from db.feed import Feed
from db.propagation import propagate_items
from ingest.item.rss import ingest_rss_item
from ingest.item.reddit import ingest_reddit_item, is_reddit_post
from ingest.reddit_rate_limit import is_reddit_url, reddit_get
from ingest.item.open_graph import ingest_open_graph_item
from ingest.item.mercury import ingest_mercury_item


def _embedded_models(item: ItemStrict) -> tuple:
    """Which models this item already carries embeddings for.

    Compared before and after the embedding step to tell whether an ingest
    pass actually added anything to an item that was already stored, so a feed
    full of unchanged items doesn't rewrite every row on every check.
    """
    return (
        tuple(sorted(item.embeddings or {})),
        tuple(sorted(item.image_embeddings or {})),
    )


def ingest_source(source: Source) -> None:
    # Fetch the feed ourselves so failures produce a useful error instead of
    # feedparser silently returning zero entries (rss-bridge answers bad
    # parameters with an HTML error page, for example). A descriptive
    # User-Agent matters: reddit.com and others rate-limit anonymous/default
    # agents far more aggressively.
    headers = {
        "User-Agent": (
            f"aggy/{config.get('BUILD_VERSION')} "
            "(self-hosted feed aggregator; +https://github.com/mullinmax/aggy)"
        )
    }
    # reddit.com requests share a global adaptive throttle so all ingest jobs
    # stay under one budget and back off together on 429s.
    fetch = reddit_get if is_reddit_url(source.url) else requests.get
    try:
        response = fetch(str(source.url), timeout=60, headers=headers)
    except requests.RequestException as e:
        raise Exception(f"Could not fetch feed: {e}") from e

    if response.status_code == 429:
        retry_after = response.headers.get("Retry-After")
        detail = f", retry after {retry_after}s" if retry_after else ""
        raise Exception(f"Rate limited by feed server (HTTP 429{detail})")

    if response.status_code != 200:
        raise Exception(f"Feed request returned HTTP {response.status_code}")

    parsed = feedparser.parse(response.content)
    entries = parsed.entries

    if not entries:
        detail = ""
        if parsed.bozo and parsed.get("bozo_exception"):
            detail = f" ({parsed.bozo_exception})"
        raise Exception(f"Feed returned no entries{detail}")

    # rss-bridge reports bridge failures as a 200 OK feed containing a single
    # item titled "Bridge returned error <code>! (<id>)". Treat that as a
    # failed ingest instead of ingesting the error as an article.
    bridge_errors = [
        e for e in entries if str(e.get("title", "")).startswith("Bridge returned error")
    ]
    if bridge_errors:
        raise Exception(f"rss-bridge failed: {bridge_errors[0].get('title')}")

    logging.info(f"Source '{source.name}': feed has {len(entries)} entries")

    feed = Feed.read(user_hash=source.user_hash, name_hash=source.feed_hash)
    ingested_url_hashes: list[str] = []
    new_items = 0
    stored_items = 0

    for entry in entries:
        # if the item already exists in the database, skip scraping
        temp_item = ItemLoose(url=entry.link)
        already_stored = temp_item.exists()
        if already_stored:
            stored_items += 1

            # TODO check how long ago we ingested this item and re-ingest if it's been long enough
            final_item = ItemStrict.read(url_hash=temp_item.url_hash)
            if final_item is None:
                continue

            # Items ingested before the reddit media scraper existed only
            # have the RSS thumbnail; backfill galleries/gifs/videos from
            # the post JSON. An empty list marks "scraped, no media" so
            # text posts aren't re-fetched every cycle.
            if final_item.media is None and is_reddit_post(str(final_item.url)):
                reddit_item = ingest_reddit_item(final_item)
                if reddit_item is not None:
                    final_item.update(
                        media=reddit_item.media or [],
                        image_url=reddit_item.image_url or final_item.image_url,
                    )
        else:
            new_items += 1
            rss_item = ingest_rss_item(entry)
            # reddit's post JSON has full-res images, gifs, videos, and
            # galleries that the RSS feed only thumbnails; merge it in ahead
            # of open graph so its media wins
            reddit_item = ingest_reddit_item(rss_item)
            open_graph_item = ingest_open_graph_item(rss_item)
            mercury_item = ingest_mercury_item(rss_item)

            best_item = ItemLoose.merge_instances(
                items=[rss_item, reddit_item, open_graph_item, mercury_item]
            )

            # Attempt to make strict item from best of all
            try:
                final_item = ItemStrict(**best_item.dict())
            except Exception:
                logging.error("failed to parse best item into strict item")
                logging.error(str(best_item))
                # TODO make sure we don't attempt this url over and over
                continue

        embedded_before = _embedded_models(final_item)

        # generate embedding if a model is configured and it doesn't exist yet
        embedding_model = config.get("OLLAMA_EMBEDDING_MODEL", None)
        if embedding_model is not None:
            try:
                final_item.add_embedding(model_name=embedding_model)
            except Exception as e:
                logging.error(f"Error adding embedding to item: {e}")

        # and an image embedding, when the CLIP service is configured and the
        # item has a preview image
        if config.get("IMAGE_EMBED_HOST", None) is not None:
            try:
                final_item.add_image_embedding(
                    model_name=config.get("IMAGE_EMBED_MODEL")
                )
            except Exception as e:
                logging.error(f"Error adding image embedding to item: {e}")

        # Write the item to the db. An item that was already stored is updated
        # in place, and only when this pass actually produced an embedding it
        # didn't have -- calling create() on it raises "already exists", which
        # used to abort the rest of this loop body: the item never got linked
        # to this source and feed, and any embedding just computed for it was
        # thrown away and recomputed from scratch on every later check.
        try:
            if not already_stored:
                final_item.create()
            elif _embedded_models(final_item) != embedded_before:
                final_item.update()
        except Exception as e:
            logging.error(f"Error saving item {final_item.url}: {e}")
            continue

        # Linking is idempotent, so re-running it for an item this source
        # already carries is a no-op -- but it's what attaches items that
        # another feed ingested first, which no later pass would fix.
        source.add_items(final_item)
        feed.add_items(final_item)
        ingested_url_hashes.append(final_item.url_hash)

    logging.info(
        f"Source '{source.name}': {new_items} new item(s), "
        f"{stored_items} already stored"
    )

    # Mirror everything this source produced into any feed that uses this feed
    # as a source (and on down the chain). Cheap no-op for items already there.
    if ingested_url_hashes:
        propagate_items(source.user_hash, source.feed_hash, ingested_url_hashes)
