from db.item import ItemLoose
from ingest.item.reddit import (
    _external_link_media,
    _post_media,
    ingest_reddit_item,
    is_reddit_post,
)
from ingest.item.rss import _link_media


def test_is_reddit_post():
    assert is_reddit_post("https://www.reddit.com/r/pics/comments/abc123/a_title/")
    assert is_reddit_post("https://old.reddit.com/r/pics/comments/abc123/a_title/")
    assert is_reddit_post("https://www.reddit.com/user/spez/comments/abc123/a_title/")
    assert not is_reddit_post("https://www.reddit.com/r/pics/")
    assert not is_reddit_post("https://example.com/r/pics/comments/abc123/")
    assert not is_reddit_post(None)


def test_post_media_gif_prefers_mp4_rendition():
    post = {
        "url_overridden_by_dest": "https://i.redd.it/example.gif",
        "preview": {
            "images": [
                {
                    "source": {"url": "https://preview.redd.it/example.jpg"},
                    "variants": {
                        "mp4": {"source": {"url": "https://preview.redd.it/example.mp4"}}
                    },
                }
            ]
        },
    }
    assert _post_media(post) == [
        {"type": "gif", "url": "https://preview.redd.it/example.mp4"}
    ]


def test_post_media_gif_without_mp4_rendition():
    post = {"url_overridden_by_dest": "https://i.redd.it/example.gif"}
    assert _post_media(post) == [
        {"type": "gif", "url": "https://i.redd.it/example.gif"}
    ]


def test_post_media_gifv_rewrites_to_mp4():
    post = {"url_overridden_by_dest": "https://i.imgur.com/example.gifv"}
    assert _post_media(post) == [
        {"type": "gif", "url": "https://i.imgur.com/example.mp4"}
    ]


def test_post_media_reddit_video():
    post = {
        "secure_media": {
            "reddit_video": {
                "fallback_url": "https://v.redd.it/example/DASH_720.mp4",
                "is_gif": False,
            }
        },
        "preview": {"images": [{"source": {"url": "https://preview.redd.it/poster.jpg"}}]},
    }
    assert _post_media(post) == [
        {
            "type": "video",
            "url": "https://v.redd.it/example/DASH_720.mp4",
            "poster": "https://preview.redd.it/poster.jpg",
        }
    ]


def test_post_media_reddit_video_gif():
    post = {
        "media": {
            "reddit_video": {
                "fallback_url": "https://v.redd.it/example/DASH_480.mp4",
                "is_gif": True,
            }
        }
    }
    assert _post_media(post) == [
        {"type": "gif", "url": "https://v.redd.it/example/DASH_480.mp4"}
    ]


def test_post_media_gallery_preserves_order():
    post = {
        "is_gallery": True,
        "gallery_data": {"items": [{"media_id": "b"}, {"media_id": "a"}]},
        "media_metadata": {
            "a": {"status": "valid", "e": "Image", "s": {"u": "https://i.redd.it/a.jpg"}},
            "b": {
                "status": "valid",
                "e": "AnimatedImage",
                "s": {"mp4": "https://i.redd.it/b.mp4", "gif": "https://i.redd.it/b.gif"},
            },
        },
    }
    assert _post_media(post) == [
        {"type": "gif", "url": "https://i.redd.it/b.mp4"},
        {"type": "image", "url": "https://i.redd.it/a.jpg"},
    ]


def test_post_media_image_post_hint():
    post = {
        "url_overridden_by_dest": "https://example.com/article",
        "post_hint": "image",
        "preview": {"images": [{"source": {"url": "https://preview.redd.it/img.jpg"}}]},
    }
    assert _post_media(post) == [
        {"type": "image", "url": "https://preview.redd.it/img.jpg"}
    ]


def test_post_media_reddit_video_preview_for_external_gif():
    """redgifs/gfycat-style link posts expose an mp4 via reddit_video_preview."""
    post = {
        "url_overridden_by_dest": "https://www.redgifs.com/watch/valhaalaand",
        "post_hint": "rich:video",
        "preview": {
            "images": [{"source": {"url": "https://preview.redd.it/img.jpg"}}],
            "reddit_video_preview": {
                "fallback_url": "https://v.redd.it/xyz/DASH_720.mp4",
                "is_gif": True,
            },
        },
    }
    assert _post_media(post) == [
        {
            "type": "gif",
            "url": "https://v.redd.it/xyz/DASH_720.mp4",
            "poster": "https://preview.redd.it/img.jpg",
        }
    ]


def test_post_media_reddit_video_preview_not_gif_is_video():
    post = {
        "url_overridden_by_dest": "https://gfycat.com/somename",
        "preview": {
            "reddit_video_preview": {
                "fallback_url": "https://v.redd.it/xyz/DASH_720.mp4",
                "is_gif": False,
            }
        },
    }
    assert _post_media(post) == [
        {"type": "video", "url": "https://v.redd.it/xyz/DASH_720.mp4"}
    ]


