"""Ingest backends: the different ways a source becomes a list of items.

A source names its backend in ``Source.kind``. Each backend is responsible
only for producing candidate :class:`ItemLoose` objects; deduplication,
scraping, embedding, and storage are the shared pipeline in
``ingest.source.ingest_source``.

Adding a backend means writing a module with a ``fetch_items(source)`` and
registering it here.
"""

import logging
from types import ModuleType
from typing import List

from db.item import ItemLoose
from db.source import Source

from . import html, rss, ytdlp


class Backend:
    def __init__(self, module: ModuleType, enrich: bool):
        self.module = module
        # Whether to run the per-item scrapers (reddit / open graph / mercury)
        # over what this backend produced. Backends that already return
        # complete metadata for sites that refuse anonymous scraping switch it
        # off rather than spend a request per item to learn nothing.
        self.enrich = enrich

    def fetch_items(self, source: Source) -> List[ItemLoose]:
        # looked up on the module per call, so a backend stays substitutable
        return self.module.fetch_items(source)

    def enrich_new_item(self, item):
        """A backend's own chance to top up an item it has just discovered.

        Only called for items not already stored, so the cost is paid once per
        article rather than on every check. Backends that have nothing to add
        don't define it.
        """
        hook = getattr(self.module, "enrich_new_item", None)
        if hook is None:
            return None
        try:
            return hook(item)
        except Exception as e:
            logging.error(f"Enriching {item.url} failed: {e}")
            return None


BACKENDS = {
    "rss": Backend(module=rss, enrich=True),
    "ytdlp": Backend(module=ytdlp, enrich=False),
    "html": Backend(module=html, enrich=True),
}

DEFAULT_KIND = "rss"


def get_backend(kind: str) -> Backend:
    backend = BACKENDS.get(kind)
    if backend is None:
        raise Exception(
            f"Unknown source kind '{kind}' "
            f"(expected one of {', '.join(sorted(BACKENDS))})"
        )
    return backend
