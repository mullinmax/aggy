"""Client for the ``aggy-render`` sidecar (headless Chromium).

A plain HTTP GET only sees what the server sent. A growing share of listing
pages build themselves in the browser, keep their thumbnails in data
attributes until they scroll into view, or hide everything behind a consent
or age interstitial. For those, the HTML worth scraping only exists after the
page has run — which is what this service provides.
"""

import logging
from typing import Optional

import requests

from config import config

RENDER_TIMEOUT_SECONDS = 90


def is_configured() -> bool:
    return config.get("RENDER_HOST", None) is not None


def render_page(
    url: str,
    cookie: str = "",
    wait_for: Optional[str] = None,
    scroll: bool = True,
) -> str:
    """The page's HTML after scripts have run. Raises on failure."""
    payload = {"url": url, "scroll": scroll}
    if cookie:
        payload["cookie"] = cookie
    if wait_for:
        payload["wait_for"] = wait_for

    response = requests.post(
        "http://{host}:{port}/render".format(
            host=config.get("RENDER_HOST"), port=config.get("RENDER_PORT")
        ),
        json=payload,
        timeout=RENDER_TIMEOUT_SECONDS,
    )
    if response.status_code != 200:
        raise Exception(
            f"Renderer returned HTTP {response.status_code}: "
            f"{response.text.strip()[:300]}"
        )
    return response.json()["html"]


def render_page_or_none(url: str, cookie: str = "") -> Optional[str]:
    """Render, or return None when the renderer is absent or fails.

    Callers use this to upgrade a plain fetch when the service happens to be
    running, without making it a hard dependency.
    """
    if not is_configured():
        return None
    try:
        return render_page(url, cookie=cookie)
    except Exception as e:
        logging.warning(f"Headless render of {url} failed, falling back: {e}")
        return None
