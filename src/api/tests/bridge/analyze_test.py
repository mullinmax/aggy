import pytest

from bridge.analyze import (
    AnalyzeError,
    condense_html,
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
    assert len(condensed) <= 20_000
    # repeated identical siblings collapse to a few exemplars
    assert condensed.count('<div class="x">') == 5


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
