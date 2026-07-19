# tests/test_orchestrator.py
import pytest
import threading
import time
from typing import Dict, Any

from python_engine.orchestrator import Crawler
from python_engine.cache import PageCache
from python_engine.fetcher import FetchResult
from python_engine.politeness import RobotsChecker, DomainRateLimiter


# ========================================================================
# Mock fetcher factory
# ========================================================================

def make_fake_fetcher(graph: Dict[str, Dict[str, Any]]):
    def fake_fetch(url: str) -> FetchResult:
        page = graph.get(url)
        if page is None:
            return FetchResult(
                url=url,
                status_code=404,
                html=None,
                error="Not in mock graph",
                content_type=None,
            )
        html = f"""<html>
        <head><title>{page['title']}</title></head>
        <body>
            <p>{page['text']}</p>
            <ul>
            {''.join(f'<li><a href="{link}">{link}</a></li>' for link in page['links'])}
            </ul>
        </body>
        </html>"""
        return FetchResult(
            url=url,
            status_code=200,
            html=html,
            error=None,
            content_type="text/html",
        )
    return fake_fetch


@pytest.fixture
def cache_db(tmp_path):
    return str(tmp_path / "test.db")


# ========================================================================
# Helper: create a fast crawler (no politeness delays)
# ========================================================================

def make_fast_crawler(**kwargs):
    """
    Creates a Crawler with politeness disabled and rate limiting turned off.
    Override any argument via kwargs.
    """
    # Defaults: fast, offline
    defaults = {
        "num_workers": 2,
        "fetch_fn": make_fake_fetcher({}),  # will be overridden by tests
        "respect_robots": False,
        # Rate limiter with delay=0 (never sleeps)
        "rate_limiter": DomainRateLimiter(
            delay=0.0,
            time_fn=lambda: 0.0,
            sleep_fn=lambda _: None,
        ),
    }
    # Merge with kwargs (kwargs override defaults)
    config = {**defaults, **kwargs}
    return Crawler(**config)


# ========================================================================
# Mechanics tests (all with politeness disabled)
# ========================================================================

def test_single_seed_url(cache_db):
    graph = {
        "https://seed.com/": {"title": "Seed", "text": "Seed page", "links": []},
    }
    crawler = make_fast_crawler(
        seed_urls=["https://seed.com/"],
        db_path=cache_db,
        fetch_fn=make_fake_fetcher(graph),
        max_depth=0,
    )
    crawler.crawl()
    cache = PageCache(cache_db)
    assert cache.has("https://seed.com/") is True
    stats = crawler.get_stats()
    assert stats["crawled"] == 1
    assert stats["errors"] == 0
    assert stats["attempted"] == 1


def test_dedup_self_loop(cache_db):
    graph = {
        "https://seed.com/a": {
            "title": "A",
            "text": "Page A",
            "links": ["https://seed.com/a", "https://seed.com/c"],
        },
        "https://seed.com/c": {"title": "C", "text": "Page C", "links": []},
    }
    crawler = make_fast_crawler(
        seed_urls=["https://seed.com/a"],
        db_path=cache_db,
        fetch_fn=make_fake_fetcher(graph),
        max_depth=1,
    )
    crawler.crawl()
    cache = PageCache(cache_db)
    assert cache.has("https://seed.com/a") is True
    assert cache.has("https://seed.com/c") is True
    stats = crawler.get_stats()
    assert stats["crawled"] == 2


def test_depth_limit(cache_db):
    graph = {
        "https://seed.com/": {
            "title": "Seed",
            "text": "Seed",
            "links": ["https://seed.com/a", "https://seed.com/b"],
        },
        "https://seed.com/a": {
            "title": "A",
            "text": "A",
            "links": ["https://seed.com/c"],
        },
        "https://seed.com/b": {"title": "B", "text": "B", "links": []},
        "https://seed.com/c": {"title": "C", "text": "C", "links": []},
    }
    crawler = make_fast_crawler(
        seed_urls=["https://seed.com/"],
        db_path=cache_db,
        fetch_fn=make_fake_fetcher(graph),
        max_depth=1,
    )
    crawler.crawl()
    cache = PageCache(cache_db)
    assert cache.has("https://seed.com/") is True
    assert cache.has("https://seed.com/a") is True
    assert cache.has("https://seed.com/b") is True
    assert cache.has("https://seed.com/c") is False
    stats = crawler.get_stats()
    assert stats["crawled"] == 3


