"""The catalog's labels: where a template comes from and what it will ask for.

With RSSHub's route catalog imported alongside rss-bridge's bridges, the
catalog holds templates from three different services, many with terse names
like "User posts". These are what let a result be told apart from its
neighbours.
"""

from constants import PROVIDER_BUILTIN, PROVIDER_RSSHUB, PROVIDER_RSS_BRIDGE
from db.source_template import SourceTemplate, SourceTemplateParameter


def _template(name, **kwargs) -> SourceTemplate:
    defaults = {
        "url": "https://example.com",
        "description": "an example template",
        "parameters": {},
    }
    return SourceTemplate(name=name, **{**defaults, **kwargs})


# ---------- provider ----------


def test_templates_without_a_bridge_are_aggys_own():
    template = _template("Reddit Subreddit", url_template="https://reddit.com/r/{x}")

    assert template.provider == PROVIDER_BUILTIN


def test_bridge_templates_are_labelled_rss_bridge():
    template = _template("Some Bridge", bridge_short_name="SomeBridge")

    assert template.provider == PROVIDER_RSS_BRIDGE


def test_imported_routes_are_labelled_rsshub():
    template = _template("User posts", bridge_short_name="rsshub:example/user/:uid")

    assert template.provider == PROVIDER_RSSHUB


# ---------- the rest of the label ----------


def test_site_domain_drops_the_www():
    template = _template("Example", url="https://www.example.com/some/path")

    assert template.site_domain == "example.com"


def test_required_and_optional_parameters_are_counted_separately():
    template = _template(
        "Example",
        parameters={
            "uid": SourceTemplateParameter(name="User ID", required=True, type="text"),
            "sort": SourceTemplateParameter(name="Sort", required=False, type="text"),
            "limit": SourceTemplateParameter(name="Limit", required=False, type="text"),
        },
    )

    assert template.required_parameters == ["User ID"]
    assert template.optional_parameter_count == 2


def test_a_template_needing_nothing_reports_no_required_parameters():
    assert _template("Example").required_parameters == []


def test_labels_are_serialized_for_the_catalog():
    """The search endpoint returns the model itself, so the UI only sees
    fields that serialize."""
    template = _template("User posts", bridge_short_name="rsshub:example/user/:uid")

    dumped = template.model_dump()

    assert dumped["provider"] == PROVIDER_RSSHUB
    assert dumped["site_domain"] == "example.com"
    assert dumped["required_parameters"] == []


# ---------- ordering ----------


def _seed_catalog():
    _template(
        "Aardvark Feed",
        bridge_short_name="rsshub:aardvark/feed",
        url="https://aardvark.example",
    ).create()
    _template("Zebra Bridge", bridge_short_name="ZebraBridge").create()
    _template("Zebra Builtin", url_template="https://zebra.example/{x}").create()


def test_browsing_leads_with_aggys_own_templates():
    """Alphabetical order alone buries six built-ins under thousands of
    imported routes."""
    _seed_catalog()

    providers = [t.provider for t in SourceTemplate.search()]

    assert providers == [PROVIDER_BUILTIN, PROVIDER_RSS_BRIDGE, PROVIDER_RSSHUB]


def test_equally_good_matches_break_toward_the_more_reliable_provider():
    _seed_catalog()

    results = SourceTemplate.search("Zebra")

    assert results[0].name == "Zebra Builtin"
    assert results[1].name == "Zebra Bridge"


def test_templates_are_searchable_by_provider():
    _seed_catalog()

    results = SourceTemplate.search("RSSHub")

    assert results[0].provider == PROVIDER_RSSHUB


def test_templates_are_searchable_by_site():
    _seed_catalog()

    results = SourceTemplate.search("aardvark.example")

    assert results[0].name == "Aardvark Feed"
