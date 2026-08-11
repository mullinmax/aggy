import pytest

from ingest.reddit_rate_limit import (
    RedditBlocked,
    RedditCircuit,
    RedditRateLimiter,
    _parse_retry_after,
    circuit_name,
    get_circuit,
    is_reddit_url,
    reddit_get,
)


@pytest.fixture(autouse=True)
def fresh_circuits():
    """Circuits are process-global; don't let one test's 403s leak into another."""
    import ingest.reddit_rate_limit as module

    module._circuits.clear()
    yield
    module._circuits.clear()


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


def test_circuit_name_separates_json_api_from_feeds():
    # reddit serves the public feeds to hosts it refuses the .json API to, so
    # a block on one must not stop the other
    assert circuit_name("https://www.reddit.com/r/pics/top.rss?t=day") == "feed"
    assert (
        circuit_name("https://www.reddit.com/r/pics/comments/abc/t.json?raw_json=1")
        == "post JSON"
    )


def test_get_circuit_is_cached_per_endpoint_class():
    feed = get_circuit("https://www.reddit.com/r/pics/top.rss")
    assert get_circuit("https://www.reddit.com/r/aww/.rss") is feed
    assert get_circuit("https://www.reddit.com/r/pics/comments/a/t.json") is not feed


def test_circuit_opens_only_after_consecutive_blocks():
    circuit = RedditCircuit("post JSON", threshold=3, cooldown=60, max_cooldown=600)

    circuit.record_blocked()
    circuit.record_blocked()
    assert circuit.remaining() is None  # under the threshold, still trying

    circuit.record_blocked()
    assert circuit.remaining() == pytest.approx(60, abs=1)


def test_circuit_run_of_blocks_is_broken_by_any_answer():
    circuit = RedditCircuit("post JSON", threshold=3, cooldown=60, max_cooldown=600)

    circuit.record_blocked()
    circuit.record_blocked()
    circuit.record_allowed()  # e.g. a 429: reddit is answering, just not fast
    circuit.record_blocked()
    assert circuit.remaining() is None


def test_circuit_cooldown_doubles_on_each_retrip(monkeypatch):
    clock = {"t": 0.0}
    monkeypatch.setattr("ingest.reddit_rate_limit.time.monotonic", lambda: clock["t"])
    circuit = RedditCircuit("post JSON", threshold=1, cooldown=60, max_cooldown=600)

    circuit.record_blocked()
    assert circuit.remaining() == pytest.approx(60)

    # once the cooldown lapses the next request is a probe; a 403 to it means
    # reddit still isn't serving us, so the wait doubles
    clock["t"] += 61
    assert circuit.remaining() is None
    circuit.record_blocked()
    assert circuit.remaining() == pytest.approx(120)

    clock["t"] += 121
    circuit.record_blocked()
    assert circuit.remaining() == pytest.approx(240)


def test_circuit_cooldown_respects_ceiling(monkeypatch):
    clock = {"t": 0.0}
    monkeypatch.setattr("ingest.reddit_rate_limit.time.monotonic", lambda: clock["t"])
    circuit = RedditCircuit("post JSON", threshold=1, cooldown=60, max_cooldown=100)

    for _ in range(5):
        circuit.record_blocked()
        clock["t"] += circuit.remaining() + 1

    circuit.record_blocked()
    assert circuit.remaining() == pytest.approx(100)


def test_circuit_success_closes_and_resets_escalation(monkeypatch):
    clock = {"t": 0.0}
    monkeypatch.setattr("ingest.reddit_rate_limit.time.monotonic", lambda: clock["t"])
    circuit = RedditCircuit("post JSON", threshold=1, cooldown=60, max_cooldown=600)

    circuit.record_blocked()
    circuit.record_blocked()
    circuit.record_success()
    assert circuit.remaining() is None

    # the next block starts over at the base cooldown, not the escalated one
    circuit.record_blocked()
    assert circuit.remaining() == pytest.approx(60)


def test_reddit_get_opens_circuit_on_blocked(monkeypatch):
    limiter = RedditRateLimiter(min_interval=1, max_interval=100, initial_interval=4)
    circuit = RedditCircuit("post JSON", threshold=2, cooldown=60, max_cooldown=600)
    monkeypatch.setattr("ingest.reddit_rate_limit.get_limiter", lambda: limiter)
    monkeypatch.setattr("ingest.reddit_rate_limit.get_circuit", lambda url: circuit)
    monkeypatch.setattr("ingest.reddit_rate_limit.time.sleep", lambda s: None)

    class FakeResponse:
        status_code = 403
        ok = False

    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        return FakeResponse()

    monkeypatch.setattr("ingest.reddit_rate_limit.requests.get", fake_get)

    url = "https://www.reddit.com/r/pics/comments/abc/t.json"
    assert reddit_get(url).status_code == 403
    assert reddit_get(url).status_code == 403
    assert len(calls) == 2

    # the third attempt never reaches reddit
    with pytest.raises(RedditBlocked):
        reddit_get(url)
    assert len(calls) == 2


def test_reddit_get_blocked_does_not_slow_the_throttle(monkeypatch):
    # a 403 is a policy refusal, not a pace complaint: slowing every reddit
    # request down would punish the feeds reddit is still happily serving
    limiter = RedditRateLimiter(min_interval=1, max_interval=100, initial_interval=4)
    circuit = RedditCircuit("post JSON", threshold=10, cooldown=60, max_cooldown=600)
    monkeypatch.setattr("ingest.reddit_rate_limit.get_limiter", lambda: limiter)
    monkeypatch.setattr("ingest.reddit_rate_limit.get_circuit", lambda url: circuit)
    monkeypatch.setattr("ingest.reddit_rate_limit.time.sleep", lambda s: None)

    class FakeResponse:
        status_code = 403
        ok = False

    monkeypatch.setattr(
        "ingest.reddit_rate_limit.requests.get", lambda url, **kw: FakeResponse()
    )

    reddit_get("https://www.reddit.com/r/pics/comments/abc/t.json")
    assert limiter.interval == 4


def test_reddit_get_success_closes_an_open_circuit(monkeypatch):
    clock = {"t": 0.0}
    monkeypatch.setattr("ingest.reddit_rate_limit.time.monotonic", lambda: clock["t"])
    limiter = RedditRateLimiter(min_interval=1, max_interval=100, initial_interval=4)
    circuit = RedditCircuit("post JSON", threshold=1, cooldown=60, max_cooldown=600)
    monkeypatch.setattr("ingest.reddit_rate_limit.get_limiter", lambda: limiter)
    monkeypatch.setattr("ingest.reddit_rate_limit.get_circuit", lambda url: circuit)
    monkeypatch.setattr("ingest.reddit_rate_limit.time.sleep", lambda s: None)

    class FakeResponse:
        def __init__(self, status_code):
            self.status_code = status_code
            self.ok = status_code == 200

    responses = [FakeResponse(403), FakeResponse(200)]
    monkeypatch.setattr(
        "ingest.reddit_rate_limit.requests.get", lambda url, **kw: responses.pop(0)
    )

    url = "https://www.reddit.com/r/pics/comments/abc/t.json"
    reddit_get(url)
    assert circuit.remaining() == pytest.approx(60)

    # once the cooldown lapses the probe succeeds, which closes the circuit
    clock["t"] += 61
    assert reddit_get(url).status_code == 200

    # and puts the next block back at the base cooldown rather than double it
    circuit.record_blocked()
    assert circuit.remaining() == pytest.approx(60)
