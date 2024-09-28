import pytest
from db.feed_template import (
    FeedTemplate,
    FeedTemplateParameter,
    FeedTemplateParameterType,
)


def test_create_feed_template(unique_feed_template):
    assert unique_feed_template.exists() is False
    unique_feed_template.create()
    assert unique_feed_template.exists() is True


def test_read_feed_template(existing_feed_template):
    read_feed_template = FeedTemplate.read(name_hash=existing_feed_template.name_hash)
    assert read_feed_template, "FeedTemplate should be readable"
    assert (
        read_feed_template.name == existing_feed_template.name
    ), "FeedTemplate name should match"
    assert (
        read_feed_template.url == existing_feed_template.url
    ), "FeedTemplate url should match"


def test_list_all_templates(existing_feed_template):
    feed_templates = FeedTemplate.read_all()
    assert existing_feed_template.name_hash in [t.name_hash for t in feed_templates]


@pytest.mark.parametrize(
    "parameters, expected_issues",
    [
        ({}, ["Parameter parameter_name is required"]),
        (
            {"parameter_name": "invalid_value"},
            ["Parameter parameter_name must be one of ['value', 'other_value']"],
        ),
        (
            {"invalid_parameter": "value"},
            [
                "Parameter parameter_name is required",
                "Parameter invalid_parameter is not defined in the template",
            ],
        ),
    ],
)
def test_validate_unhappy_parameters(
    parameters, expected_issues, existing_feed_template
):
    with pytest.raises(Exception) as e:
        existing_feed_template.validate_parameters(**parameters)
    assert str(e.value) == f"Validation issues: {', '.join(expected_issues)}"


def test_create_rss_url(existing_feed_template):
    parameters = {"parameter_name": "value"}
    rss_url = existing_feed_template.create_rss_url(**parameters)

    assert (
        rss_url
        == "http://dev-aggy-rss-bridge:80/?action=display&bridge=test&format=Atom&context=by+user&parameter_name=value"
    )


def test_validate_none_parameters(unique_feed_template):
    unique_feed_template.parameters = {}
    unique_feed_template.validate_parameters()


def test_validate_missing_required_parameters(unique_feed_template):
    unique_feed_template.parameters = {
        "parameter_name": FeedTemplateParameter(
            name="parameter_name", required=True, type=FeedTemplateParameterType.text
        )
    }
    with pytest.raises(Exception) as e:
        unique_feed_template.validate_parameters()
    assert str(e.value) == "Validation issues: Parameter parameter_name is required"


def test_validate_invalid_selection_parameters(unique_feed_template):
    unique_feed_template.parameters = {
        "parameter_name": FeedTemplateParameter(
            name="parameter_name",
            required=True,
            type=FeedTemplateParameterType.select,
            options={"value": "Value", "other_value": "Other Value"},
        )
    }
    with pytest.raises(Exception) as e:
        unique_feed_template.validate_parameters(parameter_name="invalid_value")
    assert (
        str(e.value)
        == "Validation issues: Parameter parameter_name must be one of ['value', 'other_value']"
    )


def test_create_rss_url_use_default_parameters(unique_feed_template):
    unique_feed_template.parameters = {
        "parameter_name": FeedTemplateParameter(
            name="parameter_name",
            required=False,
            default="default_value",
            type=FeedTemplateParameterType.text,
        )
    }
    rss_url = unique_feed_template.create_rss_url()
    assert (
        rss_url
        == "http://dev-aggy-rss-bridge:80/?action=display&bridge=test&format=Atom&context=by+user&parameter_name=default_value"
    )


def test_get_non_existent_template():
    assert FeedTemplate.read(name_hash="non_existent_template") is None
