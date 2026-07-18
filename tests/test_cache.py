# tests/test_cache.py
import pytest
import threading
from python_engine.cache import PageCache
from python_engine.parser import ParsedPage


@pytest.fixture
def cache(tmp_path):
    """Use a temporary directory – cross‑platform safe."""
    db_file = tmp_path / "test.db"
    c = PageCache(db_path=str(db_file))
    yield c
    c.close()


def test_put_and_get(cache):
    page = ParsedPage(
        url="https://example.com/",
        title="Example Domain",
        text="This is a test page.",
        links=["https://example.com/page1", "https://example.com/page2"],
    )
    cache.put(page, status_code=200)
    retrieved = cache.get(page.url)
    assert retrieved is not None
    assert retrieved.url == page.url
    assert retrieved.title == page.title
    assert retrieved.text == page.text
    assert retrieved.links == page.links


def test_has_true(cache):
    page = ParsedPage(url="https://example.com/", title="", text="", links=[])
    cache.put(page)  # status_code defaults to None
    assert cache.has("https://example.com/") is True


def test_has_false(cache):
    assert cache.has("https://missing.com/") is False


def test_upsert_replaces_content(cache):
    page1 = ParsedPage(url="https://example.com/", title="Old Title", text="old", links=[])
    page2 = ParsedPage(url="https://example.com/", title="New Title", text="new", links=[])
    cache.put(page1, status_code=200)
    cache.put(page2, status_code=200)
    retrieved = cache.get("https://example.com/")
    assert retrieved.title == "New Title"
    assert retrieved.text == "new"


def test_multiple_urls(cache):
    pages = [
        ParsedPage(url="https://a.com/", title="A", text="aaa", links=[]),
        ParsedPage(url="https://b.com/", title="B", text="bbb", links=[]),
    ]
    for p in pages:
        cache.put(p, status_code=200)
    assert cache.has("https://a.com/")
    assert cache.has("https://b.com/")
    assert cache.has("https://c.com/") is False


def test_json_serialization(cache):
    links = ["https://x.com/1", "https://x.com/2"]
    page = ParsedPage(url="https://x.com/", title="X", text="x", links=links)
    cache.put(page)  # status_code defaults to None
    retrieved = cache.get(page.url)
    assert retrieved.links == links


def test_concurrent_writes(cache):
    """Multiple threads writing different URLs simultaneously."""
    urls = [f"https://test{i}.com/" for i in range(20)]
    pages = [
        ParsedPage(url=u, title=f"Title{i}", text=f"Text{i}", links=[])
        for i, u in enumerate(urls)
    ]

    def writer(p):
        cache.put(p, status_code=200)

    threads = [threading.Thread(target=writer, args=(p,)) for p in pages]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    for u in urls:
        assert cache.has(u) is True

    retrieved = cache.get(urls[0])
    assert retrieved.title == "Title0"
    assert retrieved.text == "Text0"