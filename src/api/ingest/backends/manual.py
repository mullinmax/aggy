"""The backend for sources nothing fetches.

A manual source is filled in by hand — the browser extension saving a page,
and anything else that files an article directly — so there is no URL to poll.
It exists so those articles are attributed to something the feed can filter,
color, and count like any other source.
"""

from typing import List

from db.item import ItemLoose
from db.source import Source


def fetch_items(source: Source) -> List[ItemLoose]:
    return []
