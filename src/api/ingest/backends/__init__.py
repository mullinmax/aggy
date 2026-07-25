"""Ingest backends: the different ways a source becomes a list of items.

A source names its backend in ``Source.kind``. Each backend is responsible
only for producing candidate :class:`ItemLoose` objects; deduplication,
scraping, embedding, and storage are the shared pipeline in
``ingest.source.ingest_source``.

Adding a backend means writing a module with a ``fetch_items(source)`` and
registering it here.
"""

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
