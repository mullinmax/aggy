"""Unit tests for the rendition picker. No network, no yt-dlp: every case is
an info dict of the shape an extractor returns."""

from formats import best_format, is_m3u8, playable_url


def _fmt(**overrides):
    fmt = {
        "url": "https://cdn.example.com/video.mp4",
        "protocol": "https",
        "vcodec": "avc1",
        "acodec": "mp4a",
        "height": 720,
    }
    fmt.update(overrides)
    return fmt


def test_progressive_beats_hls():
    """A plain file plays with no player support at all, so it wins even when
    the adaptive stream offers a taller rendition."""
    info = {
        "formats": [
            _fmt(
                url="https://cdn.example.com/x.m3u8",
                protocol="m3u8_native",
                height=1080,
            ),
            _fmt(height=480),
        ]
    }
    resolved = playable_url(info)
    assert resolved["url"] == "https://cdn.example.com/video.mp4"
    assert resolved["is_hls"] is False


def test_unstated_codecs_are_not_treated_as_missing():
    """Plenty of extractors report no codec information whatsoever. Reading
    that as "no audio and no video" left those sites with nothing playable."""
    info = {"formats": [_fmt(vcodec=None, acodec=None)]}
    assert playable_url(info)["url"] == "https://cdn.example.com/video.mp4"


def test_stated_codecs_beat_a_taller_unknown():
    """A rendition that says it carries picture and sound is worth more than a
    bigger one that might turn out to be silent."""
    info = {
        "formats": [
            _fmt(
                url="https://cdn.example.com/tall.mp4",
                vcodec=None,
                acodec=None,
                height=2160,
            ),
            _fmt(url="https://cdn.example.com/known.mp4", height=720),
        ]
    }
    assert playable_url(info)["url"] == "https://cdn.example.com/known.mp4"


def test_hls_only_site_is_offered_and_flagged():
    info = {
        "formats": [
            _fmt(
                url="https://cdn.example.com/master.m3u8?sig=abc",
                protocol="m3u8_native",
            )
        ]
    }
    resolved = playable_url(info)
    assert resolved["is_hls"] is True
    assert resolved["protocol"] == "m3u8_native"


def test_split_renditions_are_skipped():
    """Video-only and audio-only formats would need muxing, which the browser
    cannot do."""
    info = {
        "formats": [
            _fmt(acodec="none"),
            _fmt(url="https://cdn.example.com/audio.m4a", vcodec="none"),
        ]
    }
    assert playable_url(info) is None


def test_single_stream_info_without_formats():
    """Some extractors describe the whole item as one stream and list no
    formats at all."""
    info = {"url": "https://cdn.example.com/single.mp4", "protocol": "https"}
    assert playable_url(info)["url"] == "https://cdn.example.com/single.mp4"


def test_nothing_playable():
    assert playable_url({"formats": []}) is None
    assert playable_url({}) is None


def test_m3u8_detected_past_a_signature():
    assert is_m3u8("https://cdn.example.com/a/master.m3u8?token=1&exp=2") is True
    assert is_m3u8("https://cdn.example.com/a/video.mp4?list=x.m3u8") is False


def test_best_format_prefers_bitrate_when_heights_match():
    chosen = best_format(
        [_fmt(tbr=500), _fmt(url="https://cdn.example.com/hi.mp4", tbr=2500)]
    )
    assert chosen["url"] == "https://cdn.example.com/hi.mp4"
