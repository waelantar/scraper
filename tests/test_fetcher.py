# tests/test_fetcher.py
import pytest
from unittest.mock import patch, MagicMock
import urllib.error
from python_engine.fetcher import fetch, FetchResult

# -----------------------------------------------------------------------------
# Unit tests (offline, deterministic, no network)
# -----------------------------------------------------------------------------

def test_fetch_200_success():
    """A 200 response decodes and returns the full HTML string."""
    fake_html_bytes = b"<html><body>Hello, world!</body></html>"

    mock_response = MagicMock()
    mock_response.read.return_value = fake_html_bytes
    mock_response.getcode.return_value = 200
    mock_response.headers = {"Content-Type": "text/html; charset=utf-8"}

    with patch("python_engine.fetcher.urlopen") as mock_urlopen:
        mock_urlopen.return_value.__enter__.return_value = mock_response

        result = fetch("https://books.toscrape.com/")

        assert result.status_code == 200
        # We expect the full HTML text (decoded bytes)
        assert result.html == "<html><body>Hello, world!</body></html>"
        assert result.error is None
        assert result.content_type == "text/html"


def test_fetch_404_http_error():
    """A 404 should be caught as HTTPError -> status_code=404, no html."""
    fake_404 = urllib.error.HTTPError(
        "https://books.toscrape.com/nonexistent",
        404,
        "Not Found",
        {},
        None
    )

    with patch("python_engine.fetcher.urlopen") as mock_urlopen:
        mock_urlopen.side_effect = fake_404

        result = fetch("https://books.toscrape.com/nonexistent")

        assert result.status_code == 404
        assert result.html is None
        assert result.error == "HTTP 404: Not Found"
        assert result.content_type is None


def test_fetch_network_error_urlerror():
    """DNS / connection errors -> URLError -> status_code=None."""
    fake_network_error = urllib.error.URLError("DNS lookup failed")

    with patch("python_engine.fetcher.urlopen") as mock_urlopen:
        mock_urlopen.side_effect = fake_network_error

        result = fetch("https://this-domain-does-not-exist-12345.com/")

        assert result.status_code is None
        assert result.html is None
        assert result.error == "Network error: DNS lookup failed"
        assert result.content_type is None


def test_fetch_timeout():
    """Timeout -> URLError -> status_code=None."""
    fake_timeout = urllib.error.URLError("Timeout")

    with patch("python_engine.fetcher.urlopen") as mock_urlopen:
        mock_urlopen.side_effect = fake_timeout

        result = fetch("https://httpbin.org/delay/5", timeout=1)

        assert result.status_code is None
        assert result.html is None
        assert "Timeout" in result.error


def test_fetch_non_utf8_content():
    """Invalid UTF-8 should be decoded with errors='replace' (no crash)."""
    fake_invalid_bytes = b"\xe9\xe9\xe9"  # invalid UTF-8 sequence
    mock_response = MagicMock()
    mock_response.read.return_value = fake_invalid_bytes
    mock_response.getcode.return_value = 200
    mock_response.headers = {"Content-Type": "text/html"}

    with patch("python_engine.fetcher.urlopen") as mock_urlopen:
        mock_urlopen.return_value.__enter__.return_value = mock_response

        result = fetch("https://example.com/bad-encoding")

        assert result.status_code == 200
        assert result.html is not None
        # Replacement characters appear
        assert "�" in result.html


def test_fetch_huge_page_truncation():
    """A page larger than max_bytes should be truncated."""
    huge_bytes = b"a" * 6_000_000  # 6 MB
    mock_response = MagicMock()
    mock_response.read.side_effect = [huge_bytes]  # returns full 6 MB in one go
    mock_response.getcode.return_value = 200
    mock_response.headers = {"Content-Type": "text/html"}

    with patch("python_engine.fetcher.urlopen") as mock_urlopen:
        mock_urlopen.return_value.__enter__.return_value = mock_response

        result = fetch("https://example.com/huge")

        # The fetcher calls read(max_bytes) – we assert that
        mock_response.read.assert_called_once_with(5_000_000)
        # After reading, the fetcher should slice to max_bytes
        assert len(result.html) == 5_000_000
        assert result.html == "a" * 5_000_000


# -----------------------------------------------------------------------------
# Integration tests (live network, opt-in)
# -----------------------------------------------------------------------------

@pytest.mark.network
def test_integration_books_toscrape():
    """Live smoke test against a known public site."""
    result = fetch("https://books.toscrape.com/")
    assert result.status_code == 200
    assert result.html is not None
    assert "books" in result.html.lower()

@pytest.mark.network
def test_integration_404_live():
    """Live test for a 404 on a real site."""
    result = fetch("https://books.toscrape.com/nonexistent")
    assert result.status_code == 404
    assert result.html is None
    assert "404" in result.error