import logging
import threading
import time
import uuid

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
    AnalyzeJobResponse,
    AnalyzeJobStatus,
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


# Analysis runs as a background job: the LLM pass can take minutes on CPU,
# which outlives reverse-proxy timeouts (Cloudflare cuts requests at ~100s
# with a 524), so /suggest returns a job id immediately and the client polls
# /suggest_result. Jobs live in memory; a restart simply loses in-flight
# analyses and the user re-runs them.
_jobs: dict = {}
_jobs_lock = threading.Lock()
JOB_TTL_SECONDS = 15 * 60


def _analyze(url: str, template_name_hash: str) -> AnalyzeResponse:
    html = fetch_page(url)
    raw = request_selector_suggestions(url, html)
    candidates = validate_suggestions(html, url, raw)

    def best(field: str) -> str:
        return candidates[field][0].selector if candidates[field] else ""

    title = page_title(html)
    return AnalyzeResponse(
        page_title=title or None,
        suggested_source_name=suggest_source_name(title, url),
        template_name_hash=template_name_hash,
        candidates=candidates,
        # author/time start disabled even when candidates exist: they're
        # nice-to-haves, and a bad time selector can break the whole feed
        defaults={
            "home_page": url,
            "entry_element_selector": best("entry_element_selector"),
            "title_selector": best("title_selector"),
            "url_selector": best("url_selector"),
            "author_selector": "",
            "time_selector": "",
            "time_format": "",
            "limit": "10",
        },
    )


def _run_suggest_job(job_id: str, url: str, template_name_hash: str) -> None:
    try:
        result = _analyze(url, template_name_hash)
        update = {"status": "done", "result": result}
    except AnalyzeError as e:
        update = {"status": "error", "detail": str(e), "status_code": e.status_code}
    except Exception as e:
        logging.exception(f"selector analysis of {url} failed")
        update = {"status": "error", "detail": str(e), "status_code": 500}
    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id].update(update)


def _drop_stale_jobs() -> None:
    cutoff = time.monotonic() - JOB_TTL_SECONDS
    with _jobs_lock:
        for job_id in [j for j, job in _jobs.items() if job["created"] < cutoff]:
            del _jobs[job_id]


@source_analyze_router.post(
    "/suggest",
    summary="Start analyzing a website to suggest CSS selectors for a feed",
    response_model=AnalyzeJobResponse,
)
def suggest_selectors(
    request: AnalyzeRequest, user: User = Depends(authenticate)
) -> AnalyzeJobResponse:
    template = _css_selector_template()
    _drop_stale_jobs()

    job_id = uuid.uuid4().hex
    with _jobs_lock:
        _jobs[job_id] = {
            "status": "running",
            "user_hash": user.name_hash,
            "created": time.monotonic(),
        }
    threading.Thread(
        target=_run_suggest_job,
        args=(job_id, request.url, template.name_hash),
        daemon=True,
    ).start()
    return AnalyzeJobResponse(job_id=job_id)


@source_analyze_router.get(
    "/suggest_result",
    summary="Poll a website-analysis job for its result",
    response_model=AnalyzeJobStatus,
)
def suggest_result(job_id: str, user: User = Depends(authenticate)) -> AnalyzeJobStatus:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is not None and job["user_hash"] != user.name_hash:
            job = None
        job = dict(job) if job is not None else None
    if job is None:
        raise HTTPException(status_code=404, detail="Analysis job not found")
    if job["status"] == "error":
        raise HTTPException(status_code=job["status_code"], detail=job["detail"])
    if job["status"] == "done":
        return AnalyzeJobStatus(status="done", result=job["result"])
    return AnalyzeJobStatus(status="running")


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
