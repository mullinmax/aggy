"""Endpoints the browser extension talks to.

The extension is a one-popup client: it knows a URL and wants to either file
that page as an article or start following the site it came from. Both would
otherwise take several round trips across the source, template, analysis, and
item APIs, with the extension having to know which of them applies to the page
it is on. These routes do that dispatch server-side so the popup stays a thin
UI over "what should happen with this page?".
"""

import logging
from typing import List
from urllib.parse import urlparse

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

import feedparser
import requests

from bridge.analyze import PREVIEW_TIMEOUT_SECONDS
from bridge.recommend import recommend_sources
from config import config
from db.base import get_db_con
from db.feed import Feed
from db.item import ItemLoose, ItemStrict
from db.item_state import ItemState
from db.source import Source
from db.source_template import SourceTemplate
from db.user import User
from ingest.item.mercury import ingest_mercury_item
from ingest.item.open_graph import ingest_open_graph_item
from ingest.item.reddit import ingest_reddit_item, is_reddit_post
from ingest.backends import get_backend
from ingest.jobs import ingest_source_now
from route_models.extension import (
    CreateSourceRequest,
    PreviewSourceRequest,
    ItemPreviewRequest,
    KnownFeed,
    KnownSource,
    RecommendRequest,
    RecommendResponse,
    SaveItemRequest,
    SaveItemResponse,
    StatusResponse,
)
from route_models.source import SourceRouteModel
from route_models.source_analyze import PreviewItem, PreviewResponse
from routers.auth import authenticate

# The feed-entry helpers the selector preview already uses; a preview of an
# option's feed should read exactly like a preview of a scraped page.
from routers.source_analyze import _entry_excerpt, _first_image

extension_router = APIRouter()

# Where pages saved one at a time are filed. One per feed, created on first
# save, so saved articles stay filterable and colorable like any other source
# without the user having to invent a name for them.
SAVED_LINKS_SOURCE_NAME = "Saved Links"
SAVED_LINKS_URL = "https://saved.aggy.local/"
EXCERPT_MAX_CHARS = 500


def _require_feed(user: User, feed_hash: str) -> Feed:
    feed = Feed.read(user_hash=user.name_hash, name_hash=feed_hash)
    if feed is None:
        raise HTTPException(status_code=404, detail="Feed not found")
    return feed


def _validate_url(url: str) -> str:
    parsed = urlparse(url or "")
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(
            status_code=422, detail="URL must start with http:// or https://"
        )
    return url


def _preview_item(item: ItemLoose) -> PreviewItem:
    excerpt = item.excerpt or ""
    if len(excerpt) > EXCERPT_MAX_CHARS:
        excerpt = excerpt[: EXCERPT_MAX_CHARS - 1] + "…"
    return PreviewItem(
        title=item.title,
        url=str(item.url),
        author=item.author,
        date_published=(
            item.date_published.isoformat() if item.date_published else None
        ),
        excerpt=excerpt or None,
        image=item.image_url,
    )


def _extract_item(request) -> ItemLoose:
    """Everything aggy can learn about a single page, best-effort.

    The same scrapers an ingested article goes through, plus whatever the
    browser passed in. The browser's values win: it saw the page rendered, and
    signed in, which is exactly the case where a server-side fetch comes back
    with a paywall stub or a consent interstitial.
    """
    candidate = ItemLoose(
        url=request.url,
        title=request.title,
        excerpt=request.excerpt,
        image_url=request.image_url,
    )

    scraped = [candidate]
    if is_reddit_post(request.url):
        scraped.append(ingest_reddit_item(candidate))
    scraped.append(ingest_open_graph_item(candidate))
    scraped.append(ingest_mercury_item(candidate))

    try:
        merged = ItemLoose.merge_instances(items=scraped)
    except Exception as e:
        logging.info(f"Merging extractions for {request.url} failed: {e}")
        merged = candidate

    # merge_instances prefers the longest value, so a browser-supplied title
    # can lose to a scraper's; the user's own page beats both.
    if request.title:
        merged.title = request.title
    if request.image_url and not merged.image_url:
        merged.image_url = request.image_url

    return merged


