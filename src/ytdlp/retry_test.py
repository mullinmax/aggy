"""The second attempt, made as a browser, when a site refuses the first."""

import pytest
from yt_dlp.utils import DownloadError

import app


class FakeYDL:
    """Stands in for YoutubeDL, recording how it was built and what it did."""

    built = []

    def __init__(self, options):
        self.options = options
        FakeYDL.built.append(options)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def extract_info(self, url, download=False, process=True):
        error = self.options.get("_fail_with")
        if error is not None and not self.options.get("impersonate"):
            raise error
        if self.options.get("_fail_impersonated") and self.options.get("impersonate"):
            raise DownloadError("the browser attempt fell over too")
        return {"url": url, "impersonated": bool(self.options.get("impersonate"))}


@pytest.fixture(autouse=True)
def fake_ydl(monkeypatch):
    FakeYDL.built = []
    monkeypatch.setattr(app, "YoutubeDL", FakeYDL)
    monkeypatch.setattr(app, "_IMPERSONATE", "chrome-target")
    yield FakeYDL


def test_a_site_that_answers_is_never_asked_twice():
    info, impersonated = app._extract("https://example.com/v", {})
    assert impersonated is False
    assert len(FakeYDL.built) == 1


def test_a_refusal_is_retried_as_a_browser():
    """The failure that started all this: an instant 403 on the video page,
    which is the site judging the request rather than the request being wrong."""
    options = {"_fail_with": DownloadError("HTTP Error 403: Forbidden")}

    info, impersonated = app._extract("https://example.com/v", options)

    assert impersonated is True
    assert info["impersonated"] is True
    assert len(FakeYDL.built) == 2
    assert FakeYDL.built[0].get("impersonate") is None
    assert FakeYDL.built[1]["impersonate"] == "chrome-target"


def test_a_video_that_is_gone_is_not_asked_for_again():
    options = {"_fail_with": DownloadError("HTTP Error 404: Not Found")}

    with pytest.raises(DownloadError, match="404"):
        app._extract("https://example.com/v", options)

    assert len(FakeYDL.built) == 1


def test_the_first_failure_is_the_one_reported():
    """If the browser attempt fails too, the plain client's message is what
    describes the site's actual answer — the retry's is noise."""
    options = {
        "_fail_with": DownloadError("HTTP Error 403: Forbidden"),
        "_fail_impersonated": True,
    }

    with pytest.raises(DownloadError, match="403"):
        app._extract("https://example.com/v", options)

    assert len(FakeYDL.built) == 2


def test_without_the_dependency_there_is_no_retry(monkeypatch):
    """curl_cffi may be missing from a build; the plain attempt still stands
    on its own."""
    monkeypatch.setattr(app, "_IMPERSONATE", None)
    options = {"_fail_with": DownloadError("HTTP Error 403: Forbidden")}

    with pytest.raises(DownloadError):
        app._extract("https://example.com/v", options)

    assert len(FakeYDL.built) == 1
