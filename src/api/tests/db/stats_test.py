import pytest

from config import config
from db.base import get_db_con
from db.item import ItemLoose
from db.item_state import ItemState
from db.stats import article_stats, base_domain, domain_stats


@pytest.mark.parametrize(
    "host,expected",
    [
        ("reddit.com", "reddit.com"),
        ("www.reddit.com", "reddit.com"),
        ("old.reddit.com", "reddit.com"),
        ("i.redd.it", "redd.it"),
        ("news.bbc.co.uk", "bbc.co.uk"),
        ("bbc.co.uk", "bbc.co.uk"),
        ("someone.github.io", "someone.github.io"),
        ("a.b.c.example.com", "example.com"),
        ("EXAMPLE.COM", "example.com"),
        ("example.com.", "example.com"),
        ("localhost", "localhost"),
        ("127.0.0.1", "127.0.0.1"),
        ("", "unknown"),
        (None, "unknown"),
    ],
)
def test_base_domain(host, expected):
    assert base_domain(host) == expected


def add_item(feed, url, **overrides):
    fields = {
        "url": url,
        "title": "Title",
        "domain": "example.com",
        "excerpt": "Excerpt",
        "content": "<p>Article body</p>",
        "author": "Author",
    }
    fields.update(overrides)
    item = ItemLoose(**fields)
    item.create(overwrite=True)
    feed.add_items(item)
    return item


def test_domain_stats_groups_hosts_by_base_domain(existing_user, existing_feed):
    add_item(existing_feed, "https://www.reddit.com/r/a/post1")
    add_item(existing_feed, "https://old.reddit.com/r/a/post2")
    add_item(existing_feed, "https://example.com/a")

    rows = domain_stats(existing_user.name_hash)

    assert [row["domain"] for row in rows] == ["reddit.com", "example.com"]
    assert rows[0]["article_count"] == 2
    assert rows[1]["article_count"] == 1


def test_domain_stats_counts_coverage(existing_user, existing_feed):
    add_item(
        existing_feed,
        "https://example.com/full",
        image_url="https://example.com/a.jpg",
        embeddings={"text-model": [0.1, 0.2]},
        image_embeddings={"clip": [0.3, 0.4]},
        media=[{"type": "video", "url": "https://example.com/v.mp4"}],
        date_published="2024-01-01T00:00:00Z",
    )
    add_item(
        existing_feed,
        "https://example.com/bare",
        content="no image here",
        author=None,
        excerpt=None,
    )

    row = domain_stats(existing_user.name_hash)[0]

    assert row["article_count"] == 2
    assert row["with_preview_image"] == 1
    assert row["with_image_embedding"] == 1
    assert row["with_text_embedding"] == 1
    assert row["with_media"] == 1
    assert row["with_date_published"] == 1
    assert row["with_author"] == 1
    assert row["with_excerpt"] == 1
    assert row["with_content"] == 2


def test_domain_stats_counts_given_up_image_embeddings(existing_user, existing_feed):
    """The image-embedding gap splits into pictures still queued and pictures
    the embedder has given up on — only the first closes by waiting, so the page
    has to be able to tell them apart."""
    max_attempts = config.get_int("IMAGE_EMBED_MAX_ATTEMPTS")

    queued = add_item(
        existing_feed, "https://example.com/queued", image_url="https://e.com/a.jpg"
    )
    exhausted = add_item(
        existing_feed, "https://example.com/exhausted", image_url="https://e.com/b.jpg"
    )
    # an item can burn its attempts and still end up embedded later (a re-scrape
    # finds a working URL); that is covered, not failed
    embedded = add_item(
        existing_feed,
        "https://example.com/embedded",
        image_url="https://e.com/c.jpg",
        image_embeddings={"clip": [0.1]},
    )

    with get_db_con() as cur:
        cur.execute(
            "UPDATE items SET image_embed_attempts = %s WHERE url_hash IN (%s, %s)",
            (max_attempts, exhausted.url_hash, embedded.url_hash),
        )

    row = domain_stats(existing_user.name_hash)[0]

    assert row["with_preview_image"] == 3
    assert row["with_image_embedding"] == 1
    assert row["image_embed_failed"] == 1
    assert queued.url_hash  # the third article is simply still in the queue


