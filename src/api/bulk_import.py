"""Parsers that turn subscription exports into source candidates.

Each platform parser accepts whatever the user can realistically get their
hands on — a data-export file, a pasted list of names/URLs, or (for
platforms with a public follows API) just a username — and normalizes it
into ``SourceCandidate`` rows the review UI can assign to feeds.

Candidates reference the built-in source templates where one exists, so
imported sources stay editable through the normal template UI.
"""

import csv
import io
import logging
import re
import xml.etree.ElementTree as ET
from typing import Callable, List, Optional, Tuple

import httpx
from pydantic import BaseModel

from builtin_templates import builtin_template

# Bound the work a single parse request can do: resolving a YouTube handle
# costs an HTTP request to youtube.com, and Bluesky follows are paginated
# 100 at a time.
MAX_YOUTUBE_RESOLUTIONS = 50
MAX_BLUESKY_FOLLOWS = 1000
HTTP_TIMEOUT_SECONDS = 10

BLUESKY_FOLLOWS_API = "https://public.api.bsky.app/xrpc/app.bsky.graph.getFollows"


class SourceCandidate(BaseModel):
    """One potential source detected in the user's subscription data."""

    name: str
    url: Optional[str] = None  # None when the entry couldn't be resolved
    # OPML folder (or other grouping) the entry came from, as a hint for
    # which feed it belongs in.
    group: Optional[str] = None
    template_name_hash: Optional[str] = None
    template_parameters: Optional[dict] = None
    error: Optional[str] = None


def _tokenize(text: str) -> List[str]:
    """Split pasted text into entry tokens (newlines, commas, whitespace)."""
    return [t for t in re.split(r"[\s,]+", text or "") if t]


def _dedupe(candidates: List[SourceCandidate]) -> List[SourceCandidate]:
    """Drop candidates that repeat an earlier candidate's URL or name."""
    seen_urls: set = set()
    seen_names: set = set()
    out = []
    for c in candidates:
        url_key = c.url or f"error:{c.name}"
        if url_key in seen_urls:
            continue
        seen_urls.add(url_key)
        # source names must be unique within a feed; disambiguate repeats
        if c.name in seen_names:
            suffix = 2
            while f"{c.name} ({suffix})" in seen_names:
                suffix += 1
            c.name = f"{c.name} ({suffix})"
        seen_names.add(c.name)
        out.append(c)
    return out


# ---------------------------------------------------------------------------
# Reddit
# ---------------------------------------------------------------------------

# Subreddit names: letters/digits/underscores, 2-21 chars.
_SUBREDDIT_RE = re.compile(r"^[A-Za-z0-9_]{2,21}$")
_SUBREDDIT_URL_RE = re.compile(r"reddit\.com/r/([A-Za-z0-9_]{2,21})", re.IGNORECASE)


def parse_reddit(text: str) -> Tuple[List[SourceCandidate], List[str]]:
    """Parse a Reddit GDPR export (subscribed_subreddits.csv) or a pasted
    list of subreddit names/URLs into subreddit source candidates."""
    template = builtin_template("Reddit Subreddit")
    names: List[str] = []
    skipped: List[str] = []

    for token in _tokenize(text):
        m = _SUBREDDIT_URL_RE.search(token)
        if m:
            names.append(m.group(1))
            continue
        # bare names, r/name, /r/name — also covers the export's CSV rows
        bare = re.sub(r"^/?(r/)?", "", token, flags=re.IGNORECASE).rstrip("/")
        if _SUBREDDIT_RE.match(bare):
            # the export file's header row
            if bare.lower() == "subreddit":
                continue
            names.append(bare)
        else:
            skipped.append(token)

    candidates = [
        SourceCandidate(
            name=f"r/{name}",
            url=template.create_rss_url(subreddit=name),
            template_name_hash=template.name_hash,
            template_parameters={"subreddit": name},
        )
        for name in names
    ]
    warnings = []
    if skipped:
        shown = ", ".join(skipped[:5])
        more = f" (and {len(skipped) - 5} more)" if len(skipped) > 5 else ""
        warnings.append(f"Skipped {len(skipped)} unrecognized entries: {shown}{more}")
    return _dedupe(candidates), warnings


# ---------------------------------------------------------------------------
# YouTube
# ---------------------------------------------------------------------------

