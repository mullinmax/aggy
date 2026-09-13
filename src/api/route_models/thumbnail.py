from .base import BaseRouteModel


class ThumbnailResponse(BaseRouteModel):
    # A picture for this item that is known to load right now, fetched
    # through this server. Asked for only when the stored one didn't.
    url: str
