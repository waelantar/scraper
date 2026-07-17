# python_engine/fetcher.py
import urllib.request
import urllib.error
from typing import Optional
from dataclasses import dataclass
from urllib.request import urlopen


@dataclass
class FetchResult:
    url: str
    status_code: Optional[int]
    html: Optional[str]
    error: Optional[str]
    content_type: Optional[str]


def fetch(
    url: str,
    timeout: float = 10.0,
    max_bytes: int = 5_000_000,
    user_agent: str = "Mozilla/5.0 (compatible; MyCrawler/1.0; +https://example.com/bot)"
) -> FetchResult:
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})

    try:
        with urlopen(req, timeout=timeout) as response:
            raw_data = response.read(max_bytes)
            # ✅ Defensive slice: cap to max_bytes even if read() returns more (mock safety)
            raw_data = raw_data[:max_bytes]

            status_code = response.getcode()
            content_type = response.headers.get("Content-Type", "").split(";")[0].strip()

            try:
                html = raw_data.decode("utf-8")
            except UnicodeDecodeError:
                html = raw_data.decode("utf-8", errors="replace")

            return FetchResult(
                url=url,
                status_code=status_code,
                html=html,
                error=None,
                content_type=content_type or None,
            )

    except urllib.error.HTTPError as e:
        content_type = e.headers.get("Content-Type", "").split(";")[0].strip()
        return FetchResult(
            url=url,
            status_code=e.code,
            html=None,
            error=f"HTTP {e.code}: {e.reason}",
            content_type=content_type or None,
        )

    except urllib.error.URLError as e:
        return FetchResult(
            url=url,
            status_code=None,
            html=None,
            error=f"Network error: {e.reason}",
            content_type=None,
        )

    except Exception as e:
        return FetchResult(
            url=url,
            status_code=None,
            html=None,
            error=f"Unexpected error: {e}",
            content_type=None,
        )