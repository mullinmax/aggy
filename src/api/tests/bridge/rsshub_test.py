from bridge import rsshub


NAMESPACE = {
    "name": "Example Site",
    "url": "example.com",
    "description": "An example namespace",
}


def _template(path, route=None, monkeypatch=None):
    return rsshub.route_to_template(
        "example", NAMESPACE, path, route or {"name": "User posts"}
    )


def test_route_parameters_become_template_parameters(monkeypatch):
    monkeypatch.setattr(rsshub, "_base_url", lambda: "http://rsshub:1200")

    template = _template("/user/:uid")

    assert set(template.parameters) == {"uid"}
    assert template.parameters["uid"].required is True
    assert template.url_template == "http://rsshub:1200/example/user/{uid}"


def test_optional_route_parameters_are_not_required(monkeypatch):
    monkeypatch.setattr(rsshub, "_base_url", lambda: "http://rsshub:1200")

    template = _template("/user/:uid/:category?")

    assert template.parameters["uid"].required is True
    assert template.parameters["category"].required is False


def test_parameter_descriptions_are_carried_over(monkeypatch):
    monkeypatch.setattr(rsshub, "_base_url", lambda: "http://rsshub:1200")

    template = rsshub.route_to_template(
        "example",
        NAMESPACE,
        "/user/:uid",
        {"name": "User posts", "parameters": {"uid": "the user's numeric id"}},
    )

    assert template.parameters["uid"].title == "the user's numeric id"


def test_object_shaped_parameter_descriptions_are_understood(monkeypatch):
    monkeypatch.setattr(rsshub, "_base_url", lambda: "http://rsshub:1200")

    template = rsshub.route_to_template(
        "example",
        NAMESPACE,
        "/user/:uid",
        {"name": "User posts", "parameters": {"uid": {"description": "numeric id"}}},
    )

    assert template.parameters["uid"].title == "numeric id"


def test_the_namespace_becomes_the_template_context(monkeypatch):
    """So the catalog reads "User posts (Example Site)", like rss-bridge's."""
    monkeypatch.setattr(rsshub, "_base_url", lambda: "http://rsshub:1200")

    template = _template("/user/:uid")

    assert template.user_friendly_name == "User posts (Example Site)"


def test_imported_templates_are_marked_so_they_can_be_cleaned_up(monkeypatch):
    monkeypatch.setattr(rsshub, "_base_url", lambda: "http://rsshub:1200")

    template = _template("/user/:uid")

    assert template.bridge_short_name == "rsshub:example/user/:uid"


def test_wildcard_routes_are_skipped(monkeypatch):
    """Their free-form remainder has no sensible parameter form."""
    monkeypatch.setattr(rsshub, "_base_url", lambda: "http://rsshub:1200")

    assert _template("/user/*") is None


def test_routes_with_too_many_parameters_are_skipped(monkeypatch):
    monkeypatch.setattr(rsshub, "_base_url", lambda: "http://rsshub:1200")

    assert _template("/a/:b/:c/:d/:e/:f/:g") is None


def test_the_catalog_job_is_a_no_op_without_the_service(monkeypatch):
    monkeypatch.setattr(rsshub, "is_configured", lambda: False)
    dropped = []
    monkeypatch.setattr(
        rsshub, "_drop_imported_templates", lambda: dropped.append(True)
    )

    rsshub.rsshub_get_templates_job()

    # the routes go away with the service rather than lingering as templates
    # that could never be fetched
    assert dropped == [True]


def test_a_non_json_catalog_is_survivable(monkeypatch):
    """Instances that don't serve the catalog answer with HTML; the generic
    route template still works, so this must not raise."""
    monkeypatch.setattr(rsshub, "is_configured", lambda: True)
    monkeypatch.setattr(rsshub, "_base_url", lambda: "http://rsshub:1200")

    class _HtmlResponse:
        def raise_for_status(self):
            pass

        def json(self):
            raise ValueError("not json")

    monkeypatch.setattr(rsshub.requests, "get", lambda *a, **kw: _HtmlResponse())

    rsshub.rsshub_get_templates_job()
