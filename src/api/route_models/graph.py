"""The feed's similarity graph, as the graph view draws it.

Deliberately not ``ItemResponse``: a node is a dot on a canvas, and shipping
every article's sanitised HTML body to draw a thousand dots would be most of the
payload for none of the picture. What is here is what the drawing and its detail
card need -- enough to size a node, colour it, label it, show a thumbnail of it,
and open it.

The article's body is the one thing left out, which is why opening one from the
graph fetches it: see ``GET /feed/item``.
"""

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import HttpUrl

from .base import BaseRouteModel


class GraphNodeResponse(BaseRouteModel):
    item_hash: str
    item_url: HttpUrl
    item_title: Optional[str] = None
    item_date_published: Optional[datetime] = None
    # Colour comes from the source, the same one its badge uses in the feed.
    item_source_name: Optional[str] = None
    item_source_color: Optional[str] = None
    # Enough to put a picture on the detail card. The card shows a still and a
    # play badge rather than a working player -- a video in a 288px card beside
    # the graph is not where anyone wants to watch one, and opening it gives
    # the reader, which plays it properly.
    item_image_url: Optional[str] = None
    item_media: Optional[List[Dict[str, Optional[str]]]] = None
    # Size comes from the prediction. Null for an article the model has not
    # scored yet, which the view draws at its smallest rather than guessing.
    item_predicted_score: Optional[float] = None
    item_predicted_confidence: Optional[float] = None
    # A real vote, when there is one. Never folded into the predicted score:
    # what you actually said and what the model guessed are different things.
    item_user_score: Optional[float] = None
    item_is_read: Optional[bool] = None
    # The duplicate group this article is in, so copies of one story can be
    # picked out of the picture.
    item_duplicate_group: Optional[str] = None


class GraphEdgeResponse(BaseRouteModel):
    """One undirected link. ``source`` and ``target`` are article hashes, and
    which is which carries no meaning -- the pair is ordered so that the two
    stored directions fold into one line."""

    source: str
    target: str
    similarity: float


class FeedGraphResponse(BaseRouteModel):
    nodes: List[GraphNodeResponse]
    edges: List[GraphEdgeResponse]
    # How many articles the feed holds in total, so the view can say when it is
    # showing a window of a larger thing rather than the whole feed.
    total_items: int
