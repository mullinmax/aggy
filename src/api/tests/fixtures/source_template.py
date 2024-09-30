import pytest
import uuid

from db.source_template import (
    SourceTemplate,
    SourceTemplateParameter,
    SourceTemplateParameterType,
)


@pytest.fixture(scope="function")
def unique_source_template() -> SourceTemplate:
    """Generates unique source template data for each test"""

    parameter = SourceTemplateParameter(
        name="Parameter Name",
        required=True,
        type=SourceTemplateParameterType.text,
        default="value",
        example="example_value",
        title="title",
        options={"value": "Human Readable Value", "other_value": "Other Value"},
    )

    source_template = SourceTemplate(
        name=f"Source Template Name {uuid.uuid4()}",
        bridge_short_name="test",
        url="http://example.com",
        description="Description",
        context="by user",
        parameters={"parameter_name": parameter},
    )

    yield source_template

    if source_template.exists():
        source_template.delete()


@pytest.fixture(scope="function")
def existing_source_template(unique_source_template: SourceTemplate) -> SourceTemplate:
    """Generates existing source template data for each test"""
    unique_source_template.create()
    yield unique_source_template
