import pytest

from bridge.analyze import (
    AnalyzeError,
    condense_html,
    detect_source_type,
    discover_feed_url,
    feed_covers_page,
    fetch_page,
    php_time_format_to_strptime,
    suggest_source_name,
    validate_suggestions,
)


SAMPLE_HTML = """
<html>
<head>
  <title>Example Blog | Great Posts</title>
  <script>var tracking = "junk";</script>
  <style>.post { color: red; }</style>
</head>
<body>
  <nav><a href="/about">About</a></nav>
  <div class="posts">
    <div class="post">
      <h2 class="post-title"><a href="/blog/one">First post</a></h2>
      <span class="author">Alice</span>
      <time datetime="2026-01-01T10:00:00+00:00">Jan 1</time>
      <p>Summary of the first post</p>
    </div>
    <div class="post">
      <h2 class="post-title"><a href="/blog/two">Second post</a></h2>
      <span class="author">Bob</span>
      <time datetime="2026-01-02T10:00:00+00:00">Jan 2</time>
      <p>Summary of the second post</p>
    </div>
    <div class="post">
      <h2 class="post-title"><a href="/blog/three">Third post</a></h2>
      <span class="author">Carol</span>
      <time datetime="2026-01-03T10:00:00+00:00">Jan 3</time>
      <p>Summary of the third post</p>
    </div>
  </div>
</body>
</html>
"""

RAW_SUGGESTIONS = {
    "entry_element_selector": ["div.post", "div.nonexistent", "nav a"],
    "title_selector": ["h2.post-title", "h5.missing"],
    "url_selector": ["a"],
    "author_selector": ["span.author"],
    "time_selector": [
        {"selector": "time", "php_time_format": "Y-m-d\\TH:i:sP"},
        {"selector": "time", "php_time_format": "duplicate ignored"},
        {"selector": "p", "php_time_format": "Y-m-d"},
    ],
}


def test_validate_suggestions_keeps_only_working_selectors():
    result = validate_suggestions(
        SAMPLE_HTML, "https://example.com/blog/", RAW_SUGGESTIONS
    )

    entries = result["entry_element_selector"]
    # div.nonexistent matches nothing; nav a matches only one element
    assert [c.selector for c in entries] == ["div.post"]
    assert entries[0].match_count == 3
    assert "First post" in entries[0].samples[0]

    titles = result["title_selector"]
    assert [c.selector for c in titles] == ["h2.post-title"]
    assert titles[0].match_count == 3
    assert titles[0].samples[0] == "First post"

    urls = result["url_selector"]
    assert urls[0].selector == "a"
    # hrefs are resolved against the page URL for readable samples
    assert urls[0].samples[0] == "https://example.com/blog/one"

    authors = result["author_selector"]
    assert [c.selector for c in authors] == ["span.author"]

    times = result["time_selector"]
    # the <p> selector's text doesn't parse as a date; the duplicate is dropped
    assert len(times) == 1
    assert times[0].selector == "time"
    assert times[0].time_format == "Y-m-d\\TH:i:sP"
    assert times[0].samples[0] == "2026-01-01T10:00:00+00:00"


def test_validate_suggestions_errors_without_entry_candidates():
    with pytest.raises(AnalyzeError):
        validate_suggestions(
            SAMPLE_HTML,
            "https://example.com/",
            {"entry_element_selector": ["div.nope", ":::garbage:::"]},
        )


def test_condense_html_strips_noise_and_truncates_text():
    condensed = condense_html(SAMPLE_HTML)
    assert "tracking" not in condensed  # scripts removed
    assert "color: red" not in condensed  # styles removed
    assert 'class="post-title"' in condensed  # identifying attrs kept
    assert "First post" in condensed  # text kept


def test_condense_html_caps_length_and_collapses_repeats():
    huge = "<body>" + "<div class='x'><span>word</span></div>" * 20000 + "</body>"
    condensed = condense_html(huge)
    assert len(condensed) <= 60_000
    # repeated identical siblings collapse to a few exemplars
    assert condensed.count('<div class="x">') == 8


