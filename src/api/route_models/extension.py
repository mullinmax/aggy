from typing import Dict, List, Optional

from pydantic import confloat

from .base import BaseRouteModel
from .source_analyze import PreviewItem


class SourceOption(BaseRouteModel):
    """One way the browser extension could turn a page into a source.

    Every option carries everything ``/extension/create_source`` needs to
    build the source, so the extension never has to know which endpoint a
    given strategy would otherwise have used.
    """

    # "template" (a catalog template with parameters), "rss" (a feed URL),
    # or "scrape" (CSS selectors, which have to be analyzed first)
    strategy: str
    # short label for the button, e.g. "Subscribe to r/selfhosted"
    label: str
    # one sentence on why this is the right way to read the page
    reason: str
    # "high" for a rule that recognised the site outright, "medium" for a
    # feed the page advertises or a model's template pick, "low" for the
    # generic fallbacks
    confidence: str
    suggested_source_name: str
    # set for strategy == "rss"
    feed_url: Optional[str] = None
    # set for strategy == "template"
    template_name_hash: Optional[str] = None
    template_name: Optional[str] = None
    template_parameters: Optional[Dict[str, str]] = None
    # True when the option still needs a selector analysis pass before it can
    # be previewed or saved (strategy == "scrape")
    requires_analysis: bool = False


class RecommendRequest(BaseRouteModel):
    url: str
    # Feed URLs the extension read out of the live DOM's <link rel="alternate">
    # tags. The browser sees pages logged in and after JavaScript has run, so
    # these are often feeds a server-side fetch would never find.
    page_feeds: List[str] = []
    # Page title as the browser rendered it, for naming the source.
    page_title: Optional[str] = None
    # Raw Cookie header for the site, when the user chose to share it so the
    # server can fetch the page as they see it.
    cookie: Optional[str] = None


class RecommendResponse(BaseRouteModel):
    url: str
    options: List[SourceOption]
    # populated when the analysis model was asked to pick a template and
    # couldn't be reached; the rule-based options are still returned
    model_error: Optional[str] = None


class CreateSourceRequest(BaseRouteModel):
    feed_hash: str
    source_name: str
    option: SourceOption
    # Cookie header to store on the source, so ingest keeps fetching the page
    # the way the user sees it.
    cookie: Optional[str] = None
    # CSS selectors approved in the preview, for a "scrape" option.
    parameters: Optional[Dict[str, str]] = None
    # Whether the scraped page needs the headless renderer.
    rendered: bool = False


class PreviewSourceRequest(BaseRouteModel):
    option: SourceOption
    cookie: Optional[str] = None


class SaveItemRequest(BaseRouteModel):
    url: str
    feed_hash: str
    # Overrides for what the extractors found; the extension sends what the
    # browser sees so a page behind a login still gets a real title.
    title: Optional[str] = None
    excerpt: Optional[str] = None
    image_url: Optional[str] = None
    # -1 (down) .. 1 (up); None saves the article without voting on it.
    score: Optional[confloat(ge=-1, le=1)] = None
    cookie: Optional[str] = None


class SaveItemResponse(BaseRouteModel):
    item_hash: str
    # the manual source the article was filed under
    source_name: str
    source_name_hash: str
    # False when this exact URL was already in the feed
    created: bool
    score: Optional[float] = None
    item: PreviewItem


class ItemPreviewRequest(BaseRouteModel):
    url: str
    title: Optional[str] = None
    excerpt: Optional[str] = None
    image_url: Optional[str] = None
    cookie: Optional[str] = None


class KnownFeed(BaseRouteModel):
    feed_hash: str
    feed_name: str
    # the user's vote on this item in that feed, when there is one
    score: Optional[float] = None
    is_read: Optional[bool] = None


class KnownSource(BaseRouteModel):
    feed_hash: str
    feed_name: str
    source_name: str
    source_name_hash: str
    source_url: str
    kind: str


class StatusResponse(BaseRouteModel):
    # True when this exact URL is already an item in one of the user's feeds
    item_saved: bool
    item_hash: Optional[str] = None
    # feeds that already carry this item, with the vote cast in each
    item_feeds: List[KnownFeed] = []
    # sources the user already follows on this site
    site_sources: List[KnownSource] = []
