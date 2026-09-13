"""Short-lived permission slips for the media proxy.

A `video` element cannot send an Authorization header: whatever the browser
is pointed at has to carry its own credential in the URL. So a ticket is a
signed statement of "this user may pull exactly this URL, until then", handed
out by `/item/stream_url` and checked by the proxy.

Signing them with the login secret directly would make every ticket a bearer
token, and tickets travel in URLs - they land in browser history, in a
referer header, in an access log. Instead they are signed with a key derived
from it, so a ticket cannot be presented as a login and a login cannot be
presented as a ticket.
"""

import hashlib
import hmac
from datetime import datetime, timedelta, timezone
import jwt

from config import config

# Long enough for someone to finish watching, short enough that a leaked URL
# is worth little. The signed URL it wraps usually expires sooner anyway.
TICKET_TTL_SECONDS = 6 * 60 * 60

_DERIVATION_LABEL = b"aggy-media-proxy-v1"


class InvalidTicket(Exception):
    """The ticket was forged, expired, or is not a media ticket."""


def _secret() -> str:
    return hmac.new(
        str(config.get("JWT_SECRET")).encode(), _DERIVATION_LABEL, hashlib.sha256
    ).hexdigest()


def _algorithm() -> str:
    return config.get("JWT_ALGORITHM") or "HS256"


def mint(url: str, user_hash: str, item_url_hash: str) -> str:
    """A ticket for one URL, on behalf of one user, for one item.

    The item comes along because the proxy has to fetch as the source did:
    the cookie that got past the site's door is looked up from it, server
    side, rather than being written into a URL.
    """
    claims = {
        "url": str(url),
        "user": user_hash,
        "item": item_url_hash,
        "exp": datetime.now(timezone.utc) + timedelta(seconds=TICKET_TTL_SECONDS),
    }
    return jwt.encode(claims, _secret(), algorithm=_algorithm())


def verify(ticket: str) -> dict:
    """The claims of a ticket this server signed, or `InvalidTicket`."""
    try:
        claims = jwt.decode(ticket, _secret(), algorithms=[_algorithm()])
    except jwt.ExpiredSignatureError as e:
        raise InvalidTicket("This playback link has expired") from e
    except jwt.PyJWTError as e:
        raise InvalidTicket("This playback link is not valid") from e

    if not claims.get("url"):
        raise InvalidTicket("This playback link is not valid")
    return claims


def url_for(ticket: str) -> str:
    return f"/item/stream?ticket={ticket}"
