"""Work out the best way to follow the page a user is looking at.

The browser extension sends the URL of the tab (plus whatever the live DOM
told it) and gets back a ranked list of ``SourceOption``s: subscribe to a
site's own template, follow a feed the page advertises, enumerate it with the
video extractor, or -- when nothing better exists -- scrape it with CSS
selectors.

Rules come first: a reddit or YouTube URL is recognised outright, which is
cheaper, faster, and more reliable than asking a model. The analysis model is
only consulted for sites no rule covers, and only to pick a template out of
the catalog that already matches the site's domain. Every step is
best-effort: a rule that raises, a site that won't answer, or an Ollama that
isn't running removes one option rather than failing the request.
"""

import json
import logging
import re
from urllib.parse import urlparse

from builtin_templates import builtin_template, ytdlp_template
from bridge.analyze import (
    AnalyzeError,
    _chat,
    detect_source_type,
    suggest_source_name,
)
from config import config
from db.source_template import SourceTemplate
from ingest.backends import ytdlp
from route_models.extension import SourceOption
from utils import get_ollama_connection

# How many catalog templates for the site's domain the model is shown. The
# prompt has to fit a small local model's context window, and a domain rarely
# has more than a handful of routes worth considering.
MAX_MODEL_TEMPLATES = 12
# Feeds advertised by the page are offered individually; a page listing more
# than a few is a directory, not a subscription choice.
MAX_PAGE_FEEDS = 3

_REDDIT_HOSTS = ("reddit.com", "old.reddit.com", "new.reddit.com", "np.reddit.com")
_SUBREDDIT_PATH_RE = re.compile(r"^/r/([A-Za-z0-9_]{2,21})(/|$)")
_REDDIT_USER_PATH_RE = re.compile(r"^/(?:user|u)/([A-Za-z0-9_-]{3,20})(/|$)")
_YOUTUBE_CHANNEL_RE = re.compile(r"^/channel/(UC[0-9A-Za-z_-]{22})(/|$)")
_YOUTUBE_HANDLE_RE = re.compile(r"^/(@[\w.-]+|c/[\w.-]+|user/[\w.-]+)(/|$)")
_BSKY_PROFILE_RE = re.compile(r"^/profile/([^/]+)(/|$)")


