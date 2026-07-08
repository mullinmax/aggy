from ingest.reddit_rate_limit import (
    RedditRateLimiter,
    _parse_retry_after,
    is_reddit_url,
    reddit_get,
)


def test_is_reddit_url():
    assert is_reddit_url("https://www.reddit.com/r/pics/top.rss?t=day")
    assert is_reddit_url("https://old.reddit.com/user/spez/.rss")
    assert is_reddit_url("https://reddit.com/r/pics.json")
    assert not is_reddit_url("https://example.com/reddit.com/r/pics")
    assert not is_reddit_url("https://notreddit.com/r/pics")
    assert not is_reddit_url("https://reddit.com.evil.example/r/pics")
    assert not is_reddit_url(None)


def test_acquire_spaces_requests(monkeypatch):
    limiter = RedditRateLimiter(min_interval=1, max_interval=10, initial_interval=3)

    clock = {"t": 100.0}
    sleeps = []
    monkeypatch.setattr("ingest.reddit_rate_limit.time.monotonic", lambda: clock["t"])

    def fake_sleep(seconds):
        sleeps.append(seconds)
        clock["t"] += seconds

    monkeypatch.setattr("ingest.reddit_rate_limit.time.sleep", fake_sleep)

    # first call fires immediately (next_allowed starts at 0)
    limiter.acquire()
    assert sleeps == []
    # the next call must wait a full interval behind the first
    limiter.acquire()
    assert sleeps == [3]


def test_record_rate_limited_backs_off_exponentially():
    limiter = RedditRateLimiter(min_interval=1, max_interval=100, initial_interval=4)
    limiter.record_rate_limited()
    assert limiter.interval == 8
    limiter.record_rate_limited()
    assert limiter.interval == 16


def test_record_rate_limited_respects_ceiling():
    limiter = RedditRateLimiter(min_interval=1, max_interval=10, initial_interval=8)
    limiter.record_rate_limited()
    assert limiter.interval == 10


def test_record_rate_limited_honors_retry_after(monkeypatch):
    limiter = RedditRateLimiter(min_interval=1, max_interval=1000, initial_interval=4)
    monkeypatch.setattr("ingest.reddit_rate_limit.time.monotonic", lambda: 0.0)
    limiter.record_rate_limited(retry_after=120)
    # the next request must be pushed out by the retry-after, not just the delay
    assert limiter._next_allowed == 120


def test_record_success_recovers_cautiously():
    # a big initial delay means a low rate; success nudges the rate up a little,
    # which only shaves a little off the delay (very cautious recovery)
    limiter = RedditRateLimiter(min_interval=1, max_interval=100, initial_interval=10)
    before = limiter.interval
    limiter.record_success()
    assert limiter.interval < before
    # one success shouldn't come anywhere near collapsing to the floor
    assert limiter.interval > 5


def test_record_success_never_below_floor():
    limiter = RedditRateLimiter(min_interval=2, max_interval=100, initial_interval=2)
    for _ in range(1000):
        limiter.record_success()
    assert limiter.interval >= 2


def test_parse_retry_after():
    class R:
        def __init__(self, headers):
            self.headers = headers

    assert _parse_retry_after(R({"Retry-After": "30"})) == 30
    assert _parse_retry_after(R({})) is None
    assert _parse_retry_after(R({"Retry-After": "not-a-number"})) is None


def test_reddit_get_records_success(monkeypatch):
    limiter = RedditRateLimiter(min_interval=1, max_interval=100, initial_interval=10)
    monkeypatch.setattr("ingest.reddit_rate_limit.get_limiter", lambda: limiter)

    class FakeResponse:
        status_code = 200
        ok = True

    monkeypatch.setattr(
        "ingest.reddit_rate_limit.requests.get", lambda url, **kw: FakeResponse()
    )
    monkeypatch.setattr("ingest.reddit_rate_limit.time.sleep", lambda s: None)

    before = limiter.interval
    reddit_get("https://www.reddit.com/r/pics/top.rss")
    assert limiter.interval < before


def test_reddit_get_records_rate_limit(monkeypatch):
    limiter = RedditRateLimiter(min_interval=1, max_interval=100, initial_interval=4)
    monkeypatch.setattr("ingest.reddit_rate_limit.get_limiter", lambda: limiter)

    class FakeResponse:
        status_code = 429
        ok = False
        headers = {"Retry-After": "50"}

    monkeypatch.setattr(
        "ingest.reddit_rate_limit.requests.get", lambda url, **kw: FakeResponse()
    )
    monkeypatch.setattr("ingest.reddit_rate_limit.time.sleep", lambda s: None)

    response = reddit_get("https://www.reddit.com/r/pics/top.rss")
    assert response.status_code == 429
    # 429 backs the whole limiter off
    assert limiter.interval == 8
