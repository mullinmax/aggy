import logging
import feedparser
import requests
from config import config
from db.item import ItemLoose, ItemStrict
from db.source import Source
from db.feed import Feed
from ingest.item.rss import ingest_rss_item
from ingest.item.open_graph import ingest_open_graph_item
from ingest.item.mercury import ingest_mercury_item


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
    try:
        response = requests.get(str(source.url), timeout=60, headers=headers)
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
                continue

        # generate embedding if a model is configured and it doesn't exist yet
        embedding_model = config.get("OLLAMA_EMBEDDING_MODEL", None)
        if embedding_model is not None:
            try:
                final_item.add_embedding(model_name=embedding_model)
            except Exception as e:
                logging.error(f"Error adding embedding to item: {e}")

        # write item to db
        try:
            final_item.create()
        except Exception as e:
            logging.error(f"Error creating item: {e}")
            continue

        source.add_items(final_item)
        feed = Feed.read(user_hash=source.user_hash, name_hash=source.feed_hash)
        feed.add_items(final_item)
