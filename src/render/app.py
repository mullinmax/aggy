"""Headless rendering service.

Returns a page's HTML *after* its scripts have run. A plain HTTP GET only ever
sees the server's response, which on a growing share of sites is an empty
shell: the article list is built client-side, thumbnails sit in data
attributes until they scroll into view, and a consent or age interstitial
covers everything until it is dismissed.

The service is internal: aggy-api is the only client, and it is not exposed
in the bundled compose file.
"""

import logging
import os
from contextlib import asynccontextmanager
from typing import Optional
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import async_playwright
from pydantic import BaseModel

DEFAULT_TIMEOUT_MS = 30_000
MAX_TIMEOUT_MS = 60_000
# Lazy-loading listings only fill in once the viewport passes them, so the
# page is scrolled to the bottom in steps before its HTML is taken.
SCROLL_STEPS = 8
SCROLL_PAUSE_MS = 350

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

_state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    playwright = await async_playwright().start()
    _state["playwright"] = playwright
    # CHROMIUM_PATH points at a browser already on the machine, for images or
    # hosts that ship their own instead of the one Playwright downloads.
    executable = os.environ.get("CHROMIUM_PATH") or None
    _state["browser"] = await playwright.chromium.launch(
        args=["--no-sandbox", "--disable-dev-shm-usage"],
        executable_path=executable,
    )
    logging.info("chromium launched")
    yield
    await _state["browser"].close()
    await playwright.stop()


app = FastAPI(title="aggy-render", lifespan=lifespan)


class RenderRequest(BaseModel):
    url: str
    cookie: Optional[str] = None
    # CSS selector to wait for before taking the HTML, when the caller knows
    # which element carries the content.
    wait_for: Optional[str] = None
    scroll: bool = True
    timeout_ms: int = DEFAULT_TIMEOUT_MS


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "browser": bool(_state.get("browser"))}


async def _scroll_through(page) -> None:
    for step in range(1, SCROLL_STEPS + 1):
        await page.evaluate(
            "fraction => window.scrollTo(0, document.body.scrollHeight * fraction)",
            step / SCROLL_STEPS,
        )
        await page.wait_for_timeout(SCROLL_PAUSE_MS)
    await page.evaluate("window.scrollTo(0, 0)")


@app.post("/render")
async def render(request: RenderRequest) -> dict:
    parsed = urlparse(request.url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(status_code=422, detail="URL must be http(s)")

    timeout = max(1_000, min(request.timeout_ms or DEFAULT_TIMEOUT_MS, MAX_TIMEOUT_MS))
    browser = _state.get("browser")
    if browser is None:
        raise HTTPException(status_code=503, detail="Browser is not running")

    # a fresh context per request: no cookie or storage bleed between sources
    context = await browser.new_context(
        user_agent=USER_AGENT,
        locale="en-US",
        viewport={"width": 1280, "height": 2000},
    )
    try:
        if request.cookie:
            await context.set_extra_http_headers({"Cookie": request.cookie})

        page = await context.new_page()
        try:
            await page.goto(request.url, timeout=timeout, wait_until="domcontentloaded")
            if request.wait_for:
                await page.wait_for_selector(request.wait_for, timeout=timeout)
            else:
                # settle for the network going quiet, but don't fail the render
                # when a page keeps a socket open forever (ads, analytics)
                try:
                    await page.wait_for_load_state("networkidle", timeout=5_000)
                except PlaywrightError:
                    pass
            if request.scroll:
                await _scroll_through(page)

            return {
                "html": await page.content(),
                "url": page.url,
                "title": await page.title(),
            }
        finally:
            await page.close()
    except PlaywrightError as e:
        raise HTTPException(status_code=502, detail=str(e)[:500])
    except Exception as e:
        logging.exception(f"render failed for {request.url}")
        raise HTTPException(status_code=500, detail=str(e)[:500])
    finally:
        await context.close()