def test_preview_image_falls_back_to_content_image(existing_user, existing_feed):
    add_item(
        existing_feed,
        "https://example.com/inline",
        content='<p>hi</p><img src="https://example.com/a.jpg">',
    )

    assert domain_stats(existing_user.name_hash)[0]["with_preview_image"] == 1


def test_domain_stats_counts_votes(existing_user, existing_feed):
    up = add_item(existing_feed, "https://example.com/up")
    down = add_item(existing_feed, "https://example.com/down")
    add_item(existing_feed, "https://example.com/unvoted")

    for item, score in ((up, 1), (down, -1)):
        ItemState.set_state(
            user_hash=existing_user.name_hash,
            feed_hash=existing_feed.name_hash,
            item_url_hash=item.url_hash,
            score=score,
        )

    row = domain_stats(existing_user.name_hash)[0]

    assert row["up_votes"] == 1
    assert row["down_votes"] == 1
    assert row["neutral_votes"] == 0


def test_article_counted_once_across_feeds(existing_user, existing_feed):
    from db.feed import Feed

    other = Feed(user_hash=existing_user.name_hash, name="Another feed")
    other.create()

    item = add_item(existing_feed, "https://example.com/shared")
    other.add_items(item)

    rows = domain_stats(existing_user.name_hash)

    assert len(rows) == 1
    assert rows[0]["article_count"] == 1


def test_stats_are_scoped_to_the_user(existing_user, existing_feed):
    from db.user import User

    add_item(existing_feed, "https://example.com/mine")

    other_user = User(name="somebody_else")
    other_user.set_password("password")
    other_user.create()

    assert domain_stats(other_user.name_hash) == []
    assert len(domain_stats(existing_user.name_hash)) == 1


def test_article_stats_summary_and_timeline(existing_user, existing_feed):
    add_item(
        existing_feed,
        "https://example.com/a",
        image_url="https://example.com/a.jpg",
        embeddings={"text-model": [0.1]},
    )
    add_item(existing_feed, "https://news.bbc.co.uk/b", content="plain text")

    stats = article_stats(existing_user.name_hash, timeline_days=7)

    assert stats["summary"]["total_articles"] == 2
    assert stats["summary"]["domain_count"] == 2
    assert stats["summary"]["with_preview_image"] == 1
    assert stats["summary"]["with_text_embedding"] == 1
    assert stats["summary"]["avg_content_chars"] is not None

    # one point per day, inclusive of both ends, with today carrying the items
    assert len(stats["timeline"]) == 8
    assert stats["timeline"][-1]["article_count"] == 2
    assert sum(point["article_count"] for point in stats["timeline"]) == 2


def test_article_stats_with_no_articles(existing_user):
    stats = article_stats(existing_user.name_hash, timeline_days=3)

    assert stats["domains"] == []
    assert stats["summary"]["total_articles"] == 0
    assert stats["summary"]["avg_content_chars"] is None
    assert [point["article_count"] for point in stats["timeline"]] == [0, 0, 0, 0]


# ---------- duplicate counts ----------


def test_duplicate_counts_are_scoped_to_what_the_user_holds(
    existing_user, existing_feed
):
    """Detection is global, so a group routinely has members in other people's
    feeds. Only the copies this user actually has may count, or the page reports
    duplicates they cannot see."""
    from db.feed import Feed
    from db.user import User
    from dedup.detect import duplicate_detection_job

    add_item(existing_feed, "https://example.com/story?utm_source=mine")

    # the second copy of the same story belongs to somebody else entirely
    other = User(name="somebody-else")
    other.set_password("password")
    other.create()
    other_feed = Feed(user_hash=other.name_hash, name="Theirs")
    other_feed.create()
    add_item(other_feed, "https://example.com/story?utm_source=theirs")

    duplicate_detection_job()
    summary = article_stats(existing_user.name_hash)["summary"]

    # the two copies are one group, but only one of them is in this user's feed
    assert summary["total_articles"] == 1
    assert summary["in_duplicate_group"] == 0
    assert summary["duplicate_groups"] == 0
    assert summary["redundant_articles"] == 0


