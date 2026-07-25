import logging

from config import config
from db.item import ItemLoose, ItemStrict
from db.source import Source
from db.feed import Feed
from db.propagation import propagate_items
from ingest.backends import get_backend
from ingest.item.reddit import ingest_reddit_item, is_reddit_post
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
    """Fetch a source through its backend and store what comes back.

    The backend (see ``ingest.backends``) decides *how* a source becomes a
    list of items — a feed, a video site's listing, a scraped page. Everything
    after that is common to all of them: skip what's already stored, enrich
    with the per-item scrapers, embed, and attach to the source and feed.
    """
    backend = get_backend(source.kind)
    candidates = backend.fetch_items(source)

    if not candidates:
        raise Exception("Source returned no entries")

    feed = Feed.read(user_hash=source.user_hash, name_hash=source.feed_hash)
    ingested_url_hashes: list[str] = []
    new_items = 0
    stored_items = 0

    for candidate in candidates:
        # if the item already exists in the database, skip scraping
        already_stored = candidate.exists()
        if already_stored:
            stored_items += 1

            # TODO check how long ago we ingested this item and re-ingest if it's been long enough
            final_item = ItemStrict.read(url_hash=candidate.url_hash)
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
            if backend.enrich:
                # reddit's post JSON has full-res images, gifs, videos, and
                # galleries that the RSS feed only thumbnails; merge it in ahead
                # of open graph so its media wins
                best_item = ItemLoose.merge_instances(
                    items=[
                        candidate,
                        ingest_reddit_item(candidate),
                        ingest_open_graph_item(candidate),
                        ingest_mercury_item(candidate),
                    ]
                )
            else:
                best_item = candidate

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
