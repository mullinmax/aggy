import logging
import json
import requests

from config import config
from db.item import ItemLoose


def ingest_mercury_item(item: ItemLoose) -> ItemLoose:
    headers = json.dumps({"User-Agent": "Mozilla/5.0"})

    try:
        res = requests.get(
            f"http://{config.get('EXTRACT_HOST')}:{config.get('EXTRACT_PORT')}/parser/",
            params={"url": item.url, "headers": headers},
            timeout=10,
        )

        if res.status_code != 200:
            logging.error(
                "Mercury ingestion exception {entry.url}: {res.status_code}{res.text}"
            )

        item_dict = res.json()
        item_dict["url"] = item.url  # make sure url matches the entry

        return ItemLoose(**item_dict)
    except Exception as e:
        logging.error(f"Error extracting content: {e}")