def _saved_links_source(feed: Feed) -> Source:
    """The feed's manual source for one-off saves, created on first use."""
    source = Source(
        user_hash=feed.user_hash,
        feed_hash=feed.name_hash,
        name=SAVED_LINKS_SOURCE_NAME,
        url=SAVED_LINKS_URL,
        kind="manual",
    )
    if not source.exists():
        feed.add_source(source)
        return source
    return Source.read(
        user_hash=feed.user_hash,
        feed_hash=feed.name_hash,
        source_hash=source.name_hash,
    )


@extension_router.post(
    "/recommend",
    summary="Rank the ways a page could become a source",
    response_model=RecommendResponse,
)
def recommend(
    request: RecommendRequest, user: User = Depends(authenticate)
) -> RecommendResponse:
    _validate_url(request.url)
    result = recommend_sources(
        request.url,
        page_feeds=request.page_feeds,
        page_title=request.page_title,
        cookie=request.cookie or "",
    )
    return RecommendResponse(
        url=request.url,
        options=result["options"],
        model_error=result["model_error"],
    )


@extension_router.post(
    "/create_source",
    summary="Create the source behind a recommended option",
    response_model=SourceRouteModel,
)
def create_source(
    request: CreateSourceRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(authenticate),
) -> SourceRouteModel:
    feed = _require_feed(user, request.feed_hash)
    option = request.option
    name = request.source_name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Source name cannot be empty")

    if option.strategy == "scrape":
        parameters = dict(request.parameters or {})
        if not parameters.get("home_page"):
            raise HTTPException(
                status_code=422,
                detail=(
                    "A scraped source needs the selectors from an analysis "
                    "pass (parameters, including home_page)"
                ),
            )
        if request.cookie:
            parameters["cookie"] = request.cookie
        source = Source(
            user_hash=user.name_hash,
            feed_hash=feed.name_hash,
            name=name,
            url=parameters["home_page"],
            kind="html",
            config={**parameters, "render": request.rendered},
        )
    elif option.strategy == "template":
        template = SourceTemplate.read(name_hash=option.template_name_hash or "")
        if template is None:
            raise HTTPException(status_code=404, detail="Source template not found")
        parameters = dict(option.template_parameters or {})
        if request.cookie and "cookie" in template.parameters:
            parameters["cookie"] = request.cookie
        try:
            source_url = template.create_rss_url(**parameters)
        except Exception as e:
            raise HTTPException(status_code=422, detail=str(e))
        source = Source(
            user_hash=user.name_hash,
            feed_hash=feed.name_hash,
            name=name,
            url=source_url,
            template_name_hash=template.name_hash,
            template_parameters=parameters,
            kind=template.kind,
        )
    elif option.strategy == "rss":
        if not option.feed_url:
            raise HTTPException(status_code=422, detail="This option has no feed URL")
        source = Source(
            user_hash=user.name_hash,
            feed_hash=feed.name_hash,
            name=name,
            url=option.feed_url,
        )
    else:
        raise HTTPException(
            status_code=422, detail=f"Unknown strategy '{option.strategy}'"
        )

    if source.exists():
        raise HTTPException(
            status_code=409,
            detail=(
                f'A source named "{name}" already exists in this feed. '
                "Pick a different name."
            ),
        )

    feed.add_source(source)
    # fetch it now rather than waiting for the schedule, so the user sees
    # items in the feed while the extension popup is still open
    background_tasks.add_task(ingest_source_now, source)
    return SourceRouteModel.from_db_model(source)


def _preview_feed(feed_url: str) -> PreviewResponse:
    """Fetch a feed URL and render its entries the way the app will show them."""
    try:
        response = requests.get(feed_url, timeout=PREVIEW_TIMEOUT_SECONDS)
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Couldn't fetch the feed: {e}")

    if not response.ok:
        raise HTTPException(
            status_code=502,
            detail=f"The feed answered with HTTP {response.status_code}",
        )

    parsed = feedparser.parse(response.content)
    if not parsed.entries:
        raise HTTPException(
            status_code=422,
            detail="That feed has no entries in it right now.",
        )

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


