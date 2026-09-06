import logging
from typing import Optional
import requests
from bs4 import BeautifulSoup

from db.item import ItemLoose


def ingest_open_graph_item(item: ItemLoose) -> Optional[ItemLoose]:
    try:
        response = requests.get(str(item.url), timeout=10)
    except requests.RequestException as e:
        # A page that refuses us, times out, or has gone away is the ordinary
        # case here, and it happens once per article: a stack trace each time
        # would bury everything else in the log for a single dead site.
        logging.info(f"No open graph data for {item.url}: {e}")
        return None
    except Exception as e:
        logging.exception(f"Fetching open graph data for {item.url} failed: {e}")
        return None
    soup = BeautifulSoup(response.text, "html.parser")
    og_tags = soup.find_all(
        "meta", attrs={"property": lambda x: x and x.startswith("og:")}
    )
    og_data = {
        tag["property"].replace("og:", ""): tag["content"]
        for tag in og_tags
        if "content" in tag.attrs
    }

    # https://ogp.me/
    return ItemLoose(
        url=item.url,
        image_url=og_data.get("image"),
        domain=og_data.get("site_name"),
        excerpt=og_data.get("description"),
        content=og_data.get("description"),
        title=og_data.get("title"),
        # future video url for embedding a web player?
        # video = og_data['video'] # https://youtube.com/slightly/different/url
        # type = og_data['type'] # "video"
        # embeddable audio file?
        # audio = og_data['audio']
    )
