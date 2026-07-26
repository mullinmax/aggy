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


# ---------- what a route's parameters should tell the user ----------


def test_example_values_are_read_out_of_the_routes_example(monkeypatch):
    """Without these a user has to guess what a segment wants, and a wrong
    guess is often accepted by the route and only fails when it's fetched."""
    monkeypatch.setattr(rsshub, "_base_url", lambda: "http://rsshub:1200")

    template = rsshub.route_to_template(
        "example",
        NAMESPACE,
        "/user/:uid/:language?",
        {"name": "User posts", "example": "/example/user/12345/en"},
    )

    assert template.parameters["uid"].example == "12345"
    assert template.parameters["language"].example == "en"


def test_example_values_are_url_decoded(monkeypatch):
    monkeypatch.setattr(rsshub, "_base_url", lambda: "http://rsshub:1200")

    template = rsshub.route_to_template(
        "example",
        NAMESPACE,
        "/category/:path",
        {"name": "Category", "example": "/example/category/videos%2Frecent"},
    )

    assert template.parameters["path"].example == "videos/recent"


def test_a_shorter_example_leaves_the_rest_without_one(monkeypatch):
    """Examples routinely omit optional trailing segments."""
    monkeypatch.setattr(rsshub, "_base_url", lambda: "http://rsshub:1200")

    template = rsshub.route_to_template(
        "example",
        NAMESPACE,
        "/user/:uid/:language?",
        {"name": "User posts", "example": "/example/user/12345"},
    )

    assert template.parameters["uid"].example == "12345"
    assert template.parameters["language"].example is None


def test_a_parameter_with_known_values_becomes_a_dropdown(monkeypatch):
    """So a value the route would reject can't be typed in the first place."""
    monkeypatch.setattr(rsshub, "_base_url", lambda: "http://rsshub:1200")

    template = rsshub.route_to_template(
        "example",
        NAMESPACE,
        "/user/:language",
        {
            "name": "User posts",
            "parameters": {
                "language": {
                    "description": "site language",
                    "default": "www",
                    "options": [
                        {"value": "www", "label": "English"},
                        {"value": "de", "label": "German"},
                    ],
                }
            },
        },
    )

    parameter = template.parameters["language"]
    assert parameter.type.value == "select"
    assert parameter.options == {"www": "English", "de": "German"}
    assert parameter.default == "www"


def test_options_given_as_a_mapping_are_understood(monkeypatch):
    monkeypatch.setattr(rsshub, "_base_url", lambda: "http://rsshub:1200")

    template = rsshub.route_to_template(
        "example",
        NAMESPACE,
        "/user/:sort",
        {"name": "User posts", "parameters": {"sort": {"options": {"new": "Newest"}}}},
    )

    assert template.parameters["sort"].options == {"new": "Newest"}


def test_a_plain_string_parameter_description_still_works(monkeypatch):
    monkeypatch.setattr(rsshub, "_base_url", lambda: "http://rsshub:1200")

    template = rsshub.route_to_template(
        "example",
        NAMESPACE,
        "/user/:uid",
        {"name": "User posts", "parameters": {"uid": "the user's numeric id"}},
    )

    parameter = template.parameters["uid"]
    assert parameter.title == "the user's numeric id"
    assert parameter.type.value == "text"
    assert parameter.options is None
