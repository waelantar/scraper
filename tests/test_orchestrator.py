# tests/test_orchestrator.py
import pytest
import threading
import time
from typing import Dict, Any

from python_engine.orchestrator import Crawler
from python_engine.cache import PageCache
from python_engine.fetcher import FetchResult


# ========================================================================
# Mock fetcher factory
# ========================================================================

def make_fake_fetcher(graph: Dict[str, Dict[str, Any]]):
    """Create a fake fetch function from a link graph."""
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


# ========================================================================
# Fixtures
# ========================================================================

@pytest.fixture
def cache_db(tmp_path):
    """Cross-platform temp directory for test databases."""
    return str(tmp_path / "test.db")


# ========================================================================
# Unit tests (offline, deterministic)
# ========================================================================

def test_single_seed_url(cache_db):
    graph = {
        "https://seed.com/": {
            "title": "Seed",
            "text": "Seed page",
            "links": [],
        }
    }
    crawler = Crawler(
        seed_urls=["https://seed.com/"],
        db_path=cache_db,
        num_workers=1,
        max_depth=0,
        fetch_fn=make_fake_fetcher(graph),
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
        "https://seed.com/c": {
            "title": "C",
            "text": "Page C",
            "links": [],
        },
    }
    crawler = Crawler(
        seed_urls=["https://seed.com/a"],
        db_path=cache_db,
        num_workers=2,
        max_depth=1,
        fetch_fn=make_fake_fetcher(graph),
    )
    crawler.crawl()
    cache = PageCache(cache_db)
    assert cache.has("https://seed.com/a") is True
    assert cache.has("https://seed.com/c") is True
    stats = crawler.get_stats()
    assert stats["crawled"] == 2
    assert stats["errors"] == 0


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
    crawler = Crawler(
        seed_urls=["https://seed.com/"],
        db_path=cache_db,
        num_workers=2,
        max_depth=1,
        fetch_fn=make_fake_fetcher(graph),
    )
    crawler.crawl()
    cache = PageCache(cache_db)
    assert cache.has("https://seed.com/") is True
    assert cache.has("https://seed.com/a") is True
    assert cache.has("https://seed.com/b") is True
    assert cache.has("https://seed.com/c") is False  # depth 2
    stats = crawler.get_stats()
    assert stats["crawled"] == 3
    assert stats["errors"] == 0


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
    crawler = Crawler(
        seed_urls=["https://seed.com/"],
        db_path=cache_db,
        num_workers=2,
        max_depth=1,
        same_domain=True,
        fetch_fn=make_fake_fetcher(graph),
    )
    crawler.crawl()
    cache = PageCache(cache_db)
    assert cache.has("https://seed.com/") is True
    assert cache.has("https://seed.com/a") is True
    # Off-domain should NOT be crawled
    assert cache.has("https://evil.com/offdomain") is False
    stats = crawler.get_stats()
    assert stats["crawled"] == 2
    assert stats["errors"] == 0


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
    crawler = Crawler(
        seed_urls=["https://seed.com/"],
        db_path=cache_db,
        num_workers=2,
        max_depth=None,
        max_urls=2,
        fetch_fn=make_fake_fetcher(graph),
    )
    # Run crawl in thread with timeout to catch hangs
    t = threading.Thread(target=crawler.crawl)
    t.start()
    t.join(timeout=5.0)
    assert not t.is_alive(), "Crawl did not finish within timeout"

    stats = crawler.get_stats()
    assert stats["attempted"] == 2
    assert stats["crawled"] == 2
    assert stats["errors"] == 0


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
    crawler = Crawler(
        seed_urls=["https://seed.com/"],
        db_path=cache_db,
        num_workers=2,
        max_depth=None,
        fetch_fn=make_fake_fetcher(graph),
    )
    crawler.crawl()

    cache = PageCache(cache_db)
    expected = {"https://seed.com/", "https://seed.com/a", "https://seed.com/b", "https://seed.com/c"}
    crawled = {url for url in expected if cache.has(url)}
    assert crawled == expected

    stats = crawler.get_stats()
    assert stats["attempted"] == 4
    assert stats["crawled"] == 4
    assert stats["errors"] == 0


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
    crawler = Crawler(
        seed_urls=["https://seed.com/"],
        db_path=cache_db,
        num_workers=2,
        max_depth=None,
        fetch_fn=make_fake_fetcher(graph),
    )
    t = threading.Thread(target=crawler.crawl)
    t.start()
    time.sleep(0.1)
    crawler.shutdown()
    t.join(timeout=2.0)
    assert not t.is_alive()
    assert crawler.pool.active_count == 0


def test_shutdown_idempotent(cache_db):
    """Calling shutdown twice should not crash."""
    graph = {
        "https://seed.com/": {
            "title": "Seed",
            "text": "Seed",
            "links": [],
        }
    }
    crawler = Crawler(
        seed_urls=["https://seed.com/"],
        db_path=cache_db,
        num_workers=1,
        fetch_fn=make_fake_fetcher(graph),
    )
    crawler.crawl()
    crawler.shutdown()  # second call after crawl() already shut down
    # should not raise


# ========================================================================
# Network integration test (opt-in)
# ========================================================================

@pytest.mark.network
def test_real_books_toscrape_smoke(cache_db):
    """Smoke test against a real live site."""
    crawler = Crawler(
        seed_urls=["https://books.toscrape.com/"],
        db_path=cache_db,
        num_workers=2,
        max_depth=0,
        same_domain=True,
    )
    crawler.crawl()
    cache = PageCache(cache_db)
    assert cache.has("https://books.toscrape.com/") is True
    stats = crawler.get_stats()
    assert stats["crawled"] == 1
    assert stats["errors"] == 0