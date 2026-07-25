from typing import Optional

from .base import BaseRouteModel


class StreamUrlResponse(BaseRouteModel):
    # A playable media URL, freshly resolved. Usually signed and short-lived,
    # so it is meant to be used immediately and never stored.
    url: str
    ext: Optional[str] = None
    height: Optional[int] = None
    protocol: Optional[str] = None
    title: Optional[str] = None
    duration: Optional[float] = None
    poster: Optional[str] = None
