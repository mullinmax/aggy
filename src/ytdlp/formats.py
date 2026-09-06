"""Choosing a rendition a browser can actually play.

Kept apart from the service itself so it stays a plain function of the info
dict yt-dlp hands back — no network, no yt-dlp, no FastAPI — which is what
makes it testable, and it is the part most worth testing: getting this choice
wrong is the difference between a video that plays and a play button that
does nothing.
"""

from typing import Optional
from urllib.parse import urlparse

# Protocols a browser can be handed directly, best first. A progressive file
# just plays; an HLS playlist plays natively on Safari/iOS and through the
# player's own HLS support elsewhere. Split renditions (DASH manifests, and
# the video-only/audio-only formats that would need muxing) are left out:
# nothing in the browser can put those back together without a download.
PROGRESSIVE_PROTOCOLS = ("https", "http")
HLS_PROTOCOLS = ("m3u8", "m3u8_native")


def _has_track(fmt: dict, key: str) -> bool:
    """Whether a format carries a video/audio track.

    yt-dlp writes the string "none" for a track a format genuinely lacks, and
    leaves the field unset when the extractor simply didn't say. Treating
    "unknown" as "missing" throws away every format on the many sites that
    report no codec information at all, so only an explicit "none" counts as
    absent.
    """
    return fmt.get(key) != "none"


def _states_both_tracks(fmt: dict) -> bool:
    return fmt.get("vcodec") not in (None, "none") and fmt.get("acodec") not in (
        None,
        "none",
    )


def _muxed_formats(info: dict, protocols) -> list:
    """Formats carrying both tracks in one stream, on the given protocols."""
    return [
        fmt
        for fmt in info.get("formats") or []
        if fmt.get("url")
        and _has_track(fmt, "vcodec")
        and _has_track(fmt, "acodec")
        and (fmt.get("protocol") or "") in protocols
    ]


def is_m3u8(url: str) -> bool:
    """An HLS playlist by its path, ignoring the signature query string that
    almost every one of these URLs carries."""
    return urlparse(str(url)).path.lower().endswith(".m3u8")


def best_format(candidates: list) -> dict:
    """Pick a rendition: one that says it has both tracks first, then the
    biggest. A format whose codecs the extractor never filled in is playable
    often enough to be worth offering, but a format that states it carries
    picture and sound is worth more than a taller one that might be silent.
    """

    def rank(fmt: dict):
        return (
            1 if _states_both_tracks(fmt) else 0,
            fmt.get("height") or 0,
            fmt.get("tbr") or 0,
        )

    return max(candidates, key=rank)


def playable_url(info: dict) -> Optional[dict]:
    """The best rendition a browser can play, or None if there is none.

    A plain progressive file wins when the site offers one. Sites that only
    publish adaptive streams — increasingly, most of them — fall back to their
    HLS playlist, which the player loads with its own HLS support; the result
    says which it is, so the client knows what it is being handed.
    """
    candidates = _muxed_formats(info, PROGRESSIVE_PROTOCOLS)
    if not candidates:
        candidates = _muxed_formats(info, HLS_PROTOCOLS)
    # Some extractors describe the whole item as one stream and list no
    # formats at all; `url` on the info dict itself is then the playable one.
    if not candidates and info.get("url"):
        candidates = [info]
    if not candidates:
        return None

    best = best_format(candidates)
    protocol = best.get("protocol") or ""
    return {
        "url": best["url"],
        "ext": best.get("ext"),
        "height": best.get("height"),
        "protocol": protocol,
        # HLS needs the player to load it rather than the `video` tag alone,
        # everywhere but Safari, so say so plainly instead of making every
        # caller recognise yt-dlp's protocol names.
        "is_hls": protocol in HLS_PROTOCOLS or is_m3u8(best["url"]),
    }
