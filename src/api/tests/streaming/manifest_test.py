"""Pointing an HLS playlist's contents back through this server."""

from streaming import manifest

BASE = "https://cdn.example.com/hls/720/index.m3u8?sig=abc"


def _proxied(url):
    return f"/item/stream?ticket={url}"


def test_a_relative_segment_is_resolved_before_it_is_rewritten():
    """The browser would have resolved it against the playlist's address;
    once the playlist is served from here, only we still know what that was."""
    body = "#EXTINF:6.0,\nseg1.ts\n"

    rewritten = manifest.rewrite(body, BASE, _proxied)

    assert "/item/stream?ticket=https://cdn.example.com/hls/720/seg1.ts" in rewritten


def test_an_absolute_segment_is_kept_whole():
    body = "https://other.example.com/a/seg1.ts\n"

    assert manifest.rewrite(body, BASE, _proxied) == (
        "/item/stream?ticket=https://other.example.com/a/seg1.ts\n"
    )


def test_a_url_inside_a_tag_is_rewritten_too():
    """The decryption key and the initialisation segment are named in
    attributes rather than on lines of their own, and a stream is just as
    unplayable without them."""
    body = (
        '#EXT-X-KEY:METHOD=AES-128,URI="key.bin",IV=0x1\n'
        '#EXT-X-MAP:URI="https://cdn.example.com/init.mp4"\n'
    )

    rewritten = manifest.rewrite(body, BASE, _proxied)

    assert 'URI="/item/stream?ticket=https://cdn.example.com/hls/720/key.bin"' in (
        rewritten
    )
    assert 'URI="/item/stream?ticket=https://cdn.example.com/init.mp4"' in rewritten
    assert "METHOD=AES-128" in rewritten and "IV=0x1" in rewritten


def test_everything_that_is_not_a_url_is_left_alone():
    body = "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:6\n\n#EXT-X-ENDLIST\n"

    assert manifest.rewrite(body, BASE, _proxied) == body


def test_a_playlist_is_told_apart_from_a_media_file():
    assert manifest.looks_like_manifest(BASE, "") is True
    assert (
        manifest.looks_like_manifest(
            "https://cdn.example.com/x", "application/vnd.apple.mpegurl; charset=utf-8"
        )
        is True
    )
    # some CDNs serve playlists as plain text, which the extension still gives away
    assert manifest.looks_like_manifest("https://x/y.m3u8", "text/plain") is True
    assert manifest.looks_like_manifest("https://x/y.mp4", "video/mp4") is False
    assert manifest.looks_like_manifest("https://x/seg.ts", "") is False
