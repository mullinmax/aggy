"""Turn a bare website URL into rss-bridge "CSS Selector Complex" parameters.

The flow: fetch the page, hand a condensed copy of its HTML to an Ollama
chat model that proposes candidate CSS selectors for each bridge parameter,
then validate every candidate against the real page with BeautifulSoup so
the UI only offers selectors that actually match something.
"""

import json
import logging
import re
import threading
from datetime import datetime
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Comment

from config import config
from route_models.source_analyze import SelectorCandidate
from utils import get_ollama_connection

BRIDGE_SHORT_NAME = "CssSelectorComplexBridge"

PAGE_FETCH_TIMEOUT_SECONDS = 20
PAGE_MAX_BYTES = 3 * 1024 * 1024
# rss-bridge may fetch the page plus one page per article, so previews get a
# much longer budget than the initial page fetch
PREVIEW_TIMEOUT_SECONDS = 90

# pretend to be a browser: many sites serve bots a stub page or a 403
PAGE_FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}

# HTML attributes that help identify elements; everything else is stripped
# before the page is shown to the model to save context space.
KEPT_ATTRIBUTES = ("class", "id", "href", "datetime", "itemprop")
CONDENSED_HTML_MAX_CHARS = 30_000
CONDENSED_TEXT_MAX_CHARS = 80

# sanity bounds for an "article entry" selector: one match is a page layout
# element, hundreds are navigation links or tag clouds
ENTRY_MATCH_MIN = 2
ENTRY_MATCH_MAX = 300
MAX_CANDIDATES_PER_FIELD = 4
SAMPLES_PER_CANDIDATE = 3
SAMPLE_MAX_CHARS = 120


class AnalyzeError(Exception):
    """User-visible analysis failure with an HTTP status."""

    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


def fetch_page(url: str) -> str:
    """Download a page's HTML, with guardrails on scheme, size, and type."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise AnalyzeError("URL must start with http:// or https://")

    try:
        response = requests.get(
            url,
            headers=PAGE_FETCH_HEADERS,
            timeout=PAGE_FETCH_TIMEOUT_SECONDS,
            stream=True,
        )
        response.raise_for_status()
        content = response.raw.read(PAGE_MAX_BYTES + 1, decode_content=True)
    except requests.RequestException as e:
        raise AnalyzeError(f"Couldn't fetch {url}: {e}", status_code=502)

    if len(content) > PAGE_MAX_BYTES:
        raise AnalyzeError("Page is too large to analyze (over 3MB)")

    content_type = response.headers.get("Content-Type", "")
    if content_type and "html" not in content_type and "xml" not in content_type:
        raise AnalyzeError(
            f"URL returned {content_type or 'unknown content'}, not an HTML page"
        )

    return content.decode(response.encoding or "utf-8", errors="replace")


def condense_html(html: str) -> str:
    """Strip a page down to its structural skeleton for the model prompt."""
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(
        ["script", "style", "noscript", "svg", "iframe", "link", "meta", "template"]
    ):
        tag.decompose()
    for comment in soup.find_all(string=lambda s: isinstance(s, Comment)):
        comment.extract()

    body = soup.body or soup
    for tag in body.find_all(True):
        kept = {}
        for attr in KEPT_ATTRIBUTES:
            if attr not in tag.attrs:
                continue
            value = tag.attrs[attr]
            if isinstance(value, list):
                value = " ".join(value)
            kept[attr] = value[:100]
        tag.attrs = kept

    for text in body.find_all(string=True):
        stripped = " ".join(str(text).split())
        if len(stripped) > CONDENSED_TEXT_MAX_CHARS:
            stripped = stripped[:CONDENSED_TEXT_MAX_CHARS] + "…"
        text.replace_with(stripped)

    condensed = str(body)
    # collapse the indentation whitespace html.parser preserves
    condensed = re.sub(r">\s+<", "><", condensed)
    return condensed[:CONDENSED_HTML_MAX_CHARS]


# Structured-output schema the model must fill in. Selectors for everything
# but the entry element are relative to (searched inside) an entry element.
_SUGGESTION_SCHEMA = {
    "type": "object",
    "properties": {
        "entry_element_selector": {
            "type": "array",
            "items": {"type": "string"},
            "description": "CSS selectors matching one article/post entry each",
        },
        "title_selector": {"type": "array", "items": {"type": "string"}},
        "url_selector": {"type": "array", "items": {"type": "string"}},
        "author_selector": {"type": "array", "items": {"type": "string"}},
        "time_selector": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string"},
                    "php_time_format": {"type": "string"},
                },
                "required": ["selector", "php_time_format"],
            },
        },
    },
    "required": [
        "entry_element_selector",
        "title_selector",
        "url_selector",
        "author_selector",
        "time_selector",
    ],
}

_PROMPT = """You are helping turn a web page into an RSS feed by picking CSS selectors.

Below is the condensed HTML of the page. It lists articles/posts/videos (the "entries").

