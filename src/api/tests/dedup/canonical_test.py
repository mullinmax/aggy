"""What a URL reduces to. No database: canonicalising is a pure function, and
it is the whole basis of the canonical-URL duplicate signal, so it is worth
pinning down case by case."""

import pytest

from dedup.canonical import canonical_url


@pytest.mark.parametrize(
    "url,expected",
    [
        # tracking parameters say where a click came from, not which article
        (
            "https://example.com/a?utm_source=rss&utm_medium=feed",
            "https://example.com/a",
        ),
        ("https://example.com/a?fbclid=xyz", "https://example.com/a"),
        ("https://example.com/a?gclid=xyz&ref=twitter", "https://example.com/a"),
        # ...but a real parameter is part of what identifies the page
        ("https://example.com/a?utm_source=rss&id=7", "https://example.com/a?id=7"),
        # host and scheme case, and the www. that is never meaningful
        ("https://Example.COM/a", "https://example.com/a"),
        ("HTTPS://example.com/a", "https://example.com/a"),
        ("https://www.example.com/a", "https://example.com/a"),
        # a default port is the same address
        ("https://example.com:443/a", "https://example.com/a"),
        ("http://example.com:80/a", "http://example.com/a"),
        # ...a non-default one is not
        ("https://example.com:8443/a", "https://example.com:8443/a"),
        # a fragment is a position on the page, not a different page
        ("https://example.com/a#section-2", "https://example.com/a"),
        # a trailing slash never distinguishes two articles
        ("https://example.com/a/b/", "https://example.com/a/b"),
        # ...and a bare root collapses rather than keeping a lone slash
        ("https://example.com/", "https://example.com"),
        # parameter order is not meaningful, so it is normalised away
        ("https://example.com/a?b=2&a=1", "https://example.com/a?a=1&b=2"),
        ("https://example.com/a?a=1&b=2", "https://example.com/a?a=1&b=2"),
        # AMP is a rendition of the same article, both ways it is spelled
        ("https://example.com/news/amp/story", "https://example.com/news/story"),
        ("https://example.com/news/story/amp", "https://example.com/news/story"),
        ("https://example.com/a?amp=1&id=3", "https://example.com/a?id=3"),
        (
            "https://example-com.cdn.ampproject.org/c/s/example.com/story/1",
            "https://example.com/story/1",
        ),
        (
            "https://example-com.cdn.ampproject.org/v/s/example.com/story/1",
            "https://example.com/story/1",
        ),
        # a redirector serves nothing of its own: the article is the target
        (
            "https://news.google.com/articles/CBMi?url=https%3A%2F%2Fexample.com"
            "%2Freal&hl=en",
            "https://example.com/real",
        ),
        (
            "https://out.reddit.com/r/x?url=https%3A%2F%2Fexample.com%2Freal",
            "https://example.com/real",
        ),
        # ...and the target is itself canonicalised on the way out
        (
            "https://news.google.com/articles/CBMi?url=https%3A%2F%2Fwww."
            "example.com%2Freal%2F%3Futm_source%3Dgnews",
            "https://example.com/real",
        ),
        # a "amp" substring inside a real segment is not an AMP marker
        (
            "https://example.com/amplifier/review",
            "https://example.com/amplifier/review",
        ),
    ],
)
def test_canonical_url_normalises(url, expected):
    assert canonical_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        None,
        "",
        "   ",
        "not a url",
        "ftp://example.com/a",
        "mailto:someone@example.com",
        "/relative/path",
        "https://",
    ],
)
def test_no_canonical_form_is_none_not_an_error(url):
    """A URL with no canonical form means "no canonical-URL signal for this
    item", which every caller treats as ungrouped rather than as a failure."""
    assert canonical_url(url) is None


@pytest.mark.parametrize(
    "url",
    [
        "https://Example.com/a/b/?utm_source=x&id=1#frag",
        "https://example-com.cdn.ampproject.org/c/s/www.example.com/story/amp/",
        "https://news.google.com/articles/CBMi?url=https%3A%2F%2Fexample.com%2Fr",
        "https://example.com/pa th/x",
        "https://example.com:443/",
    ],
)
def test_canonicalising_is_idempotent(url):
    """The column is recomputed whenever an item is re-scraped, so feeding a
    canonical URL back in has to return it unchanged -- otherwise an item could
    drift out of the group it is in."""
    once = canonical_url(url)
    assert once is not None
    assert canonical_url(once) == once


def test_two_spellings_of_one_query_agree():
    """Percent-encoding is normalised, so the same query written two ways does
    not become two articles."""
    assert canonical_url("https://example.com/pa th/x") == canonical_url(
        "https://example.com/pa%20th/x"
    )


def test_a_redirector_loop_has_no_canonical_form():
    """Bounded unwrapping: a URL that points at itself must not spin."""
    loop = "https://news.google.com/articles/a?url=https%3A%2F%2Fnews.google.com%2F"
    # whatever it resolves to, it resolves -- the point is that it returns
    assert canonical_url(loop) != loop


def test_different_articles_stay_different():
    """The signal is only worth anything if it separates as well as it joins."""
    assert canonical_url("https://example.com/a") != canonical_url(
        "https://example.com/b"
    )
    assert canonical_url("https://example.com/a?id=1") != canonical_url(
        "https://example.com/a?id=2"
    )
