"""Reduce a URL to what actually identifies the content it points at.

The same article arrives under a different URL from every source that carries
it: one has the RSS reader's ``utm_source`` glued on, one is the AMP
rendition, one came through a Google News redirect. ``items.url_hash`` is a
hash of the raw URL, so each of those is a separate item and the feed shows
the same piece several times over.

``canonical_url`` strips everything that does not identify the content, so
those all collapse to one string. Two items with equal canonical URLs are the
same article -- the one duplicate signal that is effectively certain, which is
why it is matched on exact equality rather than any kind of distance.

The one rule this deliberately does *not* apply: an item's own URL is
canonicalised, never its outbound link target. A Reddit or Hacker News post
that links to an article shares a target URL with the article itself, but a
discussion of a piece is not the piece, and collapsing them would hide
whichever the model happened to score lower.
"""

from typing import Optional
from urllib.parse import (
    parse_qsl,
    quote,
    unquote,
    urlencode,
    urlparse,
    urlunparse,
)

# Query parameters that say where a click came from, never which article it
# landed on. Anything matching a _TRACKING_PREFIXES prefix goes too, which is
# what covers the open-ended utm_* family.
_TRACKING_PARAMS = frozenset(
    {
        "fbclid",
        "gclid",
        "dclid",
        "msclkid",
        "mc_cid",
        "mc_eid",
        "igshid",
        "si",
        "ref",
        "ref_src",
        "refsrc",
        "source",
        "spm",
        "__twitter_impression",
        "_hsenc",
        "_hsmi",
        "yclid",
        # AMP renditions are the same article; the marker only picks the
        # rendition.
        "amp",
        "usqp",
    }
)

_TRACKING_PREFIXES = ("utm_",)

# Hosts that serve nothing of their own: the real URL is in a query parameter.
# Unwrapping one and canonicalising what comes out is what makes a Google News
# link and the publisher's own link the same item.
#
# t.co and other shortener-style redirectors are deliberately absent: their
# target is only discoverable by following the redirect, which is a network
# fetch, and this has to stay a pure function so it can run at insert time.
_REDIRECT_HOSTS = {
    "news.google.com": ("url",),
    "out.reddit.com": ("url",),
    "www.google.com": ("url", "q"),
    "l.facebook.com": ("u",),
    "lm.facebook.com": ("u",),
    "away.vk.com": ("to",),
}

# A redirector can point at another redirector. Bounded so a URL that somehow
# points at itself cannot spin.
_MAX_UNWRAPS = 4

# AMP's own CDN: https://<publisher>.cdn.ampproject.org/c/s/<real host>/<path>
# The /c/ (or /v/) prefix is the rendition type and the /s/ says the origin is
# https.
_AMP_CDN_SUFFIX = ".cdn.ampproject.org"

_DEFAULT_PORTS = {"http": "80", "https": "443"}


def _is_tracking(name: str) -> bool:
    lowered = name.lower()
    return lowered in _TRACKING_PARAMS or lowered.startswith(_TRACKING_PREFIXES)


def _normalise_host(netloc: str, scheme: str) -> str:
    """Lowercase the host, drop a leading www. and a default port.

    Userinfo is kept as-is: it is not part of what identifies the content, but
    a URL carrying it is odd enough that silently rewriting it is worse than
    leaving it alone.
    """
    userinfo, _, hostport = netloc.rpartition("@")
    host, _, port = hostport.partition(":")
    host = host.lower()
    if host.startswith("www."):
        host = host[4:]
    if port and port == _DEFAULT_PORTS.get(scheme):
        port = ""
    out = f"{host}:{port}" if port else host
    return f"{userinfo}@{out}" if userinfo else out


def _strip_amp_path(path: str) -> str:
    """Drop ``amp`` path segments, the other half of AMP's URL conventions
    (``/news/amp/article``, ``/article/amp``)."""
    if "amp" not in path.lower():
        return path
    segments = [s for s in path.split("/") if s.lower() != "amp"]
    stripped = "/".join(segments)
    if path.startswith("/") and not stripped.startswith("/"):
        stripped = "/" + stripped
    return stripped


def _unwrap_amp_cdn(scheme: str, host: str, path: str) -> Optional[str]:
    """Turn an ampproject.org CDN URL back into the publisher's own.

    ``<pub>.cdn.ampproject.org/c/s/example.com/a`` is ``https://example.com/a``.
    """
    if not host.endswith(_AMP_CDN_SUFFIX):
        return None
    segments = [s for s in path.split("/") if s]
    # /c/s/<host>/... and /v/s/<host>/..., and the same without the /s/
    if segments and segments[0] in ("c", "v"):
        segments = segments[1:]
        inner_scheme = "https"
        if segments and segments[0] == "s":
            segments = segments[1:]
        elif segments:
            inner_scheme = "http"
        if segments:
            return f"{inner_scheme}://{'/'.join(segments)}"
    return None


def _unwrap_redirect(host: str, query_pairs) -> Optional[str]:
    """The real URL a redirector is pointing at, if it carries one."""
    names = _REDIRECT_HOSTS.get(host)
    if not names:
        return None
    for name in names:
        for key, value in query_pairs:
            if key.lower() != name:
                continue
            target = unquote(value or "")
            if target.startswith("http://") or target.startswith("https://"):
                return target
    return None


def canonical_url(url) -> Optional[str]:
    """``url`` with everything that does not identify the content removed.

    Lowercases the scheme and host, drops a leading ``www.``, a default port
    and the fragment, removes tracking parameters, sorts what is left, strips a
    trailing slash, and unwraps AMP renditions and known redirectors.

    Idempotent by construction -- feeding the result back in returns it
    unchanged -- which matters because the column is recomputed whenever an
    item is re-scraped.

    Returns None for anything that is not a usable absolute http(s) URL, which
    means "no canonical-URL signal for this item" rather than an error.
    """
    if not url:
        return None
    current = str(url).strip()

    for _ in range(_MAX_UNWRAPS):
        parsed = urlparse(current)
        if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
            return None

        scheme = parsed.scheme.lower()
        host = _normalise_host(parsed.netloc, scheme)
        pairs = parse_qsl(parsed.query, keep_blank_values=True)

        target = _unwrap_redirect(host, pairs) or _unwrap_amp_cdn(
            scheme, host, parsed.path
        )
        if target and target != current:
            current = target
            continue  # canonicalise what the wrapper was pointing at instead

        path = _strip_amp_path(parsed.path)
        # A trailing slash never distinguishes two articles, but "/" is the
        # whole path of a site root, so that collapses to empty instead.
        path = path.rstrip("/")

        kept = sorted((key, value) for key, value in pairs if not _is_tracking(key))
        query = urlencode(kept)

        # parse_qsl percent-decoded the values; re-encoding is what makes two
        # spellings of the same query agree. The path is left as given beyond
        # the AMP rewrite: re-encoding it risks changing what it points at.
        return urlunparse(
            (scheme, host, quote(path, safe="/%:@!$&'()*+,;=~"), "", query, "")
        )

    return None  # a redirector loop; treat it as having no canonical form