_CHANNEL_ID_RE = re.compile(r"^UC[0-9A-Za-z_-]{22}$")
_CHANNEL_URL_RE = re.compile(
    r"youtube\.com/channel/(UC[0-9A-Za-z_-]{22})", re.IGNORECASE
)
# /@handle, /c/name and /user/name URLs (and bare @handles) all need a page
# fetch to find the channel id.
_HANDLE_URL_RE = re.compile(
    r"youtube\.com/(@[\w.-]+|c/[\w.-]+|user/[\w.-]+)", re.IGNORECASE
)
_HANDLE_RE = re.compile(r"^@[\w.-]+$")

_PAGE_CHANNEL_ID_RE = re.compile(r'"channelId":"(UC[0-9A-Za-z_-]{22})"')
_PAGE_TITLE_RE = re.compile(r'<meta property="og:title" content="([^"]*)"')


def _youtube_candidate(channel_id: str, title: str) -> SourceCandidate:
    template = builtin_template("YouTube Channel")
    return SourceCandidate(
        name=title,
        url=template.create_rss_url(channel_id=channel_id),
        template_name_hash=template.name_hash,
        template_parameters={"channel_id": channel_id},
    )


def resolve_youtube_channel(page_url: str) -> Tuple[str, str]:
    """Fetch a YouTube channel page and return (channel_id, title).

    Raises on network errors or when no channel id is present (deleted or
    mistyped channels)."""
    resp = httpx.get(
        page_url,
        timeout=HTTP_TIMEOUT_SECONDS,
        follow_redirects=True,
        headers={"User-Agent": "aggy-subscription-import"},
    )
    resp.raise_for_status()
    id_match = _PAGE_CHANNEL_ID_RE.search(resp.text)
    if not id_match:
        raise ValueError("no channel id found on page")
    title_match = _PAGE_TITLE_RE.search(resp.text)
    title = title_match.group(1) if title_match else ""
    return id_match.group(1), title


def _parse_youtube_takeout_csv(text: str) -> List[SourceCandidate]:
    reader = csv.DictReader(io.StringIO(text))
    # Takeout headers: "Channel Id", "Channel Url", "Channel Title"
    fields = {(f or "").strip().lower(): f for f in (reader.fieldnames or [])}
    id_field = fields.get("channel id")
    title_field = fields.get("channel title")
    candidates = []
    for row in reader:
        channel_id = (row.get(id_field) or "").strip()
        if not _CHANNEL_ID_RE.match(channel_id):
            continue
        title = (row.get(title_field) or "").strip() if title_field else ""
        candidates.append(_youtube_candidate(channel_id, title or channel_id))
    return candidates


def parse_youtube(
    text: str,
    resolver: Callable[[str], Tuple[str, str]] = resolve_youtube_channel,
) -> Tuple[List[SourceCandidate], List[str]]:
    """Parse a Google Takeout subscriptions.csv or pasted channel
    URLs/handles/IDs into YouTube channel source candidates.

    ``resolver`` fetches a channel page to turn handles into channel IDs;
    injectable so tests never touch the network."""
    first_line = (text or "").strip().splitlines()[0:1]
    if first_line and "channel id" in first_line[0].lower():
        return _dedupe(_parse_youtube_takeout_csv(text)), []

    candidates: List[SourceCandidate] = []
    warnings: List[str] = []
    skipped: List[str] = []
    to_resolve: List[Tuple[str, str]] = []  # (display label, page url)

    for token in _tokenize(text):
        id_url = _CHANNEL_URL_RE.search(token)
        if id_url:
            channel_id = id_url.group(1)
            candidates.append(_youtube_candidate(channel_id, channel_id))
            continue
        if _CHANNEL_ID_RE.match(token):
            candidates.append(_youtube_candidate(token, token))
            continue
        handle_url = _HANDLE_URL_RE.search(token)
        if handle_url:
            path = handle_url.group(1)
            to_resolve.append((path, f"https://www.youtube.com/{path}"))
            continue
        if _HANDLE_RE.match(token):
            to_resolve.append((token, f"https://www.youtube.com/{token}"))
            continue
        skipped.append(token)

    if len(to_resolve) > MAX_YOUTUBE_RESOLUTIONS:
        warnings.append(
            f"Only the first {MAX_YOUTUBE_RESOLUTIONS} handles/custom URLs were "
            f"looked up ({len(to_resolve)} given). Channel IDs and Takeout CSV "
            "imports have no limit."
        )
        to_resolve = to_resolve[:MAX_YOUTUBE_RESOLUTIONS]

    for label, page_url in to_resolve:
        try:
            channel_id, title = resolver(page_url)
            candidates.append(_youtube_candidate(channel_id, title or label))
        except Exception as e:
            logging.info(f"youtube channel resolution failed for {page_url}: {e}")
            candidates.append(
                SourceCandidate(name=label, error="Couldn't find this channel")
            )

    if skipped:
        shown = ", ".join(skipped[:5])
        more = f" (and {len(skipped) - 5} more)" if len(skipped) > 5 else ""
        warnings.append(f"Skipped {len(skipped)} unrecognized entries: {shown}{more}")
    return _dedupe(candidates), warnings


