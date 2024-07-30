from db.feed_template import FeedTemplate


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


def test_create_rss_url(existing_feed_template):
    parameters = {"param_name": "value"}
    rss_url = existing_feed_template.create_rss_url(**parameters)

    # TODO This will have to change when we use url encoding correctly
    assert (
        rss_url
        == "http://dev-blinder-rss-bridge:80/?action=display&bridge=test&context=by user&parameter_name=default_value&format=Atom"
    )