def test_domain_filter(cache_db):
    graph = {
        "https://seed.com/": {
            "title": "Seed",
            "text": "Seed",
            "links": [
                "https://seed.com/a",
                "https://evil.com/offdomain",
            ],
        },
        "https://seed.com/a": {"title": "A", "text": "A", "links": []},
        "https://evil.com/offdomain": {"title": "Evil", "text": "Off", "links": []},
    }
    crawler = make_fast_crawler(
        seed_urls=["https://seed.com/"],
        db_path=cache_db,
        fetch_fn=make_fake_fetcher(graph),
        max_depth=1,
        same_domain=True,
    )
    crawler.crawl()
    cache = PageCache(cache_db)
    assert cache.has("https://seed.com/") is True
    assert cache.has("https://seed.com/a") is True
    assert cache.has("https://evil.com/offdomain") is False
    stats = crawler.get_stats()
    assert stats["crawled"] == 2


def test_max_urls_limit(cache_db):
    graph = {
        "https://seed.com/": {
            "title": "Seed",
            "text": "Seed",
            "links": ["https://seed.com/a", "https://seed.com/b"],
        },
        "https://seed.com/a": {"title": "A", "text": "A", "links": []},
        "https://seed.com/b": {"title": "B", "text": "B", "links": []},
        "https://seed.com/c": {"title": "C", "text": "C", "links": []},
    }
    crawler = make_fast_crawler(
        seed_urls=["https://seed.com/"],
        db_path=cache_db,
        fetch_fn=make_fake_fetcher(graph),
        max_depth=None,
        max_urls=2,
    )
    t = threading.Thread(target=crawler.crawl)
    t.start()
    t.join(timeout=5.0)
    assert not t.is_alive()
    stats = crawler.get_stats()
    assert stats["attempted"] == 2
    assert stats["crawled"] == 2


def test_termination_detection(cache_db):
    graph = {
        "https://seed.com/": {
            "title": "Seed",
            "text": "Seed",
            "links": ["https://seed.com/a", "https://seed.com/b"],
        },
        "https://seed.com/a": {
            "title": "A",
            "text": "A",
            "links": ["https://seed.com/c"],
        },
        "https://seed.com/b": {"title": "B", "text": "B", "links": []},
        "https://seed.com/c": {"title": "C", "text": "C", "links": []},
    }
    crawler = make_fast_crawler(
        seed_urls=["https://seed.com/"],
        db_path=cache_db,
        fetch_fn=make_fake_fetcher(graph),
        max_depth=None,
    )
    crawler.crawl()
    cache = PageCache(cache_db)
    expected = {"https://seed.com/", "https://seed.com/a", "https://seed.com/b", "https://seed.com/c"}
    crawled = {url for url in expected if cache.has(url)}
    assert crawled == expected
    stats = crawler.get_stats()
    assert stats["attempted"] == 4
    assert stats["crawled"] == 4


def test_shutdown_during_crawl(cache_db):
    graph = {
        "https://seed.com/": {
            "title": "Seed",
            "text": "Seed",
            "links": ["https://seed.com/a"],
        },
        "https://seed.com/a": {
            "title": "A",
            "text": "A",
            "links": ["https://seed.com/b"],
        },
        "https://seed.com/b": {"title": "B", "text": "B", "links": []},
    }
    crawler = make_fast_crawler(
        seed_urls=["https://seed.com/"],
        db_path=cache_db,
        fetch_fn=make_fake_fetcher(graph),
        max_depth=None,
    )
    t = threading.Thread(target=crawler.crawl)
    t.start()
    time.sleep(0.1)
    crawler.shutdown()
    t.join(timeout=2.0)
    assert not t.is_alive()
    assert crawler.pool.active_count == 0


