"""Turning an extractor's failure into something a viewer can read.

yt-dlp writes its errors for a terminal: they carry the extractor's name and
the item's internal id, restate the underlying exception in brackets, and
sometimes ask you to file a bug. None of that means anything to someone who
pressed play on a card and got nothing, and the extractor's name is not ours
to put on their screen either.

So a failure is boiled down to one sentence saying what actually happened,
because "the site refused us" and "this video is gone" call for entirely
different reactions from the person reading it.
"""

import re
from typing import Optional

# "[SomeSite] abc123: Unable to download webpage: ..." — the leading bracket is
# the extractor, the token after it the site's own id for the item.
_PREFIX = re.compile(r"^\s*(?:ERROR:\s*)?(?:\[[^\]]+\]\s*)?(?:[\w.-]+:\s*)?")
# "(caused by <HTTPError 403: Forbidden>)", and yt-dlp's request-a-bug tail
_CAUSE = re.compile(r"\s*\(caused by [^)]*\)\.?", re.IGNORECASE)
_BUG_TAIL = re.compile(
    r"\s*(?:please report this issue|confirm you are on the latest version"
    r"|type\s+yt-dlp -U).*$",
    re.IGNORECASE | re.DOTALL,
)

MAX_MESSAGE_CHARS = 200

# Signs that a failure is the site turning this server away, rather than the
# video being gone or private. Only the first kind is worth asking again for.
_BLOCKED_MARKERS = (
    "403",
    "forbidden",
    "captcha",
    "blocked",
    "cloudflare",
    "429",
    "too many requests",
)


def looks_blocked(message: str) -> bool:
    """Whether the site refused us, as opposed to having nothing to give."""
    lowered = str(message).lower()
    return any(marker in lowered for marker in _BLOCKED_MARKERS)


def _http_status(text: str) -> Optional[int]:
    match = re.search(r"HTTP Error (\d{3})", text) or re.search(
        r"\bHTTP\s+(\d{3})\b", text
    )
    return int(match.group(1)) if match else None


def tidy(message: str) -> str:
    """Strip the parts of a yt-dlp error written for a terminal."""
    text = _CAUSE.sub("", str(message))
    text = _BUG_TAIL.sub("", text)
    text = _PREFIX.sub("", text.strip())
    text = " ".join(text.split())
    if len(text) > MAX_MESSAGE_CHARS:
        text = text[: MAX_MESSAGE_CHARS - 1] + "…"
    return text


def describe(message: str) -> str:
    """One short sentence for the viewer, from whatever the extractor said.

    Short because it has to fit on a card next to the article's title, and
    the cases are told apart because they call for different reactions: a
    site blocking this server can sometimes be got around with a cookie on
    the source, a video that has been taken down cannot.
    """
    text = tidy(message)
    lowered = text.lower()
    status = _http_status(text)

    if status == 403 or "forbidden" in lowered:
        return "The site refused this request (403)"
    if status in (404, 410) or "not available" in lowered or "removed" in lowered:
        return "The site no longer has this video"
    if status == 429 or "too many requests" in lowered:
        return "The site is rate limiting this server"
    if "age" in lowered and ("confirm" in lowered or "verif" in lowered):
        return "The site wants an age confirmation first"
    if "private" in lowered:
        return "This video is private"
    if "sign in" in lowered or "log in" in lowered or "login" in lowered:
        return "The site wants a signed-in session"
    if "geo" in lowered or "your country" in lowered or "not available in" in lowered:
        return "The site will not serve this video to this server"
    if status is not None:
        return f"The site answered HTTP {status}"
    return text or "The site would not hand over this video"
