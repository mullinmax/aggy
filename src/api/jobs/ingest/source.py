import logging
import feedparser
from config import config
from db.item import ItemLoose, ItemStrict
from db.source import Source
from db.feed import Feed
from .item.rss import ingest_rss_item
from .item.open_graph import ingest_open_graph_item
from .item.mercury import ingest_mercury_item
from utils import schedule
from constants import (
    SCORE_ESTIMATORS_TO_INFER_QUEUE,
    SCORE_ESTIMATE_INFERENCE_INTERVAL_TIMEDELTA,
)


def ingest_source(source: Source) -> None:
    feed = Feed.read(user_hash=source.user_hash, name_hash=source.feed_hash)

    entries = feedparser.parse(str(source.url)).entries

    for entry in entries:
        # if the item already exists in the database, skip scraping
        temp_item = ItemLoose(url=entry.link)
        if temp_item.exists():
            logging.info(f"Item already exists in database: {entry.link}")

            # TODO check how long ago we ingested this item and re-ingest if it's been long enough
            final_item = ItemStrict.read(url_hash=temp_item.url_hash)
        else:
            rss_item = ingest_rss_item(entry)
            open_graph_item = ingest_open_graph_item(rss_item)
            mercury_item = ingest_mercury_item(rss_item)

            best_item = ItemLoose.merge_instances(
                items=[rss_item, open_graph_item, mercury_item]
            )

            # Attempt to make strict item from best of all
            try:
                final_item = ItemStrict(**best_item.dict())
            except Exception:
                logging.error("failed to parse best item into strict item")
                logging.error(str(best_item))
                # TODO make sure we don't attempt this url over and over

        # generate embedding if it doesn't exist
        try:
            final_item.add_embedding(model_name=config.get("OLLAMA_EMBEDDING_MODEL"))
        except Exception as e:
            logging.error(f"Error adding embedding to item: {e}")

        # write item to db
        try:
            final_item.create()
        except Exception as e:
            logging.error(f"Error creating item: {e}")
            continue

        source.add_items(final_item)
        feed.add_items(final_item)

    # get these new items scored
    schedule(
        queue=SCORE_ESTIMATORS_TO_INFER_QUEUE,
        key=feed.key,
        interval=SCORE_ESTIMATE_INFERENCE_INTERVAL_TIMEDELTA,
        now=True,
    )
