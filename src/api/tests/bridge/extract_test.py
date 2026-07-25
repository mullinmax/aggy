from bridge.extract import extract_entries


LISTING_HTML = """
<html><body>
  <nav><a href="/about">About</a></nav>
  <div class="feed">
    <article class="card">
      <a class="link" href="/posts/one"><h3>First post</h3></a>
      <img data-src="/thumbs/one.jpg" src="data:image/gif;base64,placeholder">
      <span class="by">Alice</span>
      <time datetime="2026-01-01T10:00:00+00:00">Jan 1</time>
      <p>Some words about the first post.</p>
    </article>
    <article class="card">
      <a class="link" href="https://elsewhere.example/two"><h3>Second post</h3></a>
      <img srcset="https://cdn.example.com/two-small.jpg 400w, https://cdn.example.com/two.jpg 800w">
      <span class="by">Bob</span>
      <time datetime="2026-01-02T10:00:00+00:00">Jan 2</time>
    </article>
    <article class="card">
      <h3>Third post, with no link at all</h3>
    </article>
  </div>
</body></html>
"""

BASE_URL = "https://example.com/blog/"

SELECTORS = {
    "entry_element_selector": "article.card",
    "title_selector": "h3",
    "url_selector": "a.link",
    "author_selector": "span.by",
    "time_selector": "time",
    "time_format": "Y-m-d\\TH:i:sP",
}


def test_extracts_titles_authors_and_absolute_urls():
    entries = extract_entries(LISTING_HTML, BASE_URL, SELECTORS)

    assert [entry["title"] for entry in entries] == ["First post", "Second post"]
    assert [entry["author"] for entry in entries] == ["Alice", "Bob"]
    # relative against the page, absolute left alone
    assert entries[0]["url"] == "https://example.com/posts/one"
    assert entries[1]["url"] == "https://elsewhere.example/two"


def test_drops_entries_without_a_link():
    """There'd be nothing to open, and nothing to deduplicate on."""
    entries = extract_entries(LISTING_HTML, BASE_URL, SELECTORS)

    assert all("no link at all" not in (entry["title"] or "") for entry in entries)


def test_finds_lazy_loaded_thumbnails():
    """Listing pages routinely leave `src` as a placeholder until the image
    scrolls into view, with the real one in a data attribute."""
    entries = extract_entries(LISTING_HTML, BASE_URL, SELECTORS)

    assert entries[0]["image"] == "https://example.com/thumbs/one.jpg"


def test_reads_the_first_srcset_candidate_when_there_is_no_src():
    entries = extract_entries(LISTING_HTML, BASE_URL, SELECTORS)

    assert entries[1]["image"] == "https://cdn.example.com/two-small.jpg"


def test_parses_times_with_the_php_format_the_analyzer_chose():
    entries = extract_entries(LISTING_HTML, BASE_URL, SELECTORS)

    assert entries[0]["date_published"].year == 2026
    assert entries[0]["date_published"].month == 1


def test_a_time_format_that_does_not_parse_is_left_empty():
    """Better a missing date than a wrong one; the bridge would abort the
    whole render here."""
    entries = extract_entries(
        LISTING_HTML, BASE_URL, {**SELECTORS, "time_format": "d/m/Y"}
    )

    assert entries[0]["date_published"] is None


def test_falls_back_to_the_link_text_when_the_title_selector_misses():
    entries = extract_entries(
        LISTING_HTML, BASE_URL, {**SELECTORS, "title_selector": "h9.nope"}
    )

    assert entries[0]["title"] == "First post"


def test_entry_text_stands_in_for_the_article_body():
    entries = extract_entries(LISTING_HTML, BASE_URL, SELECTORS)

    assert "Some words about the first post." in entries[0]["text"]


def test_limit_caps_the_entries_returned():
    entries = extract_entries(LISTING_HTML, BASE_URL, {**SELECTORS, "limit": "1"})

    assert len(entries) == 1


def test_requires_an_entry_selector():
    try:
        extract_entries(LISTING_HTML, BASE_URL, {"title_selector": "h3"})
    except Exception as e:
        assert "entry selector" in str(e)
    else:  # pragma: no cover - the call above must raise
        raise AssertionError("expected a missing-selector error")


def test_an_invalid_selector_matches_nothing_instead_of_raising():
    entries = extract_entries(
        LISTING_HTML, BASE_URL, {**SELECTORS, "entry_element_selector": "article.["}
    )

    assert entries == []
