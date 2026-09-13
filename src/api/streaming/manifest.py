"""Pointing an HLS playlist back at this server.

An HLS stream is a text playlist naming other URLs: more playlists, media
segments, an encryption key. The browser resolves those against wherever it
fetched the playlist from, so a playlist served through the proxy while its
segments still name the CDN would only move the problem one hop down - the
segments would be fetched direct and refused for the same reason the playlist
was.

So every URL a playlist names is rewritten to come back here too. Relative
ones are resolved against the playlist's real address first, since that is
what the browser would have done.
"""

import re
from typing import Callable
from urllib.parse import urljoin

# `#EXT-X-KEY:METHOD=AES-128,URI="https://.../key"` and friends: the tags that
# carry a URL inside an attribute list rather than on a line of their own.
_ATTRIBUTE_URI = re.compile(r'(URI=")([^"]+)(")')

# Playlists are text, and a huge one means something other than a playlist.
MAX_MANIFEST_BYTES = 4 * 1024 * 1024

_MANIFEST_CONTENT_TYPES = (
    "application/vnd.apple.mpegurl",
    "application/x-mpegurl",
    "audio/mpegurl",
    "audio/x-mpegurl",
)


def looks_like_manifest(url: str, content_type: str = "") -> bool:
    """Whether a response body should be read and rewritten rather than piped.

    The content type is what a well-behaved CDN says; the extension is the
    fallback for the ones that serve playlists as `text/plain` or with no
    type at all.
    """
    kind = (content_type or "").split(";")[0].strip().lower()
    if kind in _MANIFEST_CONTENT_TYPES:
        return True
    path = str(url).split("?", 1)[0].split("#", 1)[0].lower()
    return path.endswith(".m3u8") or path.endswith(".m3u")


def rewrite(body: str, base_url: str, proxy_for: Callable[[str], str]) -> str:
    """Every URL in a playlist, replaced by one that comes back through us.

    `proxy_for` takes an absolute URL and returns the address to use instead.
    """
    lines = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            lines.append(line)
        elif stripped.startswith("#"):
            lines.append(
                _ATTRIBUTE_URI.sub(
                    lambda match: (
                        match.group(1)
                        + proxy_for(urljoin(base_url, match.group(2)))
                        + match.group(3)
                    ),
                    line,
                )
            )
        else:
            # a bare line is a URL: a variant playlist or a media segment
            lines.append(proxy_for(urljoin(base_url, stripped)))
    # playlists end with a newline; splitlines drops whichever one was there
    return "\n".join(lines) + "\n"