Propose selectors for these fields:
- entry_element_selector: 2 to 4 alternative selectors, each matching exactly one element
  per entry (the repeated card/row/list-item container). Prefer stable class names over
  positional selectors. Every entry element must contain a link to the article.
- title_selector: 1 to 3 selectors for the entry's title, RELATIVE to an entry element
  (e.g. "h2", "a.title").
- url_selector: 1 to 3 selectors matching the `a` element whose href is the article link,
  relative to an entry element. Use "a" if the first link is correct.
- author_selector: 0 to 2 selectors for the author name inside an entry, or empty list.
- time_selector: 0 to 2 selectors for the publication date inside an entry, each with the
  PHP date() format string that parses its value (for `time` elements the `datetime`
  attribute is parsed, e.g. format "Y-m-d\\TH:i:sP"). Use an empty list when unsure.

Rules: never invent class names that are not in the HTML. Avoid selectors tied to one
specific entry (ids or nth-child). Do not select navigation, sidebar, footer, or ad content.

Page URL: {url}

HTML:
{html}"""


# models currently being pulled in the background, keyed by model name
_pulls_in_flight: set = set()
_pulls_lock = threading.Lock()


def _pull_model_in_background(model: str) -> None:
    def pull():
        try:
            logging.info(f"Pulling ollama model {model} for source analysis...")
            get_ollama_connection().pull(model)
            logging.info(f"Ollama model {model} pulled")
        except Exception as e:
            logging.error(f"Failed to pull ollama model {model}: {e}")
        finally:
            with _pulls_lock:
                _pulls_in_flight.discard(model)

    with _pulls_lock:
        if model in _pulls_in_flight:
            return
        _pulls_in_flight.add(model)
    threading.Thread(target=pull, daemon=True).start()


def request_selector_suggestions(url: str, html: str) -> dict:
    """Ask the Ollama analysis model for candidate selectors (unvalidated)."""
    model = config.get("OLLAMA_ANALYSIS_MODEL")
    prompt = _PROMPT.format(url=url, html=condense_html(html))

    try:
        client = get_ollama_connection()
        response = client.chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            format=_SUGGESTION_SCHEMA,
            options={
                "temperature": 0,
                "num_ctx": config.get_int("OLLAMA_ANALYSIS_NUM_CTX"),
            },
        )
    except Exception as e:
        # a missing model is recoverable: kick off a pull and tell the user
        status = getattr(e, "status_code", None)
        if status == 404 or "not found" in str(e).lower():
            _pull_model_in_background(model)
            raise AnalyzeError(
                f'The analysis model "{model}" is being downloaded to Ollama. '
                "Try again in a few minutes.",
                status_code=503,
            )
        raise AnalyzeError(
            f"Ollama is unavailable for page analysis: {e}", status_code=502
        )

    try:
        return json.loads(response["message"]["content"])
    except (KeyError, TypeError, json.JSONDecodeError) as e:
        raise AnalyzeError(
            f"The analysis model returned unusable output: {e}", status_code=502
        )


def _select(root, selector: str) -> list:
    """soup.select that treats an invalid/unsupported selector as no matches."""
    if not selector or not selector.strip():
        return []
    try:
        return root.select(selector)
    except Exception:
        return []


def _sample_text(element) -> str:
    text = " ".join(element.get_text(" ", strip=True).split())
    if len(text) > SAMPLE_MAX_CHARS:
        text = text[: SAMPLE_MAX_CHARS - 1] + "…"
    return text


def _entry_link(entry, url_selector: str = "a"):
    """The `a` element the bridge would use as the entry's article link."""
    if entry.name == "a" and entry.get("href"):
        return entry
    for a in _select(entry, url_selector or "a"):
        if a.get("href"):
            return a
    return None


