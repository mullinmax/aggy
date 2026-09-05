import logging
import json
from typing import Optional
import requests

from config import config
from db.item import ItemLoose


def ingest_mercury_item(item: ItemLoose) -> Optional[ItemLoose]:
    headers = json.dumps({"User-Agent": "Mozilla/5.0"})

    try:
        res = requests.get(
            f"http://{config.get('EXTRACT_HOST')}:{config.get('EXTRACT_PORT')}/parser/",
            params={"url": str(item.url), "headers": headers},
            timeout=10,
        )

        if res.status_code != 200:
            # The extractor answers non-200 for any page it cannot read, which
            # is a routine outcome for one article among many; its body is
            # often a whole HTML error page, so only the start of it is useful.
            logging.info(
                f"No extracted content for {item.url}: "
                f"HTTP {res.status_code} {res.text.strip()[:200]}"
            )
            return None

        item_dict = res.json()
        item_dict["url"] = item.url  # make sure url matches the entry

        return ItemLoose(**item_dict)
    except (requests.RequestException, ValueError) as e:
        # unreachable extractor, or an answer that wasn't the JSON it promised
        logging.info(f"No extracted content for {item.url}: {e}")
        return None
    except Exception as e:
        logging.exception(f"Extracting content for {item.url} failed: {e}")
        return None