def _host(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    for prefix in ("www.", "m.", "mobile."):
        if host.startswith(prefix):
            host = host[len(prefix) :]
    return host


def _template_option(
    template_name: str,
    parameters: dict,
    label: str,
    reason: str,
    source_name: str,
    confidence: str = "high",
) -> SourceOption:
    """A built-in template option, or None when that template isn't stored."""
    template = builtin_template(template_name)
    stored = SourceTemplate.read(name_hash=template.name_hash)
    if stored is None:
        # the built-in seeding job hasn't run (or failed); offering a template
        # the create endpoint can't look up would only produce a 404 later
        return None
    return SourceOption(
        strategy="template",
        label=label,
        reason=reason,
        confidence=confidence,
        suggested_source_name=source_name,
        template_name_hash=template.name_hash,
        template_name=template.user_friendly_name,
        template_parameters=parameters,
    )


def _site_rule_option(url: str) -> SourceOption:
    """The option for sites aggy knows natively, or None."""
    host = _host(url)
    path = urlparse(url).path or "/"

    if host in _REDDIT_HOSTS or host.endswith(".reddit.com"):
        match = _SUBREDDIT_PATH_RE.match(path)
        if match:
            subreddit = match.group(1)
            return _template_option(
                "Reddit Subreddit",
                {"subreddit": subreddit},
                label=f"Follow r/{subreddit}",
                reason=(
                    "This is a subreddit, so aggy can read reddit's own feed "
                    "for it instead of scraping the page."
                ),
                source_name=f"r/{subreddit}",
            )
        match = _REDDIT_USER_PATH_RE.match(path)
        if match:
            username = match.group(1)
            return _template_option(
                "Reddit User",
                {"username": username},
                label=f"Follow u/{username}",
                reason="This is a reddit user page, which has its own feed.",
                source_name=f"u/{username}",
            )
        return None

    if host in ("youtube.com", "youtu.be") or host.endswith(".youtube.com"):
        match = _YOUTUBE_CHANNEL_RE.match(path)
        channel_id = match.group(1) if match else None
        title = ""
        if channel_id is None and _YOUTUBE_HANDLE_RE.match(path):
            # /@handle and /c/name don't carry the channel id; the id lives in
            # the page, so this costs one fetch of youtube.com
            from bulk_import import resolve_youtube_channel

            try:
                channel_id, title = resolve_youtube_channel(url)
            except Exception as e:
                logging.info(f"Couldn't resolve a YouTube channel for {url}: {e}")
        if channel_id is None:
            # a video, playlist, or search page: yt-dlp handles those
            return None
        return _template_option(
            "YouTube Channel",
            {"channel_id": channel_id},
            label="Follow this YouTube channel",
            reason="YouTube publishes a feed of a channel's uploads.",
            source_name=title or suggest_source_name("", url),
        )

    if host == "bsky.app":
        match = _BSKY_PROFILE_RE.match(path)
        if match:
            handle = match.group(1)
            return _template_option(
                "Bluesky User",
                {"handle": handle},
                label=f"Follow @{handle}",
                reason="Bluesky publishes a feed of each account's posts.",
                source_name=f"@{handle}",
            )

    return None


def _rss_option(
    feed_url: str, source_name: str, reason: str, confidence: str = "medium"
) -> SourceOption:
    return SourceOption(
        strategy="rss",
        label="Subscribe to this feed",
        reason=reason,
        confidence=confidence,
        suggested_source_name=source_name,
        feed_url=feed_url,
    )


def _ytdlp_option(url: str, source_name: str, extractor: str) -> SourceOption:
    template = ytdlp_template()
    if SourceTemplate.read(name_hash=template.name_hash) is None:
        return None
    return SourceOption(
        strategy="template",
        label="Follow this listing as videos",
        reason=(
            f"The {extractor or 'video'} extractor can enumerate this page's "
            "videos, reading metadata only."
        ),
        confidence="medium",
        suggested_source_name=source_name,
        template_name_hash=template.name_hash,
        template_name=template.user_friendly_name,
        template_parameters={"url": url},
    )


_TEMPLATE_PICK_SCHEMA = {
    "type": "object",
    "properties": {
        "template_number": {"type": "integer"},
        "parameters": {"type": "object", "additionalProperties": {"type": "string"}},
        "reason": {"type": "string"},
    },
    "required": ["template_number", "parameters", "reason"],
}

_TEMPLATE_PICK_PROMPT = """You are matching a web page to a feed template.

A user is on this page and wants to follow it:
URL: {url}
Title: {title}

Below are the templates aggy has for this site. Each turns a set of parameters
into a feed URL. Pick the ONE template that would follow what this page shows,
and fill in its parameters from the URL above.

{templates}

Answer with the template's number and its parameters. Every required parameter
must be filled with a value taken from the URL -- never invent an id, a name,
or a number that does not appear in it. If no template fits the page, or a
required parameter is not in the URL, answer with template_number 0 and empty
parameters."""


def _describe_template(index: int, template: SourceTemplate) -> str:
    lines = [f"{index}. {template.user_friendly_name} -- {template.description}"]
    for key, parameter in template.parameters.items():
        bits = [f"   - {key}"]
        if parameter.title or parameter.name:
            bits.append(f"({parameter.title or parameter.name})")
        bits.append("required" if parameter.required else "optional")
        if parameter.example:
            bits.append(f"e.g. {parameter.example}")
        lines.append(" ".join(bits))
    return "\n".join(lines)


def _model_template_option(url: str, title: str) -> tuple:
    """Ask the analysis model to match the page to a catalog template.

    Returns ``(option, error)``; both are None when the site simply has no
    templates worth showing the model.
    """
    host = _host(url)
    if not host:
        return None, None

    candidates = [
        template
        for template in SourceTemplate.search(host, limit=MAX_MODEL_TEMPLATES)
        # a template for another site would only tempt the model into
        # inventing parameters that aren't in this URL
        if template.site_domain
        and (host.endswith(template.site_domain) or template.site_domain.endswith(host))
    ]
    if not candidates:
        return None, None

    prompt = _TEMPLATE_PICK_PROMPT.format(
        url=url,
        title=title or "",
        templates="\n".join(
            _describe_template(i + 1, t) for i, t in enumerate(candidates)
        ),
    )

    model = config.get("OLLAMA_ANALYSIS_MODEL")
    try:
        response = _chat(
            get_ollama_connection(), model, prompt, schema=_TEMPLATE_PICK_SCHEMA
        )
        content = re.sub(
            r"<think>.*?</think>",
            "",
            response["message"]["content"],
            flags=re.DOTALL,
        )
        pick = json.loads(content[content.find("{") : content.rfind("}") + 1])
    except Exception as e:
        logging.info(f"Template matching for {url} was unavailable: {e}")
        return None, f"Couldn't ask the analysis model for a template match: {e}"

    number = pick.get("template_number") or 0
    if not 1 <= number <= len(candidates):
        return None, None

    template = candidates[number - 1]
    parameters = {
        key: str(value)
        for key, value in (pick.get("parameters") or {}).items()
        if key in template.parameters and value not in (None, "")
    }
    try:
        # the model routinely misses a required parameter or fills one with a
        # value it made up; the template's own validation is the cheap check
        template.validate_parameters(**parameters)
    except Exception as e:
        logging.info(f"Model's template pick for {url} didn't validate: {e}")
        return None, None

    return (
        SourceOption(
            strategy="template",
            label=f"Follow with “{template.user_friendly_name}”",
            reason=(pick.get("reason") or template.description)[:300],
            confidence="medium",
            suggested_source_name=suggest_source_name(title, url),
            template_name_hash=template.name_hash,
            template_name=template.user_friendly_name,
            template_parameters=parameters,
        ),
        None,
    )


def _scrape_option(url: str, source_name: str) -> SourceOption:
    return SourceOption(
        strategy="scrape",
        label="Build a feed from this page",
        reason=(
            "No feed for this page, so aggy will read the page itself and work "
            "out which parts of it are articles."
        ),
        confidence="low",
        suggested_source_name=source_name,
        requires_analysis=True,
    )


def _clean_feed_urls(page_feeds: list) -> list:
    """Absolute http(s) feed URLs from the page, deduplicated, capped."""
    seen = set()
    out = []
    for feed in page_feeds or []:
        feed = (feed or "").strip()
        parsed = urlparse(feed)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            continue
        if feed in seen:
            continue
        seen.add(feed)
        out.append(feed)
    return out[:MAX_PAGE_FEEDS]


def recommend_sources(
    url: str, page_feeds: list = None, page_title: str = None, cookie: str = ""
) -> dict:
    """Rank the ways this URL could become a source.

    Returns ``{"options": [SourceOption], "model_error": str | None}``, always
    with at least the scrape fallback in it.
    """
    options = []
    model_error = None
    default_name = suggest_source_name(page_title or "", url)

    rule_option = _site_rule_option(url)
    if rule_option is not None:
        options.append(rule_option)

    # Feeds the browser found in the page beat anything the server can detect:
    # the extension read them from the DOM of a page rendered, and logged in,
    # as the user sees it.
    for feed_url in _clean_feed_urls(page_feeds):
        options.append(
            _rss_option(
                feed_url,
                default_name,
                reason="This page advertises this feed in its HTML.",
                confidence="high" if not options else "medium",
            )
        )

    detected = None
    if not options:
        # Only worth a fetch when nothing above matched: it costs a request to
        # the site and tells us what a page already claiming a feed would have.
        try:
            detected = detect_source_type(url, cookie=cookie)
        except AnalyzeError as e:
            logging.info(f"Couldn't fetch {url} while recommending sources: {e}")
        except Exception as e:
            logging.warning(f"Source detection for {url} failed: {e}")

    if detected is not None:
        default_name = detected.get("suggested_source_name") or default_name
        if detected.get("kind") == "feed" and detected.get("feed_url"):
            options.append(
                _rss_option(
                    detected["feed_url"],
                    default_name,
                    reason=(
                        "This URL is a feed."
                        if detected["feed_url"] == url
                        else "The page advertises this feed."
                    ),
                    confidence="high",
                )
            )

    supported = ytdlp.is_supported(url)
    if supported.get("supported"):
        option = _ytdlp_option(url, default_name, supported.get("extractor"))
        if option is not None:
            options.append(option)

    # A model pass is worth its seconds only when nothing confident was found.
    if not any(o.confidence == "high" for o in options):
        option, model_error = _model_template_option(url, page_title or "")
        if option is not None:
            options.append(option)

    options.append(_scrape_option(url, default_name))

    order = {"high": 0, "medium": 1, "low": 2}
    options.sort(key=lambda o: order.get(o.confidence, 3))
    return {"options": options, "model_error": model_error}