def validate_entry_candidates(soup, raw_selectors, base_url) -> list:
    """Keep entry selectors that match a plausible list of linked entries."""
    candidates = []
    for selector in dict.fromkeys(s.strip() for s in raw_selectors if s and s.strip()):
        matches = _select(soup, selector)
        if not (ENTRY_MATCH_MIN <= len(matches) <= ENTRY_MATCH_MAX):
            continue
        linked = [m for m in matches if _entry_link(m) is not None]
        # the bridge silently drops entries without links; require that most
        # matches carry one so the selector really is the article list
        if len(linked) < max(ENTRY_MATCH_MIN, len(matches) // 2):
            continue
        samples = [_sample_text(m) for m in linked[:SAMPLES_PER_CANDIDATE]]
        candidates.append(
            SelectorCandidate(
                selector=selector,
                match_count=len(matches),
                samples=[s for s in samples if s],
            )
        )
        if len(candidates) >= MAX_CANDIDATES_PER_FIELD:
            break
    return candidates


def _validate_within_entries(entries, raw_selectors, extract) -> list:
    """Generic per-entry validation: keep selectors matching inside entries.

    ``extract(entry, selector)`` returns the sample string for one entry, or
    None when the selector finds nothing useful in it.
    """
    candidates = []
    for selector in dict.fromkeys(s.strip() for s in raw_selectors if s and s.strip()):
        samples = []
        hits = 0
        for entry in entries:
            value = extract(entry, selector)
            if value is None:
                continue
            hits += 1
            if value and len(samples) < SAMPLES_PER_CANDIDATE:
                samples.append(value)
        # require the selector to work for most entries, not just one
        if hits < max(1, len(entries) // 2):
            continue
        candidates.append(
            SelectorCandidate(selector=selector, match_count=hits, samples=samples)
        )
        if len(candidates) >= MAX_CANDIDATES_PER_FIELD:
            break
    return candidates


def _extract_title(entry, selector):
    matches = _select(entry, selector)
    if not matches:
        return None
    return _sample_text(matches[0]) or None


def _extract_url(base_url):
    def extract(entry, selector):
        link = _entry_link(entry, selector)
        if link is None:
            return None
        return urljoin(base_url, link.get("href", ""))

    return extract


# PHP date() tokens translated to strptime, used only to sanity-check the
# model's proposed time format against real values from the page.
_PHP_TO_STRPTIME = {
    "Y": "%Y",
    "y": "%y",
    "m": "%m",
    "n": "%m",
    "d": "%d",
    "j": "%d",
    "H": "%H",
    "G": "%H",
    "h": "%I",
    "g": "%I",
    "i": "%M",
    "s": "%S",
    "A": "%p",
    "a": "%p",
    "D": "%a",
    "l": "%A",
    "M": "%b",
    "F": "%B",
    "P": "%z",
    "O": "%z",
    "T": "%Z",
}


def php_time_format_to_strptime(php_format: str) -> str:
    """Best-effort PHP→strptime translation; raises on untranslatable tokens."""
    out = []
    i = 0
    while i < len(php_format):
        char = php_format[i]
        if char == "\\" and i + 1 < len(php_format):
            out.append(php_format[i + 1])
            i += 2
            continue
        if char in _PHP_TO_STRPTIME:
            out.append(_PHP_TO_STRPTIME[char])
        elif char.isalpha():
            raise ValueError(f"Unsupported PHP date token: {char}")
        else:
            out.append(char)
        i += 1
    return "".join(out)


def _time_value(element) -> str:
    return element.get("datetime") or element.get_text(" ", strip=True)


def validate_time_candidates(entries, raw_candidates) -> list:
    """Keep time selectors whose format really parses the page's values.

    A wrong time selector/format aborts the whole bridge render, so unlike
    the other fields these are dropped unless parsing provably works.
    """
    candidates = []
    seen = set()
    for raw in raw_candidates:
        selector = (raw.get("selector") or "").strip()
        php_format = (raw.get("php_time_format") or "").strip()
        if not selector or not php_format or selector in seen:
            continue
        seen.add(selector)

        try:
            strptime_format = php_time_format_to_strptime(php_format)
        except ValueError:
            continue

        samples = []
        hits = 0
        for entry in entries:
            matches = _select(entry, selector)
            if not matches:
                continue
            value = " ".join(_time_value(matches[0]).split())
            try:
                datetime.strptime(value, strptime_format)
            except ValueError:
                continue
            hits += 1
            if len(samples) < SAMPLES_PER_CANDIDATE:
                samples.append(value)
        if hits < max(1, len(entries) // 2):
            continue
        candidates.append(
            SelectorCandidate(
                selector=selector,
                match_count=hits,
                samples=samples,
                time_format=php_format,
            )
        )
        if len(candidates) >= MAX_CANDIDATES_PER_FIELD:
            break
    return candidates


def validate_suggestions(html: str, base_url: str, raw: dict) -> dict:
    """Validate model output against the page; returns candidates per field."""
    soup = BeautifulSoup(html, "html.parser")

    entry_candidates = validate_entry_candidates(
        soup, raw.get("entry_element_selector") or [], base_url
    )
    if not entry_candidates:
        raise AnalyzeError(
            "Couldn't find a repeating list of linked articles on that page. "
            "It may load its content with JavaScript, which this can't handle."
        )

    # per-entry fields are validated inside the best entry selector's matches
    entries = _select(soup, entry_candidates[0].selector)[:10]

    return {
        "entry_element_selector": entry_candidates,
        "title_selector": _validate_within_entries(
            entries, raw.get("title_selector") or [], _extract_title
        ),
        "url_selector": _validate_within_entries(
            entries, raw.get("url_selector") or [], _extract_url(base_url)
        ),
        "author_selector": _validate_within_entries(
            entries, raw.get("author_selector") or [], _extract_title
        ),
        "time_selector": validate_time_candidates(
            entries, raw.get("time_selector") or []
        ),
    }


def page_title(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    if soup.title and soup.title.string:
        return " ".join(soup.title.string.split())
    return ""


def suggest_source_name(title: str, url: str) -> str:
    """A human-friendly default source name from the page title or domain."""
    if title:
        # "Latest news | Some Site" -> "Latest news"
        first = re.split(r"\s+[|–—-]\s+", title)[0].strip()
        if first:
            return first[:80]
    return urlparse(url).netloc or url
