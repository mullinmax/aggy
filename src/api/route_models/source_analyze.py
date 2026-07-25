from typing import Dict, List, Optional

from .base import BaseRouteModel


class AnalyzeRequest(BaseRouteModel):
    url: str
    # optional raw Cookie header, for sites that hide content behind a
    # consent/age wall; carried through to the saved source's bridge config
    cookie: Optional[str] = None

    model_config = {
        "json_schema_extra": {"example": {"url": "https://example.com/blog/"}}
    }


class DetectResponse(BaseRouteModel):
    # "feed" when the URL is (or advertises) an RSS/Atom feed, "video" when a
    # video-site extractor can enumerate it, else "html" (needs selectors)
    kind: str
    # the feed to subscribe to when kind == "feed"; may differ from the input
    # URL when auto-discovered from an HTML page's <link> tags
    feed_url: Optional[str] = None
    # friendly default source name from the page/feed title or domain
    suggested_source_name: str
    # template to create the source from, when kind == "video"
    template_name_hash: Optional[str] = None
    # which extractor claimed the URL, for kind == "video"
    extractor: Optional[str] = None


class SelectorCandidate(BaseRouteModel):
    selector: str
    # how many elements the selector matched on the page (entry selector) or
    # in how many entries it matched something (per-entry selectors)
    match_count: int
    # extracted text/urls from the first few matches, so the user can judge a
    # candidate without reading CSS
    samples: List[str] = []
    # PHP date format for time selectors (CssSelectorComplexBridge needs it)
    time_format: Optional[str] = None


class AnalyzeResponse(BaseRouteModel):
    page_title: Optional[str] = None
    suggested_source_name: str
    # template used to create the source (CSS Selector Complex bridge)
    template_name_hash: str
    # True when the selectors were found in headless-rendered HTML rather than
    # the raw response. Such a source has to keep rendering to see its
    # articles, so it is saved as a scraped source instead of an rss-bridge one.
    rendered: bool = False
    # candidates per bridge parameter: entry_element_selector, title_selector,
    # url_selector, time_selector, author_selector
    candidates: Dict[str, List[SelectorCandidate]]
    # preselected value per bridge parameter, ready to preview
    defaults: Dict[str, str]


class AnalyzeJobResponse(BaseRouteModel):
    # analysis runs as a background job (an LLM pass can outlive proxy
    # timeouts); the client polls suggest_result with this id
    job_id: str


class AnalyzeJobStatus(BaseRouteModel):
    # "running" while the job works; "done" comes with the result attached
    status: str
    result: Optional[AnalyzeResponse] = None


class PreviewRequest(BaseRouteModel):
    # CssSelectorComplexBridge parameters (home_page, entry_element_selector, ...)
    parameters: Dict[str, str]
    # Preview the page as the headless renderer sees it, and extract the
    # entries in-process, exactly as a scraped source would at ingest time.
    rendered: bool = False

    model_config = {
        "json_schema_extra": {
            "example": {
                "parameters": {
                    "home_page": "https://example.com/blog/",
                    "entry_element_selector": "div.article",
                    "limit": "10",
                }
            }
        }
    }


class PreviewItem(BaseRouteModel):
    title: Optional[str] = None
    url: Optional[str] = None
    author: Optional[str] = None
    date_published: Optional[str] = None
    excerpt: Optional[str] = None
    image: Optional[str] = None


class PreviewResponse(BaseRouteModel):
    feed_title: Optional[str] = None
    items: List[PreviewItem]
