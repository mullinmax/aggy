import requests
from bs4 import BeautifulSoup

from db.item import ItemLoose


def ingest_open_graph_item(item: ItemLoose) -> ItemLoose:
    response = requests.get(item.url)
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
