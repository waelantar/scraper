# python_engine/politeness.py
import threading
import time
import urllib.request
from urllib.robotparser import RobotFileParser
from typing import Dict, Optional, Callable
from urllib.parse import urlparse


def default_robots_fetcher(domain: str) -> str:
    """Default robots.txt fetcher using urllib.request."""
    url = f"https://{domain}/robots.txt"
    with urllib.request.urlopen(url, timeout=5.0) as response:
        return response.read().decode("utf-8", errors="replace")


class RobotsChecker:
    """
    Thread‑safe robots.txt checker with per‑domain caching.

    Lazy loading: the first call to can_fetch() for a domain triggers a fetch of robots.txt.
    If the fetch fails, we default to ALLOWING all requests (lenient policy).
    This matches the conventional "fail open" behaviour for crawlers.

    The fetch function can be injected for testing (offline, deterministic).
    """

    def __init__(
        self,
        user_agent: str = "MyCrawler/1.0",
        robots_fetcher: Callable[[str], str] = default_robots_fetcher,
    ):
        self.user_agent = user_agent
        self.robots_fetcher = robots_fetcher
        self._parsers: Dict[str, RobotFileParser] = {}
        self._lock = threading.Lock()
        self._loaded: set[str] = set()

    def parse_for_domain(self, domain: str, lines: list[str]) -> None:
        """
        Feed raw robot.txt lines directly (for testing / offline use).
        Marks the domain as loaded to prevent network fetches.
        """
        parser = RobotFileParser()
        parser.parse(lines)
        with self._lock:
            self._parsers[domain] = parser
            self._loaded.add(domain)

    def _ensure_loaded(self, domain: str) -> None:
        """Load robots.txt for a domain if not already loaded."""
        with self._lock:
            if domain in self._loaded:
                return
            # Mark as loaded BEFORE we attempt the fetch to prevent duplicate reads
            self._loaded.add(domain)

        # Actually fetch (outside the lock)
        parser = RobotFileParser()
        try:
            content = self.robots_fetcher(domain)
            parser.parse(content.splitlines())
        except Exception:
            # If robots.txt is unavailable, we set allow_all = True
            # This makes can_fetch() return True for all URLs.
            parser.allow_all = True

        with self._lock:
            self._parsers[domain] = parser

    def can_fetch(self, url: str) -> bool:
        """
        Check if a URL is allowed by robots.txt.

        Unknown domains are loaded lazily (first call triggers a fetch).
        If robots.txt cannot be fetched, returns True (allow).
        """
        parsed = urlparse(url)
        domain = parsed.netloc

        # Ensure loaded
        self._ensure_loaded(domain)

        with self._lock:
            parser = self._parsers.get(domain)
            if parser is None:
                # Should not happen, but fallback to allow
                return True
            # If parser has allow_all True, it will return True.
            # Otherwise, it will check the rules.
            return parser.can_fetch(self.user_agent, url)


class DomainRateLimiter:
    """Same as before; unchanged."""
    def __init__(
        self,
        delay: float = 1.0,
        time_fn: Callable[[], float] = time.monotonic,
        sleep_fn: Callable[[float], None] = time.sleep,
    ):
        self.delay = delay
        self.time_fn = time_fn
        self.sleep_fn = sleep_fn
        self._lock = threading.Lock()
        self._next_allowed: Dict[str, float] = {}

    def wait_if_needed(self, domain: str) -> None:
        now = self.time_fn()
        with self._lock:
            next_allowed = self._next_allowed.get(domain, 0.0)
            if now >= next_allowed:
                wait = 0.0
                self._next_allowed[domain] = now + self.delay
            else:
                wait = next_allowed - now
                self._next_allowed[domain] = next_allowed + self.delay
        if wait > 0:
            self.sleep_fn(wait)

    def reset(self) -> None:
        with self._lock:
            self._next_allowed.clear()