def _preview_backend(source: Source) -> PreviewResponse:
    """Run an option's backend once, without saving anything."""
    try:
        items = get_backend(source.kind).fetch_items(source)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

    return PreviewResponse(
        feed_title=source.name,
        items=[
            PreviewItem(
                title=item.title,
                url=str(item.url),
                author=item.author,
                date_published=(
                    item.date_published.isoformat() if item.date_published else None
                ),
                excerpt=item.excerpt,
                image=item.image_url,
            )
            for item in items
        ],
    )


@extension_router.post(
    "/preview_source",
    summary="Preview the items a recommended option would produce",
    response_model=PreviewResponse,
)
def preview_source(
    request: PreviewSourceRequest, user: User = Depends(authenticate)
) -> PreviewResponse:
    """Show what following this option actually yields, before creating it.

    A "scrape" option has no preview here: it has to be analyzed first, and
    the selector endpoints (/source_analyze/suggest and /preview) do that.
    """
    option = request.option

    if option.strategy == "rss":
        if not option.feed_url:
            raise HTTPException(status_code=422, detail="This option has no feed URL")
        return _preview_feed(option.feed_url)

    if option.strategy == "template":
        template = SourceTemplate.read(name_hash=option.template_name_hash or "")
        if template is None:
            raise HTTPException(status_code=404, detail="Source template not found")
        parameters = dict(option.template_parameters or {})
        if request.cookie and "cookie" in template.parameters:
            parameters["cookie"] = request.cookie
        try:
            source_url = template.create_rss_url(**parameters)
        except Exception as e:
            raise HTTPException(status_code=422, detail=str(e))
        if template.kind == "rss":
            return _preview_feed(source_url)
        return _preview_backend(
            Source(
                user_hash=user.name_hash,
                feed_hash="preview",
                name=option.suggested_source_name,
                url=source_url,
                kind=template.kind,
                config={"cookie": request.cookie} if request.cookie else None,
            )
        )

    raise HTTPException(
        status_code=422,
        detail=(
            "This option has to be analyzed first; use /source_analyze/suggest "
            "and /source_analyze/preview for it."
        ),
    )


@extension_router.post(
    "/preview_item",
    summary="Extract a single page's article content without saving it",
    response_model=PreviewItem,
)
def preview_item(
    request: ItemPreviewRequest, user: User = Depends(authenticate)
) -> PreviewItem:
    _validate_url(request.url)
    return _preview_item(_extract_item(request))


@extension_router.post(
    "/save_item",
    summary="Save a single page into a feed as an article",
    response_model=SaveItemResponse,
)
def save_item(
    request: SaveItemRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(authenticate),
) -> SaveItemResponse:
    _validate_url(request.url)
    feed = _require_feed(user, request.feed_hash)
    source = _saved_links_source(feed)

    candidate = ItemLoose(url=request.url)
    already_stored = candidate.exists()

    if already_stored:
        item = ItemStrict.read(url_hash=candidate.url_hash)
        if item is None:
            # deleted between the existence check and the read
            raise HTTPException(
                status_code=409, detail="That article was removed while saving it."
            )
    else:
        merged = _extract_item(request)
        # A page whose extractors all came back empty is still worth saving:
        # the user asked for it, and its URL and domain carry enough to rank
        # and display it.
        host = urlparse(str(merged.url)).netloc
        try:
            item = ItemStrict(
                **{
                    **merged.model_dump(),
                    "title": merged.title or host,
                    "domain": merged.domain or host,
                    "excerpt": merged.excerpt or "",
                    "content": merged.content or "",
                }
            )
        except Exception as e:
            raise HTTPException(
                status_code=422,
                detail=f"Couldn't build an article from {request.url}: {e}",
            )

        embedding_model = config.get("OLLAMA_EMBEDDING_MODEL", None)
        if embedding_model is not None:
            try:
                item.add_embedding(model_name=embedding_model)
            except Exception as e:
                logging.error(f"Error embedding saved item {item.url}: {e}")
        if config.get("IMAGE_EMBED_HOST", None) is not None:
            try:
                item.add_image_embedding(model_name=config.get("IMAGE_EMBED_MODEL"))
            except Exception as e:
                logging.error(f"Error embedding image of saved item {item.url}: {e}")

        try:
            item.create()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Couldn't save the item: {e}")

    # Linking is idempotent, so re-saving a page the feed already carries just
    # re-files it (and lets the vote below land) instead of failing.
    source.add_items(item)
    feed.add_items(item)

    if request.score is not None:
        ItemState.set_state(
            user_hash=user.name_hash,
            feed_hash=feed.name_hash,
            item_url_hash=item.url_hash,
            score=request.score,
            is_read=True,
        )

    return SaveItemResponse(
        item_hash=item.url_hash,
        source_name=source.name,
        source_name_hash=source.name_hash,
        created=not already_stored,
        score=request.score,
        item=_preview_item(item),
    )


