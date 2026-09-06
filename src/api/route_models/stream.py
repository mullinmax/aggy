from typing import Optional

from .base import BaseRouteModel


class StreamUrlResponse(BaseRouteModel):
    # A playable media URL, freshly resolved. Usually signed and short-lived,
    # so it is meant to be used immediately and never stored.
    url: str
    ext: Optional[str] = None
    height: Optional[int] = None
    protocol: Optional[str] = None
    # True when the URL is an HLS playlist rather than a plain media file:
    # the player has to load it itself everywhere except Safari, which plays
    # HLS natively.
    is_hls: bool = False
    title: Optional[str] = None
    duration: Optional[float] = None
    poster: Optional[str] = None
