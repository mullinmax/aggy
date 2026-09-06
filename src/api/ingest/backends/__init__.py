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
from ingest.errors import IngestError

from . import html, manual, rss, ytdlp


class Backend:
    def __init__(self, module: ModuleType, enrich: bool, scheduled: bool = True):
        self.module = module
        # Whether sources of this kind are polled on a schedule at all. A
        # manual source has nothing to fetch, and putting it in the ingest
        # queue would only mark it failed for returning no entries.
        self.scheduled = scheduled
        # Whether to run the per-item scrapers (reddit / open graph / mercury)
        # over what this backend produced. Backends that already return
        # complete metadata for sites that refuse anonymous scraping switch it
        # off rather than spend a request per item to learn nothing.
        self.enrich = enrich

    def fetch_items(self, source: Source) -> List[ItemLoose]:
        # looked up on the module per call, so a backend stays substitutable
        return self.module.fetch_items(source)

    def enrich_item(self, item):
        """A backend's own chance to top up an item.

        Called when an item is first seen, and again on an explicit
        re-collect — never on every check, since it costs a request per
        article. Backends with nothing to add don't define it.
        """
        hook = getattr(self.module, "enrich_item", None)
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
    "manual": Backend(module=manual, enrich=True, scheduled=False),
}

DEFAULT_KIND = "rss"

# Kinds that are never polled: their sources are filled in by hand, so the
# ingest queue skips them entirely.
UNSCHEDULED_KINDS = [
    kind for kind, backend in BACKENDS.items() if not backend.scheduled
]


def get_backend(kind: str) -> Backend:
    backend = BACKENDS.get(kind)
    if backend is None:
        raise IngestError(
            f"Unknown source kind '{kind}' "
            f"(expected one of {', '.join(sorted(BACKENDS))})"
        )
    return backend
