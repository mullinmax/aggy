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

    for candidate in candidates:
        # if the item already exists in the database, skip scraping
        already_stored = candidate.exists()
        if already_stored:
            logging.info(f"Item already exists in database: {candidate.url}")

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

            # the backend's own turn to fill gaps, now that we know this
            # article is new and worth spending a request on
            final_item = backend.enrich_new_item(final_item) or final_item

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

        # write item to db. An item already in the table is updated rather than
        # inserted: create() refuses to overwrite, and treating that as a
        # failure used to skip the attachment below — so an article another
        # source had already stored never showed up in this one's feed.
        try:
            if already_stored:
                final_item.update()
            else:
                final_item.create()
        except Exception as e:
            logging.error(f"Error storing item {final_item.url}: {e}")
            continue

        source.add_items(final_item)
        feed.add_items(final_item)
        ingested_url_hashes.append(final_item.url_hash)

    # Mirror everything this source produced into any feed that uses this feed
    # as a source (and on down the chain). Cheap no-op for items already there.
    if ingested_url_hashes:
        propagate_items(source.user_hash, source.feed_hash, ingested_url_hashes)
