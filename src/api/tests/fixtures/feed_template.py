import pytest
import uuid

from db.feed_template import FeedTemplate, FeedTemplateParameter


@pytest.fixture(scope="function")
def unique_feed_template() -> FeedTemplate:
    """Generates unique feed template data for each test"""
    feed_template = FeedTemplate(
        name=f"Feed Template Name {uuid.uuid4()}",
        bridge_short_name="test",
        context="test",
        parameters={
            "test": FeedTemplateParameter(
                name="param_name",
                required=True,
                default="default value",
                example="example value",
                title="title",
                options={"A": "a", "B": "b", "C": "c"},
            )
        },
    )

    yield feed_template

    if feed_template.exists():
        feed_template.delete()


@pytest.fixture(scope="function")
def existing_feed_template(unique_feed_template: FeedTemplate) -> FeedTemplate:
    """Generates existing feed template data for each test"""
    unique_feed_template.create()
    yield unique_feed_template