def test_shutdown_idempotent(cache_db):
    graph = {
        "https://seed.com/": {
            "title": "Seed",
            "text": "Seed",
            "links": [],
        }
    }
    crawler = make_fast_crawler(
        seed_urls=["https://seed.com/"],
        db_path=cache_db,
        fetch_fn=make_fake_fetcher(graph),
    )
    crawler.crawl()
    crawler.shutdown()
    # Should not raise


# ========================================================================
# Politeness tests (respect_robots=True, injected checkers)
# ========================================================================

def test_robots_disallows_url(cache_db):
    # Use bare product token for robots matching
    robots_txt = """User-agent: MyCrawler
Disallow: /private/
"""
    checker = RobotsChecker(user_agent="MyCrawler/1.0")  # Full UA for the crawler
    checker.parse_for_domain("example.com", robots_txt.splitlines())

    graph = {
        "https://example.com/": {
            "title": "Seed",
            "text": "Seed page",
            "links": ["https://example.com/private/secret"],
        },
        "https://example.com/private/secret": {
            "title": "Secret",
            "text": "Secret page",
            "links": [],
        },
    }
    fake_fetch = make_fake_fetcher(graph)
    fetch_calls = []

    def spy_fetch(url):
        fetch_calls.append(url)
        return fake_fetch(url)

    crawler = Crawler(
        seed_urls=["https://example.com/"],
        db_path=cache_db,
        num_workers=2,
        max_depth=1,
        robots_checker=checker,
        fetch_fn=spy_fetch,
        respect_robots=True,
        # Use a fast rate limiter for this test (don't sleep)
        rate_limiter=DomainRateLimiter(delay=0.0, time_fn=lambda: 0.0, sleep_fn=lambda _: None),
    )
    crawler.crawl()

    assert "https://example.com/" in fetch_calls
    assert "https://example.com/private/secret" not in fetch_calls

    stats = crawler.get_stats()
    assert stats["crawled"] == 1
    assert stats["skipped_robots"] == 1
    assert stats["errors"] == 0


def test_rate_limiting_applied(cache_db):
    graph = {
        "https://example.com/": {
            "title": "Seed",
            "text": "Seed",
            "links": [
                "https://example.com/page1",
                "https://example.com/page2",
            ],
        },
        "https://example.com/page1": {"title": "Page1", "text": "Page1", "links": []},
        "https://example.com/page2": {"title": "Page2", "text": "Page2", "links": []},
    }
    fake_fetch = make_fake_fetcher(graph)
    rate_limit_calls = []

    def spy_wait_if_needed(domain):
        rate_limit_calls.append(domain)

    limiter = DomainRateLimiter(
        delay=0.1,
        time_fn=lambda: 0.0,
        sleep_fn=lambda _: None,
    )
    original_wait = limiter.wait_if_needed

    def wrapped_wait(domain):
        spy_wait_if_needed(domain)
        original_wait(domain)

    limiter.wait_if_needed = wrapped_wait

    crawler = Crawler(
        seed_urls=["https://example.com/"],
        db_path=cache_db,
        num_workers=2,
        max_depth=1,
        fetch_fn=fake_fetch,
        rate_limiter=limiter,
        respect_robots=False,  # robots off for this test
    )
    crawler.crawl()

    assert "example.com" in rate_limit_calls
    assert len(rate_limit_calls) >= 3


# ========================================================================
# Network integration test (opt-in)
# ========================================================================

@pytest.mark.network
def test_real_books_toscrape_smoke(cache_db):
    crawler = Crawler(
        seed_urls=["https://books.toscrape.com/"],
        db_path=cache_db,
        num_workers=2,
        max_depth=0,
        same_domain=True,
        respect_robots=False,
        # Use a real but fast rate limiter (delay=0.1s)
        crawl_delay=0.1,
    )
    crawler.crawl()
    cache = PageCache(cache_db)
    assert cache.has("https://books.toscrape.com/") is True
    stats = crawler.get_stats()
    assert stats["crawled"] == 1
    assert stats["errors"] == 0