def test_post_media_redgifs_embed_without_rendition():
    """No mp4 rendition available: fall back to redgifs' iframe player."""
    post = {
        "url_overridden_by_dest": "https://www.redgifs.com/watch/valhaalaand",
        "post_hint": "rich:video",
        "preview": {"images": [{"source": {"url": "https://preview.redd.it/img.jpg"}}]},
    }
    assert _post_media(post) == [
        {
            "type": "embed",
            "url": "https://www.redgifs.com/ifr/valhaalaand",
            "poster": "https://preview.redd.it/img.jpg",
        }
    ]


def test_post_media_plain_link_has_no_media():
    post = {"url_overridden_by_dest": "https://example.com/article"}
    assert _post_media(post) == []


def test_external_link_media_for_link_post():
    post = {
        "url_overridden_by_dest": "https://example.com/article",
        "domain": "example.com",
        "preview": {"images": [{"source": {"url": "https://preview.redd.it/img.jpg"}}]},
    }
    assert _external_link_media(post) == [
        {
            "type": "link",
            "url": "https://example.com/article",
            "domain": "example.com",
            "poster": "https://preview.redd.it/img.jpg",
        }
    ]


def test_external_link_media_without_preview_falls_back_to_host():
    post = {"url": "https://news.ycombinator.com/item?id=1"}
    assert _external_link_media(post) == [
        {
            "type": "link",
            "url": "https://news.ycombinator.com/item?id=1",
            "domain": "news.ycombinator.com",
        }
    ]


def test_external_link_media_skips_self_post():
    post = {"is_self": True, "url": "https://www.reddit.com/r/x/comments/abc/t/"}
    assert _external_link_media(post) == []


def test_external_link_media_skips_reddit_hosted_destinations():
    # reddit CDN media and permalinks aren't off-site destinations to preview
    assert _external_link_media({"url": "https://i.redd.it/example.jpg"}) == []
    assert _external_link_media(
        {"url": "https://www.reddit.com/r/x/comments/abc/t/"}
    ) == []
    assert _external_link_media({}) == []


def test_ingest_reddit_item_skips_non_reddit_urls():
    item = ItemLoose(url="https://example.com/article")
    assert ingest_reddit_item(item) is None


def test_ingest_reddit_item_fetches_post_json(monkeypatch):
    post = {
        "title": "A gif post",
        "author": "someone",
        "url_overridden_by_dest": "https://i.redd.it/example.gif",
        "preview": {"images": [{"source": {"url": "https://preview.redd.it/img.jpg"}}]},
    }

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return [{"data": {"children": [{"data": post}]}}]

    captured = {}

    def fake_get(url, **kwargs):
        captured["url"] = url
        return FakeResponse()

    monkeypatch.setattr("ingest.item.reddit.reddit_get", fake_get)

    item = ItemLoose(url="https://www.reddit.com/r/pics/comments/abc123/a_gif_post/")
    result = ingest_reddit_item(item)

    assert captured["url"] == "https://www.reddit.com/r/pics/comments/abc123/a_gif_post.json"
    assert result.title == "A gif post"
    assert result.author == "u/someone"
    assert result.media == [{"type": "gif", "url": "https://i.redd.it/example.gif"}]
    assert result.image_url == "https://preview.redd.it/img.jpg"


def test_ingest_reddit_item_adds_link_card_for_link_post(monkeypatch):
    post = {
        "title": "An interesting article",
        "author": "someone",
        "url_overridden_by_dest": "https://example.com/article",
        "domain": "example.com",
        "preview": {"images": [{"source": {"url": "https://preview.redd.it/img.jpg"}}]},
    }

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return [{"data": {"children": [{"data": post}]}}]

    monkeypatch.setattr(
        "ingest.item.reddit.reddit_get", lambda url, **kwargs: FakeResponse()
    )

    item = ItemLoose(url="https://www.reddit.com/r/x/comments/abc123/an_article/")
    result = ingest_reddit_item(item)

    assert result.media == [
        {
            "type": "link",
            "url": "https://example.com/article",
            "domain": "example.com",
            "poster": "https://preview.redd.it/img.jpg",
        }
    ]


def test_rss_link_media():
    assert _link_media("https://example.com/funny.gif") == [
        {"type": "gif", "url": "https://example.com/funny.gif"}
    ]
    assert _link_media("https://example.com/clip.mp4") == [
        {"type": "video", "url": "https://example.com/clip.mp4"}
    ]
    assert _link_media("https://example.com/photo.jpg?width=100") == [
        {"type": "image", "url": "https://example.com/photo.jpg?width=100"}
    ]
    assert _link_media("https://example.com/article") is None
    assert _link_media(None) is None
