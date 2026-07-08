"""Pull rich media (gifs, videos, galleries) out of reddit posts.

Reddit's RSS feeds only carry a small thumbnail; the post's JSON endpoint
has the full-resolution images, mp4 renditions of gifs, v.redd.it video
streams, and gallery contents. This module fetches that JSON for reddit
items and turns it into the item's ``media`` list.
"""

import logging
import re
from typing import List, Optional

import requests

from config import config
from db.item import ItemLoose

# A reddit post's comments page, which is what reddit RSS uses as the entry
# link, e.g. https://www.reddit.com/r/pics/comments/abc123/title/
_REDDIT_POST_RE = re.compile(
    r"^https?://(?:www|old|new)\.reddit\.com/(?:r|user|u)/[^/]+/comments/", re.I
)

_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
_VIDEO_EXTENSIONS = (".mp4", ".webm")


def is_reddit_post(url: Optional[str]) -> bool:
    return bool(url and _REDDIT_POST_RE.match(str(url)))


def _media_entry(type: str, url: str, poster: Optional[str] = None) -> dict:
    entry = {"type": type, "url": url}
    if poster:
        entry["poster"] = poster
    return entry


def _preview_image(post: dict) -> Optional[str]:
    try:
        return post["preview"]["images"][0]["source"]["url"]
    except (KeyError, IndexError, TypeError):
        return None


def _preview_mp4(post: dict) -> Optional[str]:
    """Reddit's mp4 rendition of a gif post, when it exists (much smaller)."""
    try:
        return post["preview"]["images"][0]["variants"]["mp4"]["source"]["url"]
    except (KeyError, IndexError, TypeError):
        return None


def _gallery_media(post: dict) -> List[dict]:
    metadata = post.get("media_metadata") or {}
    ordered = [
        i.get("media_id") for i in (post.get("gallery_data") or {}).get("items") or []
    ]
    entries = []
    for media_id in ordered or metadata.keys():
        meta = metadata.get(media_id) or {}
        if meta.get("status") != "valid":
            continue
        source = meta.get("s") or {}
        if meta.get("e") == "AnimatedImage":
            url = source.get("mp4") or source.get("gif")
            if url:
                entries.append(_media_entry("gif", url))
        else:
            url = source.get("u")
            if url:
                entries.append(_media_entry("image", url))
    return entries


def _post_media(post: dict) -> List[dict]:
    if post.get("is_gallery"):
        return _gallery_media(post)

    # native reddit video (v.redd.it); fallback_url is a plain mp4 stream
    reddit_video = ((post.get("secure_media") or post.get("media") or {})).get(
        "reddit_video"
    )
    if reddit_video and reddit_video.get("fallback_url"):
        media_type = "gif" if reddit_video.get("is_gif") else "video"
        return [
            _media_entry(
                media_type, reddit_video["fallback_url"], _preview_image(post)
            )
        ]

    target = post.get("url_overridden_by_dest") or post.get("url") or ""
    path = target.split("?")[0].lower()

    if path.endswith(".gifv"):
        # imgur gifv pages wrap an mp4 of the same name
        return [_media_entry("gif", _preview_mp4(post) or target[:-5] + ".mp4")]
    if path.endswith(".gif"):
        return [_media_entry("gif", _preview_mp4(post) or target)]
    if path.endswith(_VIDEO_EXTENSIONS):
        return [_media_entry("video", target, _preview_image(post))]
    if path.endswith(_IMAGE_EXTENSIONS):
        return [_media_entry("image", target)]
    if post.get("post_hint") == "image":
        image = _preview_image(post)
        if image:
            return [_media_entry("image", image)]
    return []


def ingest_reddit_item(item: ItemLoose) -> Optional[ItemLoose]:
    url = str(item.url)
    if not is_reddit_post(url):
        return None

    headers = {
        "User-Agent": (
            f"aggy/{config.get('BUILD_VERSION')} "
            "(self-hosted feed aggregator; +https://github.com/mullinmax/aggy)"
        )
    }
    try:
        # raw_json=1 stops reddit from HTML-escaping the media URLs
        response = requests.get(
            url.rstrip("/") + ".json",
            params={"raw_json": 1},
            timeout=15,
            headers=headers,
        )
        response.raise_for_status()
        post = response.json()[0]["data"]["children"][0]["data"]
    except Exception as e:
        logging.warning(f"Could not fetch reddit post data for {url}: {e}")
        return None

    media = _post_media(post)

    # a full-resolution card image beats the RSS thumbnail
    image_url = _preview_image(post)
    if not image_url:
        first_image = next((m for m in media if m["type"] == "image"), None)
        if first_image:
            image_url = first_image["url"]

    return ItemLoose(
        url=item.url,
        title=post.get("title"),
        author=f"u/{post['author']}" if post.get("author") else None,
        media=media or None,
        image_url=image_url,
    )
