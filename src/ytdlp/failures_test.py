"""What a viewer is told when a site won't hand over a video."""

from failures import describe, looks_blocked, tidy


def test_the_extractor_and_the_item_id_are_stripped():
    """yt-dlp names the extractor and the site's internal id for the item.
    Neither is ours to put on someone's screen."""
    message = (
        "ERROR: [SomeSite] 6a846b2473a1f: Unable to download webpage: "
        "HTTP Error 403: Forbidden (caused by <HTTPError 403: Forbidden>)"
    )
    cleaned = tidy(message)
    assert "SomeSite" not in cleaned
    assert "6a846b2473a1f" not in cleaned
    assert "caused by" not in cleaned
    assert cleaned == "Unable to download webpage: HTTP Error 403: Forbidden"


def test_the_bug_report_boilerplate_goes_too():
    message = (
        "Unable to extract player version; please report this issue on "
        "https://github.com/yt-dlp/yt-dlp/issues , filling out the appropriate "
        "issue template. Confirm you are on the latest version"
    )
    assert tidy(message) == "Unable to extract player version;"


def test_a_refusal_says_so_without_naming_the_extractor():
    message = "[SomeSite] abc: Unable to download webpage: HTTP Error 403: Forbidden"
    described = describe(message)
    assert described == "The site refused this request (403)"
    assert "SomeSite" not in described


def test_every_message_fits_on_a_card():
    """The card shows this beside the article's title, so a paragraph would
    push the rest of the card off the screen."""
    for message in (
        "HTTP Error 403: Forbidden",
        "HTTP Error 404: Not Found",
        "HTTP Error 429: Too Many Requests",
        "Please confirm your age",
        "This video is private",
        "Please sign in",
        "not available in your country",
        "HTTP Error 500: Server Error",
        "",
    ):
        assert len(describe(message)) <= 60, message


def test_a_missing_video_is_told_apart_from_a_refusal():
    assert "no longer has this video" in describe("Video not available")
    assert "no longer has this video" in describe("HTTP Error 404: Not Found")


def test_the_cases_worth_acting_on_each_get_their_own_sentence():
    assert "rate limiting" in describe("HTTP Error 429: Too Many Requests")
    assert "age confirmation" in describe("Please confirm your age to continue")
    assert "private" in describe("This video is private")
    assert "signed-in session" in describe("Please sign in to view this video")
    assert "not serve this video" in describe(
        "The uploader has not made this video available in your country"
    )


def test_an_unrecognised_failure_still_says_something():
    assert describe("Something went sideways") == "Something went sideways"
    assert describe("") == "The site would not hand over this video"


def test_only_a_refusal_is_worth_asking_again():
    """The browser-fingerprint retry costs a second round trip, so it is for
    the failures a different-looking request could actually change."""
    assert looks_blocked("HTTP Error 403: Forbidden") is True
    assert looks_blocked("HTTP Error 429: Too Many Requests") is True
    assert looks_blocked("Just a moment... cloudflare") is True
    assert looks_blocked("HTTP Error 404: Not Found") is False
    assert looks_blocked("This video is private") is False
