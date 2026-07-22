"""Pure-python tests for feature loading (no database)."""

from ranking.engine import _row_to_features


def _row(**overrides):
    row = {
        "url_hash": "h",
        "url": "https://example.com/article",
        "author": None,
        "date_published": None,
        "image_url": None,
        "media": None,
        "embeddings": None,
        "image_embeddings": None,
        "vote": None,
        "vote_date": None,
        "source_name": "src",
        "list_added_at": None,
    }
    row.update(overrides)
    return row


def test_has_media_from_stored_media_entry():
    feat = _row_to_features(_row(media=[{"type": "video", "url": "x"}]))
    assert feat.has_media is True


def test_has_media_true_for_youtube_without_stored_media():
    # YouTube plays inline in the UI from the URL alone, with no media entry
    feat = _row_to_features(_row(url="https://youtu.be/abc123", media=None))
    assert feat.has_media is True


def test_has_media_true_for_direct_video_file():
    feat = _row_to_features(_row(url="https://cdn.example.com/v.mp4", media=None))
    assert feat.has_media is True


def test_has_media_false_for_plain_article():
    feat = _row_to_features(_row(url="https://example.com/story", media=None))
    assert feat.has_media is False
