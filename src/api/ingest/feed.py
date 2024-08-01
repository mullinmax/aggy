import logging
import feedparser
from db.item import ItemLoose, ItemStrict
from db.feed import Feed
from db.category import Category
from ingest.item.rss import ingest_rss_item
from ingest.item.open_graph import ingest_open_graph_item
from ingest.item.mercury import ingest_mercury_item


# TODO maybe this belongs in the feed DB model
def ingest_feed(feed: Feed) -> None:
    entries = feedparser.parse(str(feed.url)).entries

    items_to_link = []
    for entry in entries:
        temp_item = ItemLoose(url=entry.link)
        if temp_item.exists():
            logging.info(f"Item already exists in database: {entry.link}")
            items_to_link.append(temp_item)
            continue

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

        try:
            final_item.create()
        except Exception as e:
            logging.error(f"Error creating item: {e}")
            continue

        items_to_link.append(final_item)

    feed.add_items(items_to_link)
    category = Category.read(user_hash=feed.user_hash, name_hash=feed.category_hash)
    category.add_items(items_to_link)