def test_php_time_format_to_strptime():
    assert php_time_format_to_strptime("Y-m-d\\TH:i:sP") == "%Y-%m-%dT%H:%M:%S%z"
    assert php_time_format_to_strptime("d/m/Y") == "%d/%m/%Y"
    with pytest.raises(ValueError):
        php_time_format_to_strptime("Y-m-d U")  # U (unix epoch) unsupported


def test_fetch_page_rejects_non_http_urls():
    for url in ("ftp://example.com", "file:///etc/passwd", "not a url"):
        with pytest.raises(AnalyzeError):
            fetch_page(url)


def test_suggest_source_name():
    assert (
        suggest_source_name("Latest news | Some Site", "https://some.site/")
        == "Latest news"
    )
    assert suggest_source_name("", "https://some.site/news") == "some.site"


RSS_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Some Blog Feed</title>
    <item><title>First</title><link>https://some.site/one</link></item>
  </channel>
</rss>
"""

HTML_WITH_FEED_LINK = """
<html>
<head>
  <title>Some Blog | Home</title>
  <link rel="alternate" type="application/rss+xml" href="/feed.xml">
</head>
<body><a href="/one">First</a></body>
</html>
"""


def test_detect_source_type_recognises_a_feed(monkeypatch):
    monkeypatch.setattr("bridge.analyze.fetch_page", lambda url, cookie="": RSS_FEED)
    result = detect_source_type("https://some.site/feed")
    assert result["kind"] == "feed"
    assert result["feed_url"] == "https://some.site/feed"
    assert result["suggested_source_name"] == "Some Blog Feed"


def test_detect_source_type_discovers_advertised_feed(monkeypatch):
    monkeypatch.setattr(
        "bridge.analyze.fetch_page", lambda url, cookie="": HTML_WITH_FEED_LINK
    )
    result = detect_source_type("https://some.site/")
    assert result["kind"] == "feed"
    # the relative href is resolved against the page URL
    assert result["feed_url"] == "https://some.site/feed.xml"
    assert result["suggested_source_name"] == "Some Blog"


def test_detect_source_type_falls_back_to_html(monkeypatch):
    monkeypatch.setattr("bridge.analyze.fetch_page", lambda url, cookie="": SAMPLE_HTML)
    result = detect_source_type("https://example.com/blog/")
    assert result["kind"] == "html"
    assert result["feed_url"] is None
    assert result["suggested_source_name"] == "Example Blog"


# A section page that advertises the site's own catch-all feed: the feed
# exists, but it lists articles from everywhere on the site rather than the
# ones this page shows.
SECTION_PAGE_WITH_SITE_FEED = """
<html>
<head>
  <title>Some Section | Some Site</title>
  <link rel="alternate" type="application/rss+xml" href="/rss" title="Site feed">
</head>
<body>
  <a href="/watch?v=in-section-1">One</a>
  <a href="/watch?v=in-section-2">Two</a>
  <a href="/watch?v=in-section-3">Three</a>
</body>
</html>
"""

SITE_WIDE_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Some Site</title>
    <item><link>https://some.site/watch?v=elsewhere-1</link></item>
    <item><link>https://some.site/watch?v=elsewhere-2</link></item>
    <item><link>https://some.site/watch?v=elsewhere-3</link></item>
  </channel>
</rss>
"""

# the same page's articles, as a feed
MATCHING_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Some Section</title>
    <item><link>https://some.site/watch?v=in-section-1</link></item>
    <item><link>https://some.site/watch?v=in-section-2</link></item>
    <item><link>https://some.site/watch?v=in-section-3</link></item>
  </channel>
