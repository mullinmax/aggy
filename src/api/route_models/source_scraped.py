from typing import Dict

from .base import BaseRouteModel


class ScrapedSourceCreate(BaseRouteModel):
    feed_hash: str
    source_name: str
    # The selectors approved in the analysis preview: home_page,
    # entry_element_selector, title_selector, url_selector, and friends.
    parameters: Dict[str, str]
    # Whether the page has to go through the headless renderer to show its
    # articles. Set by the analyzer when the raw HTML had none.
    rendered: bool = True

    model_config = {
        "json_schema_extra": {
            "example": {
                "feed_hash": "feed_hash_456",
                "source_name": "Example Blog",
                "parameters": {
                    "home_page": "https://example.com/blog/",
                    "entry_element_selector": "div.article",
                    "title_selector": "h2",
                    "url_selector": "a",
                    "limit": "10",
                },
                "rendered": True,
            }
        }
    }