def test_duplicate_counts_report_groups_and_redundancy(existing_user, existing_feed):
    from dedup.detect import duplicate_detection_job

    # one story collected three times over, one twice, and two singletons
    for i in range(3):
        add_item(existing_feed, f"https://example.com/big?utm_source=s{i}")
    for i in range(2):
        add_item(existing_feed, f"https://example.com/pair?utm_source=s{i}")
    add_item(existing_feed, "https://example.com/alone")
    add_item(existing_feed, "https://other.com/alone")

    duplicate_detection_job()
    summary = article_stats(existing_user.name_hash)["summary"]

    assert summary["total_articles"] == 7
    assert summary["duplicate_groups"] == 2
    # every copy of a duplicated story...
    assert summary["duplicated_articles"] == 5
    assert summary["in_duplicate_group"] == 5
    # ...minus the one the feed keeps showing for each
    assert summary["redundant_articles"] == 3
    assert summary["largest_duplicate_group"] == 3
    assert summary["with_1_similar_link"] == 2
    assert summary["with_2_similar_links"] == 3
    assert summary["with_3_similar_links"] == 0
    assert summary["with_4_similar_links"] == 0
    assert summary["with_5_similar_links"] == 0


def test_duplicate_counts_bucket_articles_by_similar_link_count(
    existing_user, existing_feed
):
    from dedup.detect import duplicate_detection_job

    for similar_links in range(1, 6):
        for copy in range(similar_links + 1):
            add_item(
                existing_feed,
                f"https://example.com/group-{similar_links}?utm_source=s{copy}",
            )

    duplicate_detection_job()
    summary = article_stats(existing_user.name_hash)["summary"]

    assert summary["with_1_similar_link"] == 2
    assert summary["with_2_similar_links"] == 3
    assert summary["with_3_similar_links"] == 4
    assert summary["with_4_similar_links"] == 5
    assert summary["with_5_similar_links"] == 6


def test_duplicate_counts_appear_per_domain(existing_user, existing_feed):
    """The per-article count folds up by domain like every other count."""
    from dedup.detect import duplicate_detection_job

    for i in range(2):
        add_item(existing_feed, f"https://dupes.com/story?utm_source=s{i}")
    add_item(existing_feed, "https://dupes.com/unique")
    add_item(existing_feed, "https://clean.com/unique")

    duplicate_detection_job()
    rows = {row["domain"]: row for row in domain_stats(existing_user.name_hash)}

    assert rows["dupes.com"]["article_count"] == 3
    assert rows["dupes.com"]["in_duplicate_group"] == 2
    assert rows["clean.com"]["in_duplicate_group"] == 0


def test_a_group_spanning_hosts_counts_under_each(existing_user, existing_feed):
    """Copies are grouped by canonical URL, so they can arrive under different
    hosts. That is exactly why the group-level numbers are summary-only: this
    group belongs to no single base domain."""
    from dedup.detect import duplicate_detection_job

    add_item(existing_feed, "https://publisher.com/piece")
    add_item(
        existing_feed,
        "https://news.google.com/articles/x?url=https%3A%2F%2Fpublisher.com%2Fpiece",
    )

    duplicate_detection_job()
    stats = article_stats(existing_user.name_hash)
    rows = {row["domain"]: row for row in stats["domains"]}

    assert rows["publisher.com"]["in_duplicate_group"] == 1
    assert rows["google.com"]["in_duplicate_group"] == 1
    # one group, not one per domain
    assert stats["summary"]["duplicate_groups"] == 1
    assert stats["summary"]["redundant_articles"] == 1


def test_duplicate_counts_are_zero_before_detection_runs(existing_user, existing_feed):
    """Detection is a background pass, so an article it has not reached yet is
    simply not in a group. That must read as zero rather than breaking the page."""
    for i in range(2):
        add_item(existing_feed, f"https://example.com/story?utm_source=s{i}")

    summary = article_stats(existing_user.name_hash)["summary"]

    assert summary["total_articles"] == 2
    assert summary["in_duplicate_group"] == 0
    assert summary["duplicate_groups"] == 0
    assert summary["largest_duplicate_group"] == 0
