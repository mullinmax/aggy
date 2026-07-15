import pytest

import bulk_import
from bulk_import import (
    fetch_bluesky_follows,
    normalize_bluesky_handle,
    parse_opml,
    parse_reddit,
    parse_youtube,
)


# ---------------------------------------------------------------------------
# reddit
# ---------------------------------------------------------------------------


def test_parse_reddit_export_csv():
    candidates, warnings = parse_reddit("subreddit\nselfhosted\nalligators\n")

    assert warnings == []
    assert [c.name for c in candidates] == ["r/selfhosted", "r/alligators"]
    assert candidates[0].url == "https://www.reddit.com/r/selfhosted/top.rss?t=day"
    assert candidates[0].template_parameters == {"subreddit": "selfhosted"}
    assert candidates[0].template_name_hash


def test_parse_reddit_pasted_mixed_formats():
    text = "r/foo, /r/bar\nhttps://www.reddit.com/r/baz/ https://old.reddit.com/r/qux"
    candidates, warnings = parse_reddit(text)

    assert [c.name for c in candidates] == ["r/foo", "r/bar", "r/baz", "r/qux"]
    assert warnings == []


def test_parse_reddit_dedupes_and_warns_on_junk():
    candidates, warnings = parse_reddit("r/foo\nfoo\n!!!")

    assert [c.name for c in candidates] == ["r/foo"]
    assert len(warnings) == 1
    assert "!!!" in warnings[0]


# ---------------------------------------------------------------------------
# youtube
# ---------------------------------------------------------------------------

CHANNEL_ID = "UCXuqSBlHAE6Xw-yeJA0Tunw"
OTHER_CHANNEL_ID = "UCsXVk37bltHxD1rDPwtNM8Q"

TAKEOUT_CSV = (
    "Channel Id,Channel Url,Channel Title\n"
    f"{CHANNEL_ID},http://www.youtube.com/channel/{CHANNEL_ID},Linus Tech Tips\n"
    f"{OTHER_CHANNEL_ID},http://www.youtube.com/channel/{OTHER_CHANNEL_ID},Kurzgesagt\n"
)


def test_parse_youtube_takeout_csv():
    candidates, warnings = parse_youtube(TAKEOUT_CSV, resolver=None)

    assert warnings == []
    assert [c.name for c in candidates] == ["Linus Tech Tips", "Kurzgesagt"]
    assert candidates[0].url == (
        f"https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL_ID}"
    )
    assert candidates[0].template_parameters == {"channel_id": CHANNEL_ID}


def test_parse_youtube_pasted_ids_and_urls_need_no_resolution():
    text = f"https://www.youtube.com/channel/{CHANNEL_ID}\n{OTHER_CHANNEL_ID}"
    candidates, warnings = parse_youtube(text, resolver=None)

    assert warnings == []
    assert [c.template_parameters["channel_id"] for c in candidates] == [
        CHANNEL_ID,
        OTHER_CHANNEL_ID,
    ]


def test_parse_youtube_resolves_handles():
    resolved = []

    def resolver(page_url):
        resolved.append(page_url)
        return CHANNEL_ID, "Veritasium"

    candidates, warnings = parse_youtube(
        "@veritasium https://www.youtube.com/@veritasium", resolver=resolver
    )

    # the handle and its URL form resolve to the same channel and dedupe
    assert resolved == [
        "https://www.youtube.com/@veritasium",
        "https://www.youtube.com/@veritasium",
    ]
    assert len(candidates) == 1
    assert candidates[0].name == "Veritasium"
    assert candidates[0].template_parameters == {"channel_id": CHANNEL_ID}


def test_parse_youtube_marks_failed_resolutions():
    def resolver(page_url):
        raise ValueError("no channel id found on page")

    candidates, _ = parse_youtube("@doesnotexist", resolver=resolver)

    assert len(candidates) == 1
    assert candidates[0].url is None
    assert candidates[0].error


# ---------------------------------------------------------------------------
# opml
# ---------------------------------------------------------------------------

OPML = """<?xml version="1.0" encoding="UTF-8"?>
<opml version="2.0">
  <head><title>Subscriptions</title></head>
  <body>
    <outline text="Tech">
      <outline text="Hacker News" xmlUrl="https://news.ycombinator.com/rss"/>
      <outline text="Lobsters" title="Lobsters!" xmlUrl="https://lobste.rs/rss"/>
    </outline>
    <outline text="No Folder" xmlUrl="https://example.com/feed.xml"/>
  </body>
</opml>
"""


def test_parse_opml_keeps_folder_groups():
    candidates, warnings = parse_opml(OPML)

    assert warnings == []
    assert [(c.name, c.group) for c in candidates] == [
        ("Hacker News", "Tech"),
        ("Lobsters!", "Tech"),
        ("No Folder", None),
    ]
    assert candidates[0].url == "https://news.ycombinator.com/rss"


def test_parse_opml_rejects_invalid_xml():
    with pytest.raises(ValueError):
        parse_opml("this is not opml")


# ---------------------------------------------------------------------------
# bluesky
# ---------------------------------------------------------------------------


def test_normalize_bluesky_handle():
    assert normalize_bluesky_handle("@jay.bsky.team") == "jay.bsky.team"
    assert normalize_bluesky_handle("jay") == "jay.bsky.social"
    assert (
        normalize_bluesky_handle("https://bsky.app/profile/jay.bsky.team")
        == "jay.bsky.team"
    )


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload
        self.status_code = 200

    def json(self):
        return self.payload

    def raise_for_status(self):
        pass


class _FakeClient:
    """Stands in for httpx.Client, returning canned paginated responses."""

    def __init__(self, pages):
        self.pages = list(pages)
        self.requests = []

    def __call__(self, **kwargs):  # httpx.Client(...) -> self
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, url, params=None):
        self.requests.append(params)
        return _FakeResponse(self.pages.pop(0))


def test_fetch_bluesky_follows_paginates(monkeypatch):
    pages = [
        {
            "cursor": "page2",
            "follows": [
                {"handle": "alice.bsky.social", "displayName": "Alice"},
                {"handle": "handle.invalid", "displayName": "Deleted"},
            ],
        },
        {
            "follows": [{"handle": "bob.example.com", "displayName": ""}],
        },
    ]
    fake = _FakeClient(pages)
    monkeypatch.setattr(bulk_import.httpx, "Client", fake)

    candidates, warnings = fetch_bluesky_follows("@me.bsky.social")

    assert warnings == []
    assert fake.requests[0]["actor"] == "me.bsky.social"
    assert fake.requests[1]["cursor"] == "page2"
    # deleted accounts are skipped; missing display names fall back to handle
    assert [(c.name, c.url) for c in candidates] == [
        ("Alice", "https://bsky.app/profile/alice.bsky.social/rss"),
        ("bob.example.com", "https://bsky.app/profile/bob.example.com/rss"),
    ]
    assert candidates[0].template_parameters == {"handle": "alice.bsky.social"}


def test_fetch_bluesky_follows_rejects_empty_handle():
    with pytest.raises(ValueError):
        fetch_bluesky_follows("   ")