def _site_sources(user: User, url: str) -> List[KnownSource]:
    """Sources the user already has whose URL is on the same site.

    Matching is on the registrable-ish host: a source pointing at
    ``example.com/feed.xml`` should count as "already following" while the
    user is reading ``www.example.com/posts/1``.
    """
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return []
    host = host[4:] if host.startswith("www.") else host

    with get_db_con() as cur:
        cur.execute(
            "SELECT s.feed_hash, s.name AS source_name, s.name_hash, s.url, s.kind, "
            "f.name AS feed_name "
            "FROM sources s JOIN feeds f "
            "ON f.user_hash = s.user_hash AND f.name_hash = s.feed_hash "
            "WHERE s.user_hash = %s",
            (user.name_hash,),
        )
        rows = cur.fetchall()

    matches = []
    for row in rows:
        source_host = (urlparse(row["url"]).hostname or "").lower()
        source_host = source_host[4:] if source_host.startswith("www.") else source_host
        # A template or scraped source's URL is the feed endpoint, which often
        # lives on the same site the user is reading; a bare host comparison
        # both ways covers subdomains in either direction.
        if not source_host or not (
            source_host == host
            or source_host.endswith(f".{host}")
            or host.endswith(f".{source_host}")
        ):
            continue
        matches.append(
            KnownSource(
                feed_hash=row["feed_hash"],
                feed_name=row["feed_name"],
                source_name=row["source_name"],
                source_name_hash=row["name_hash"],
                source_url=row["url"],
                kind=row["kind"],
            )
        )
    return matches


@extension_router.get(
    "/status",
    summary="What aggy already knows about this page and its site",
    response_model=StatusResponse,
)
def status(url: str, user: User = Depends(authenticate)) -> StatusResponse:
    _validate_url(url)
    item = ItemLoose(url=url)
    url_hash = item.url_hash

    with get_db_con() as cur:
        cur.execute(
            "SELECT fi.feed_hash, f.name AS feed_name, s.score, s.is_read "
            "FROM feed_items fi "
            "JOIN feeds f ON f.user_hash = fi.user_hash AND f.name_hash = fi.feed_hash "
            "LEFT JOIN item_states s ON s.user_hash = fi.user_hash "
            "AND s.feed_hash = fi.feed_hash AND s.item_url_hash = fi.item_url_hash "
            "WHERE fi.user_hash = %s AND fi.item_url_hash = %s",
            (user.name_hash, url_hash),
        )
        feeds = cur.fetchall()

    return StatusResponse(
        item_saved=bool(feeds),
        item_hash=url_hash if feeds else None,
        item_feeds=[
            KnownFeed(
                feed_hash=row["feed_hash"],
                feed_name=row["feed_name"],
                score=row["score"],
                is_read=row["is_read"],
            )
            for row in feeds
        ],
        site_sources=_site_sources(user, url),
    )
