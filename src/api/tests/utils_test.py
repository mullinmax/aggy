"""Unit tests for small helpers in utils."""

import pytest

from utils import is_playable_media_url


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.youtube.com/watch?v=abc123", True),
        ("https://youtu.be/abc123", True),
        ("http://m.youtube.com/watch?v=abc123", True),
        ("https://www.youtube-nocookie.com/embed/abc123", True),
        ("https://example.com/clip.mp4", True),
        ("https://example.com/clip.webm?t=10", True),
        ("https://example.com/article", False),
        ("https://vimeo.com/12345", False),  # not rendered inline by the UI
        ("https://notyoutube.com.evil.example/x", False),
        (None, False),
        ("", False),
    ],
)
def test_is_playable_media_url(url, expected):
    assert is_playable_media_url(url) is expected
