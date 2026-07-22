import re
from typing import Optional
from urllib.parse import urlparse

from ollama import Client
from httpx import BasicAuth

from config import config

# Hosts whose links the UI renders as an inline player, and file extensions the
# UI plays directly, even when the item has no stored `media` entry (see the
# frontend's youtubeId/isVideoFile). Used so ranking treats these as playable
# media rather than plain links.
_PLAYABLE_MEDIA_HOSTS = {"youtube.com", "youtu.be", "youtube-nocookie.com"}
_VIDEO_FILE_RE = re.compile(r"\.(mp4|webm)(\?|$)", re.IGNORECASE)


def is_playable_media_url(url: Optional[str]) -> bool:
    """True when this URL plays inline in the UI (a YouTube link or a direct
    video file) even though it may carry no stored media entry."""
    if not url:
        return False
    if _VIDEO_FILE_RE.search(url):
        return True
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    if host.startswith("www.") or host.startswith("m."):
        host = host.split(".", 1)[1]
    return host in _PLAYABLE_MEDIA_HOSTS


def get_ollama_connection() -> Client:
    ollama_args = {
        "host": f"{config.get('OLLAMA_HOST')}:{config.get_int('OLLAMA_PORT')}"
    }

    auth_user = config.get("OLLAMA_USER", False)
    auth_password = config.get("OLLAMA_PASSWORD", False)
    if auth_user and auth_password:
        ollama_args["auth"] = BasicAuth(username=auth_user, password=auth_password)

    ollama = Client(**ollama_args)

    return ollama


def skip_limit_to_start_end(skip: int = 0, limit: int = -1) -> tuple[int, int]:
    """Converts a skip and limit to a start and end index."""
    start = 0
    if skip is not None and skip > 0:
        start = skip

    end = -1
    if limit is not None and limit >= 0:
        end = start + limit - 1

    return (start, end)
