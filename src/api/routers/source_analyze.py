import logging

import requests
import feedparser
from bs4 import BeautifulSoup
from fastapi import APIRouter, Depends, HTTPException

from bridge.analyze import (
    AnalyzeError,
    BRIDGE_SHORT_NAME,
    PREVIEW_TIMEOUT_SECONDS,
    fetch_page,
    page_title,
    request_selector_suggestions,
    suggest_source_name,
    validate_suggestions,
)
from db.source_template import SourceTemplate
from db.user import User
from route_models.source_analyze import (
    AnalyzeRequest,
    AnalyzeResponse,
    PreviewItem,
    PreviewRequest,
    PreviewResponse,
)
from routers.auth import authenticate

source_analyze_router = APIRouter()

PREVIEW_EXCERPT_MAX_CHARS = 300


def _css_selector_template() -> SourceTemplate:
    template = SourceTemplate.read_by_bridge_short_name(BRIDGE_SHORT_NAME)
    if template is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "The CSS Selector Complex template isn't available yet. "
                "Aggy imports it from rss-bridge shortly after startup; "
                "check that rss-bridge is running and try again."
            ),
        )
    return template


@source_analyze_router.post(
    "/suggest",
    summary="Analyze a website and suggest CSS selectors for a feed",
    response_model=AnalyzeResponse,
)
def suggest_selectors(
    request: AnalyzeRequest, user: User = Depends(authenticate)
) -> AnalyzeResponse:
    template = _css_selector_template()

    try:
        html = fetch_page(request.url)
        raw = request_selector_suggestions(request.url, html)
        candidates = validate_suggestions(html, request.url, raw)
    except AnalyzeError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))

    def best(field: str) -> str:
        return candidates[field][0].selector if candidates[field] else ""

    title = page_title(html)
    return AnalyzeResponse(
        page_title=title or None,
        suggested_source_name=suggest_source_name(title, request.url),
        template_name_hash=template.name_hash,
        candidates=candidates,
        # author/time start disabled even when candidates exist: they're
        # nice-to-haves, and a bad time selector can break the whole feed
        defaults={
            "home_page": request.url,
            "entry_element_selector": best("entry_element_selector"),
            "title_selector": best("title_selector"),
            "url_selector": best("url_selector"),
            "author_selector": "",
            "time_selector": "",
            "time_format": "",
            "limit": "10",
        },
    )


def _first_image(content_html: str):
    if not content_html:
        return None
    img = BeautifulSoup(content_html, "html.parser").find("img")
    if img and img.get("src"):
        return img["src"]
    return None


def _entry_excerpt(content_html: str):
    if not content_html:
        return None
    text = " ".join(
        BeautifulSoup(content_html, "html.parser").get_text(" ", strip=True).split()
    )
    if len(text) > PREVIEW_EXCERPT_MAX_CHARS:
        text = text[: PREVIEW_EXCERPT_MAX_CHARS - 1] + "…"
    return text or None


@source_analyze_router.post(
    "/preview",
    summary="Preview the feed produced by a set of CSS selectors",
    response_model=PreviewResponse,
)
def preview_selectors(
    request: PreviewRequest, user: User = Depends(authenticate)
) -> PreviewResponse:
    template = _css_selector_template()

    try:
        feed_url = template.create_rss_url(**request.parameters)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))

    try:
        response = requests.get(feed_url, timeout=PREVIEW_TIMEOUT_SECONDS)
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Couldn't reach rss-bridge: {e}")

    if not response.ok:
        # error_output=http makes the bridge return the failure as an HTML
        # page; surface its text so the user can see what went wrong
        message = " ".join(
            BeautifulSoup(response.content, "html.parser")
            .get_text(" ", strip=True)
            .split()
        )
        logging.info(f"selector preview failed ({response.status_code}): {message}")
        raise HTTPException(
            status_code=502,
            detail=f"rss-bridge couldn't build the feed: {message[:300]}",
        )

    parsed = feedparser.parse(response.content)
    items = []
    for entry in parsed.entries:
        try:
            content_html = entry.get("content")[0]["value"]
        except Exception:
            content_html = entry.get("summary")

        items.append(
            PreviewItem(
                title=entry.get("title"),
                url=entry.get("link"),
                author=entry.get("author"),
                date_published=entry.get("published"),
                excerpt=_entry_excerpt(content_html),
                image=_first_image(content_html),
            )
        )

    return PreviewResponse(feed_title=parsed.feed.get("title"), items=items)
