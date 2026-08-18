import pytest

from db.source import Source
from db.source_template import SourceTemplate, SourceTemplateParameter


def test_sources_are_rss_unless_told_otherwise(existing_source):
    """Every source predating the other backends is a feed URL, and the
    column default has to keep them that way."""
    stored = Source.read(
        user_hash=existing_source.user_hash,
        feed_hash=existing_source.feed_hash,
        source_hash=existing_source.name_hash,
    )

    assert stored.kind == "rss"
    assert stored.config is None


def test_kind_and_config_survive_a_round_trip(existing_feed):
    selectors = {
        "home_page": "https://example.com/blog/",
        "entry_element_selector": "article.card",
        "render": True,
    }
    source = Source(
        user_hash=existing_feed.user_hash,
        feed_hash=existing_feed.name_hash,
        name="Scraped source",
        url="https://example.com/blog/",
        kind="html",
        config=selectors,
    )
    source.create()

    stored = Source.read(
        user_hash=source.user_hash,
        feed_hash=source.feed_hash,
        source_hash=source.name_hash,
    )

    assert stored.kind == "html"
    assert stored.config == selectors


def test_update_replaces_a_scraped_sources_selectors(existing_feed):
    source = Source(
        user_hash=existing_feed.user_hash,
        feed_hash=existing_feed.name_hash,
        name="Scraped source",
        url="https://example.com/blog/",
        kind="html",
        config={"entry_element_selector": "article.card"},
    )
    source.create()

    source.update(
        name=source.name,
        url=str(source.url),
        config={"entry_element_selector": "li.post"},
    )

    stored = Source.read(
        user_hash=source.user_hash,
        feed_hash=source.feed_hash,
        source_hash=source.name_hash,
    )
    assert stored.config == {"entry_element_selector": "li.post"}


def test_update_leaves_config_alone_when_it_is_not_given(existing_feed):
    source = Source(
        user_hash=existing_feed.user_hash,
        feed_hash=existing_feed.name_hash,
        name="Scraped source",
        url="https://example.com/blog/",
        kind="html",
        config={"entry_element_selector": "article.card"},
    )
    source.create()

    source.update(name="Renamed", url=str(source.url))

    stored = Source.read(
        user_hash=source.user_hash,
        feed_hash=source.feed_hash,
        source_hash=source.name_hash,
    )
    assert stored.config == {"entry_element_selector": "article.card"}


# ---------- template parameter escaping ----------


def _template(quote: str, url_template: str) -> SourceTemplate:
    return SourceTemplate(
        name=f"Test {quote}",
        url="https://example.com",
        url_template=url_template,
        description="test",
        parameters={
            "value": SourceTemplateParameter(
                name="Value", required=True, type="text", quote=quote
            )
        },
    )


def test_strict_parameters_cannot_escape_their_place_in_the_url():
    template = _template("strict", "https://example.com/{value}/feed")

    url = template.create_source_url(value="../../admin")

    assert url == "https://example.com/..%2F..%2Fadmin/feed"


def test_path_parameters_keep_their_slashes():
    """A route is several path segments and has to stay that way."""
    template = _template("path", "http://rsshub:1200/{value}")

    url = template.create_source_url(value="github/issue/owner/repo")

    assert url == "http://rsshub:1200/github/issue/owner/repo"


def test_whole_url_parameters_are_used_verbatim():
    template = _template("none", "{value}")

    url = template.create_source_url(value="https://videos.example.com/c/x?sort=new")

    assert url == "https://videos.example.com/c/x?sort=new"


def test_whole_url_parameters_must_actually_be_urls():
    """They skip escaping, so anything else would land in the URL unchecked."""
    template = _template("none", "{value}")

    with pytest.raises(Exception, match="must be a http"):
        template.create_source_url(value="javascript:alert(1)")


def test_template_kind_round_trips(unique_source_template):
    unique_source_template.kind = "ytdlp"
    unique_source_template.create()

    stored = SourceTemplate.read(name_hash=unique_source_template.name_hash)

    assert stored.kind == "ytdlp"
