import pytest
from db.source_template import (
    SourceTemplate,
    SourceTemplateParameter,
    SourceTemplateParameterType,
)

from config import config


def test_create_source_template(unique_source_template):
    assert unique_source_template.exists() is False
    unique_source_template.create()
    assert unique_source_template.exists() is True


def test_read_source_template(existing_source_template):
    read_source_template = SourceTemplate.read(
        name_hash=existing_source_template.name_hash
    )
    assert read_source_template, "SourceTemplate should be readable"
    assert (
        read_source_template.name == existing_source_template.name
    ), "SourceTemplate name should match"
    assert (
        read_source_template.url == existing_source_template.url
    ), "SourceTemplate url should match"


def test_list_all_templates(existing_source_template):
    source_templates = SourceTemplate.read_all()
    assert existing_source_template.name_hash in [t.name_hash for t in source_templates]


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
    parameters, expected_issues, existing_source_template
):
    with pytest.raises(Exception) as e:
        existing_source_template.validate_parameters(**parameters)
    assert str(e.value) == f"Validation issues: {', '.join(expected_issues)}"


def test_create_rss_url(existing_source_template):
    parameters = {"parameter_name": "value"}
    rss_url = existing_source_template.create_rss_url(**parameters)

    assert (
        rss_url
        == f"http://{config.get('RSS_BRIDGE_HOST')}:80/?action=display&bridge=test&format=Atom&context=by+user&parameter_name=value"
    )


def test_validate_none_parameters(unique_source_template):
    unique_source_template.parameters = {}
    unique_source_template.validate_parameters()


def test_validate_missing_required_parameters(unique_source_template):
    unique_source_template.parameters = {
        "parameter_name": SourceTemplateParameter(
            name="parameter_name", required=True, type=SourceTemplateParameterType.text
        )
    }
    with pytest.raises(Exception) as e:
        unique_source_template.validate_parameters()
    assert str(e.value) == "Validation issues: Parameter parameter_name is required"


def test_validate_invalid_selection_parameters(unique_source_template):
    unique_source_template.parameters = {
        "parameter_name": SourceTemplateParameter(
            name="parameter_name",
            required=True,
            type=SourceTemplateParameterType.select,
            options={"value": "Value", "other_value": "Other Value"},
        )
    }
    with pytest.raises(Exception) as e:
        unique_source_template.validate_parameters(parameter_name="invalid_value")
    assert (
        str(e.value)
        == "Validation issues: Parameter parameter_name must be one of ['value', 'other_value']"
    )


def test_create_rss_url_use_default_parameters(unique_source_template):
    unique_source_template.parameters = {
        "parameter_name": SourceTemplateParameter(
            name="parameter_name",
            required=False,
            default="default_value",
            type=SourceTemplateParameterType.text,
        )
    }
    rss_url = unique_source_template.create_rss_url()
    assert (
        rss_url
        == f"http://{config.get('RSS_BRIDGE_HOST')}:80/?action=display&bridge=test&format=Atom&context=by+user&parameter_name=default_value"
    )


def test_get_non_existent_template():
    assert SourceTemplate.read(name_hash="non_existent_template") is None
