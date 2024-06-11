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


def test_create_feed_from_template(existing_feed_template, existing_category):
    feed_url = existing_feed_template.create_rss_url()
    feed = existing_feed_template.create_feed(
        user_hash=existing_feed_template.user_hash,
        category_hash=existing_category.name_hash,
        feed_name="Test Feed",
    )
    assert feed.url == feed_url
    assert feed.exists() is True
    feed.delete()
    assert feed.exists() is False
