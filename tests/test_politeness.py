# tests/test_politeness.py
import pytest
import threading
import time
from python_engine.politeness import RobotsChecker, DomainRateLimiter


# ========================================================================
# RobotsChecker tests (with injected fetcher for offline testing)
# ========================================================================

def test_robots_disallows_url():
    # Use bare product token for robots matching
    checker = RobotsChecker(user_agent="MyCrawler")
    robots_txt = """User-agent: MyCrawler
Disallow: /private/
Allow: /public/
"""
    checker.parse_for_domain("example.com", robots_txt.splitlines())

    assert checker.can_fetch("https://example.com/private/secret") is False
    assert checker.can_fetch("https://example.com/public/page") is True
    assert checker.can_fetch("https://example.com/another") is True


def test_robots_allow_all_when_unavailable():
    # Inject a fetcher that raises (simulates network failure)
    def failing_fetcher(domain: str) -> str:
        raise Exception("Simulated robots.txt fetch failure")

    checker = RobotsChecker(user_agent="MyCrawler", robots_fetcher=failing_fetcher)
    # Unknown domain: should default to allow
    assert checker.can_fetch("https://unavailable-site.com/any") is True


def test_robots_wildcard_user_agent():
    checker = RobotsChecker(user_agent="MyCrawler")
    robots_txt = """User-agent: *
Disallow: /admin/
"""
    checker.parse_for_domain("example.com", robots_txt.splitlines())

    # Trailing-slash semantics: /admin/ matches /admin/panel but not /admin
    assert checker.can_fetch("https://example.com/admin/panel") is False
    assert checker.can_fetch("https://example.com/public") is True
    # The bare /admin is allowed (doesn't start with /admin/)
    assert checker.can_fetch("https://example.com/admin") is True


# ========================================================================
# DomainRateLimiter tests (unchanged)
# ========================================================================

def test_rate_limiter_first_request_no_wait():
    limiter = DomainRateLimiter(
        delay=1.0,
        time_fn=lambda: 0.0,
        sleep_fn=lambda x: None,
    )
    limiter.wait_if_needed("example.com")
    assert limiter._next_allowed["example.com"] == 1.0


def test_rate_limiter_second_request_waits():
    time_seq = [0.0, 0.0]
    calls = []

    def time_fn():
        return time_seq.pop(0)

    def sleep_fn(dur):
        calls.append(("sleep", dur))

    limiter = DomainRateLimiter(delay=1.0, time_fn=time_fn, sleep_fn=sleep_fn)
    limiter.wait_if_needed("example.com")
    limiter.wait_if_needed("example.com")

    assert calls == [("sleep", 1.0)]


def test_rate_limiter_multiple_domains_independent():
    time_seq = [0.0, 0.0, 0.0]
    calls = []

    def time_fn():
        return time_seq.pop(0)

    def sleep_fn(dur):
        calls.append(("sleep", dur))

    limiter = DomainRateLimiter(delay=2.0, time_fn=time_fn, sleep_fn=sleep_fn)
    limiter.wait_if_needed("a.com")
    limiter.wait_if_needed("b.com")
    limiter.wait_if_needed("a.com")

    assert calls == [("sleep", 2.0)]


def test_rate_limiter_concurrent():
    delay = 0.1
    num_threads = 5

    time_values = [0.0] * num_threads
    time_index = 0
    time_lock = threading.Lock()
    calls = []

    def time_fn():
        nonlocal time_index
        with time_lock:
            val = time_values[time_index]
            time_index += 1
            return val

    def sleep_fn(dur):
        calls.append(("sleep", dur))

    limiter = DomainRateLimiter(delay=delay, time_fn=time_fn, sleep_fn=sleep_fn)

    def worker():
        limiter.wait_if_needed("example.com")

    threads = [threading.Thread(target=worker) for _ in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    total_slept = sum(dur for _, dur in calls)
    expected_total = delay * num_threads * (num_threads - 1) / 2
    assert abs(total_slept - expected_total) < 0.01

    max_wait = max([dur for _, dur in calls] or [0.0])
    expected_max = (num_threads - 1) * delay
    assert abs(max_wait - expected_max) < 0.01

    assert limiter._next_allowed["example.com"] == num_threads * delay


def test_rate_limiter_real_time_smoke():
    limiter = DomainRateLimiter(delay=0.1)
    start = time.monotonic()
    limiter.wait_if_needed("example.com")
    limiter.wait_if_needed("example.com")
    elapsed = time.monotonic() - start
    assert elapsed >= 0.1


def test_rate_limiter_reset():
    limiter = DomainRateLimiter(delay=1.0, time_fn=lambda: 0.0, sleep_fn=lambda x: None)
    limiter.wait_if_needed("example.com")
    assert "example.com" in limiter._next_allowed
    limiter.reset()
    assert "example.com" not in limiter._next_allowed