# ---------------------------------------------------------------------------
# OPML (any RSS reader / podcast app export)
# ---------------------------------------------------------------------------


def parse_opml(text: str) -> Tuple[List[SourceCandidate], List[str]]:
    """Parse an OPML export into source candidates, keeping the folder each
    feed was filed under as a grouping hint."""
    try:
        root = ET.fromstring(text or "")
    except ET.ParseError as e:
        raise ValueError(f"Not a valid OPML file: {e}")

    candidates: List[SourceCandidate] = []

    def walk(outline, group: Optional[str]):
        for child in outline.findall("outline"):
            xml_url = child.get("xmlUrl")
            title = (child.get("title") or child.get("text") or "").strip()
            if xml_url:
                candidates.append(
                    SourceCandidate(
                        name=title or xml_url,
                        url=xml_url,
                        group=group,
                    )
                )
            else:
                # a folder: its title groups everything nested below it
                walk(child, title or group)

    body = root.find("body")
    if body is None:
        raise ValueError("Not a valid OPML file: missing <body>")
    walk(body, None)

    warnings = []
    if not candidates:
        warnings.append("No feeds found in this OPML file")
    return _dedupe(candidates), warnings


# ---------------------------------------------------------------------------
# Bluesky
# ---------------------------------------------------------------------------

_BSKY_PROFILE_URL_RE = re.compile(r"bsky\.app/profile/([^/\s?]+)", re.IGNORECASE)


def normalize_bluesky_handle(raw: str) -> str:
    """Accept '@handle', a bsky.app profile URL, or a bare handle; bare
    names get the default .bsky.social suffix."""
    handle = (raw or "").strip()
    m = _BSKY_PROFILE_URL_RE.search(handle)
    if m:
        handle = m.group(1)
    handle = handle.lstrip("@").rstrip("/")
    if handle and "." not in handle:
        handle = f"{handle}.bsky.social"
    return handle


def fetch_bluesky_follows(handle: str) -> Tuple[List[SourceCandidate], List[str]]:
    """List every account ``handle`` follows via Bluesky's public (no-auth)
    API; each becomes a candidate pointing at the account's native RSS."""
    handle = normalize_bluesky_handle(handle)
    if not handle:
        raise ValueError("Enter a Bluesky handle, e.g. jay.bsky.team")

    template = builtin_template("Bluesky User")
    candidates: List[SourceCandidate] = []
    warnings: List[str] = []
    cursor = None

    with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS) as client:
        while len(candidates) < MAX_BLUESKY_FOLLOWS:
            params = {"actor": handle, "limit": 100}
            if cursor:
                params["cursor"] = cursor
            resp = client.get(BLUESKY_FOLLOWS_API, params=params)
            if resp.status_code == 400:
                detail = resp.json().get("message", "unknown account")
                raise ValueError(f"Bluesky couldn't find that account: {detail}")
            resp.raise_for_status()
            data = resp.json()
            for follow in data.get("follows", []):
                follow_handle = follow.get("handle", "")
                # accounts deleted/deactivated since being followed
                if not follow_handle or follow_handle == "handle.invalid":
                    continue
                display = (follow.get("displayName") or "").strip()
                candidates.append(
                    SourceCandidate(
                        name=display or follow_handle,
                        url=template.create_rss_url(handle=follow_handle),
                        template_name_hash=template.name_hash,
                        template_parameters={"handle": follow_handle},
                    )
                )
            cursor = data.get("cursor")
            if not cursor:
                break
        else:
            warnings.append(f"Stopped after the first {MAX_BLUESKY_FOLLOWS} follows")

    if not candidates:
        warnings.append(f"@{handle} doesn't follow any accounts")
    return _dedupe(candidates), warnings
