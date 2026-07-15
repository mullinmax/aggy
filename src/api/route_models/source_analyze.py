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
