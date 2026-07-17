# tests/test_parser.py
import pytest
from python_engine.parser import parse_html


# -----------------------------------------------------------------------------
# Unit tests (offline, using sample HTML strings)
# -----------------------------------------------------------------------------

SAMPLE_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Test Page Title</title>
    <style>body { color: red; } /* this should be skipped */</style>
    <script>console.log("skip me too");</script>
</head>
<body>
    <h1>Welcome to the test page</h1>
    <p>This is visible text that should be extracted.</p>
    <ul>
        <li><a href="/root-relative">Root Relative Link</a></li>
        <li><a href="path-relative">Path Relative Link</a></li>
        <li><a href="https://example.com/absolute">Absolute Link</a></li>
        <li><a href="#fragment">Fragment Only</a></li>
        <li><a href="mailto:test@example.com">Email</a></li>
        <li><a href="javascript:void(0)">JS Link</a></li>
    </ul>
    <div>More visible text.</div>
</body>
</html>
"""


def test_parse_title():
    result = parse_html("https://example.com/", SAMPLE_HTML)
    assert result.title == "Test Page Title"


def test_parse_visible_text():
    result = parse_html("https://example.com/", SAMPLE_HTML)
    assert "Welcome to the test page" in result.text
    assert "This is visible text" in result.text
    assert "More visible text" in result.text
    assert "color: red" not in result.text
    assert "console.log" not in result.text


def test_parse_absolute_links():
    """Absolute and root‑relative links are resolved correctly."""
    result = parse_html("https://example.com/catalogue/", SAMPLE_HTML)
    links = result.links

    # Root-relative (starts with /) → resolves against domain root
    assert "https://example.com/root-relative" in links

    # Path-relative (no leading /) → resolves against the current path
    assert "https://example.com/catalogue/path-relative" in links

    # Absolute stays absolute
    assert "https://example.com/absolute" in links


def test_parse_filters_non_http_schemes():
    """mailto:, javascript:, and fragments are filtered out."""
    result = parse_html("https://example.com/catalogue/", SAMPLE_HTML)
    links = result.links

    # Should NOT contain non‑http schemes
    assert "mailto:test@example.com" not in links
    assert "javascript:void(0)" not in links
    # Fragments should be filtered (not even resolved to absolute)
    # Our implementation will skip them before urljoin, or urljoin will produce
    # https://example.com/catalogue/#fragment, but scheme is http, so we need
    # explicit fragment stripping in the parser to remove it.
    # The correct filter: skip if href starts with '#'.
    # Since we do that in the parser, it won't appear.
    assert "#fragment" not in " ".join(links)


def test_parse_links_deduplication():
    html_with_dups = """
    <a href="/page1">Link 1</a>
    <a href="/page1">Duplicate</a>
    <a href="/page2">Different</a>
    """
    result = parse_html("https://example.com/", html_with_dups)
    assert len(result.links) == 2
    assert "https://example.com/page1" in result.links
    assert "https://example.com/page2" in result.links


def test_parse_malformed_html():
    malformed = "<html><head><title>Title</title></head><body><p>Text"
    result = parse_html("https://example.com/", malformed)
    assert result.title == "Title"
    assert "Text" in result.text


def test_parse_empty_html():
    result = parse_html("https://example.com/", "")
    assert result.title == ""
    assert result.text == ""
    assert result.links == []


def test_parse_text_size_limit():
    large_text = "word " * 1000
    html = f"<html><body>{large_text}</body></html>"
    result = parse_html("https://example.com/", html, max_text_size=100)
    assert len(result.text) <= 100


# -----------------------------------------------------------------------------
# Integration tests (opt-in, live)
# -----------------------------------------------------------------------------

@pytest.mark.network
def test_parse_live_books_toscrape():
    from python_engine.fetcher import fetch

    result = fetch("https://books.toscrape.com/")
    assert result.status_code == 200

    parsed = parse_html(result.url, result.html)
    assert parsed.title
    assert "Books" in parsed.title
    assert parsed.text
    assert "Books" in parsed.text
    assert len(parsed.links) > 0
    for link in parsed.links:
        assert link.startswith("http")

def test_parse_text_size_limit_multi_chunk():
    """Test that the cap is enforced even with many tiny chunks + separators."""
    # Many small chunks produce many joining spaces.
    chunks = ["a"] * 50   # 50 parts, joined -> len = 50 + 49 = 99
    html = "<html><body>" + "".join(f"<p>{ch}</p>" for ch in chunks) + "</body></html>"

    result = parse_html("https://example.com/", html, max_text_size=20)
    # Without the fix, this would be 99. With the fix, it's ≤ 20.
    assert len(result.text) == 20