</rss>
"""


def test_detect_source_type_rejects_a_feed_that_misses_the_page(monkeypatch):
    """A site-wide feed linked from a section page isn't that page's feed."""
    monkeypatch.setattr(
        "bridge.analyze.fetch_page", lambda url, cookie="": SECTION_PAGE_WITH_SITE_FEED
    )
    monkeypatch.setattr(
        "bridge.analyze.fetch_feed_entry_links",
        lambda feed_url, cookie="": [
            "https://some.site/watch?v=elsewhere-1",
            "https://some.site/watch?v=elsewhere-2",
            "https://some.site/watch?v=elsewhere-3",
        ],
    )

    result = detect_source_type("https://some.site/sections/some-section")

    # scraping the page is the only way to get the articles it actually shows
    assert result["kind"] == "html"
    assert result["feed_url"] is None
    # ...but the feed we found is still offered to the user
    assert result["site_feed_url"] == "https://some.site/rss"


def test_detect_source_type_keeps_a_feed_that_matches_the_page(monkeypatch):
    monkeypatch.setattr(
        "bridge.analyze.fetch_page", lambda url, cookie="": SECTION_PAGE_WITH_SITE_FEED
    )
    monkeypatch.setattr(
        "bridge.analyze.fetch_feed_entry_links",
        lambda feed_url, cookie="": [
            "https://some.site/watch?v=in-section-1",
            "https://some.site/watch?v=in-section-2",
            "https://some.site/watch?v=in-section-3",
        ],
    )

    result = detect_source_type("https://some.site/sections/some-section")

    assert result["kind"] == "feed"
    assert result["feed_url"] == "https://some.site/rss"


def test_feed_covers_page_trusts_the_url_when_it_matches_the_section():
    """A feed under (or named after) the page's path needs no content check."""
    # would raise if it tried to fetch, since no fetch is stubbed here
    assert feed_covers_page(
        "https://some.site/sections/some-section/rss",
        "https://some.site/sections/some-section",
        SECTION_PAGE_WITH_SITE_FEED,
    )
    assert feed_covers_page(
        "https://some.site/rss?section=some-section",
        "https://some.site/sections/some-section",
        SECTION_PAGE_WITH_SITE_FEED,
    )


def test_feed_covers_page_accepts_any_feed_advertised_by_the_site_root():
    """A front page's feed is the site's feed, so it needs no content check."""
    assert feed_covers_page(
        "https://some.site/rss", "https://some.site/", SECTION_PAGE_WITH_SITE_FEED
    )


def test_feed_covers_page_falls_back_to_scraping_when_the_feed_is_unreadable(
    monkeypatch,
):
    monkeypatch.setattr(
        "bridge.analyze.fetch_feed_entry_links", lambda feed_url, cookie="": []
    )
    assert not feed_covers_page(
        "https://some.site/rss",
        "https://some.site/sections/some-section",
        SECTION_PAGE_WITH_SITE_FEED,
    )


# feedparser reports a version for an ordinary HTML page that happens to
# declare the Atom namespace, so entries are what actually prove it's a feed
HTML_DECLARING_A_FEED_NAMESPACE = """
<html xmlns:atom="http://www.w3.org/2005/Atom">
<head><title>Some Blog | Home</title></head>
<body>
  <div class="post"><a href="/one">First</a></div>
  <div class="post"><a href="/two">Second</a></div>
</body>
</html>
"""


def test_detect_source_type_ignores_a_feed_namespace_without_entries(monkeypatch):
    monkeypatch.setattr(
        "bridge.analyze.fetch_page",
        lambda url, cookie="": HTML_DECLARING_A_FEED_NAMESPACE,
    )
    result = detect_source_type("https://some.site/blog/")
    assert result["kind"] == "html"
    assert result["feed_url"] is None


def test_detect_source_type_handles_an_empty_response(monkeypatch):
    monkeypatch.setattr("bridge.analyze.fetch_page", lambda url, cookie="": "")
    result = detect_source_type("https://some.site/blog/")
    assert result["kind"] == "html"


def test_discover_feed_url_ignores_non_feed_links():
    html = """
    <html><head>
      <link rel="stylesheet" href="/style.css">
      <link rel="alternate" type="application/json" href="/feed.json">
    </head><body></body></html>
    """
    assert discover_feed_url(html, "https://some.site/") is None
