# python_engine/cache.py
import sqlite3
import json
import time
from contextlib import closing
from typing import Optional, List

from python_engine.parser import ParsedPage


class PageCache:
    """
    SQLite-backed cache for crawled pages.

    SINGLE SOURCE OF TRUTH for the 'pages' table schema.
    Columns (matches C1 contract + links_json):
        - url TEXT PRIMARY KEY
        - title TEXT
        - content TEXT
        - status_code INTEGER
        - crawled_at INTEGER (Unix epoch)
        - links_json TEXT (JSON array of absolute URLs)

    Thread-safe: each method opens its own short-lived connection.
    """

    def __init__(self, db_path: str = "crawler.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """Create the pages table if it doesn't exist."""
        with closing(sqlite3.connect(self.db_path, timeout=5.0)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS pages (
                    url TEXT PRIMARY KEY,
                    title TEXT,
                    content TEXT,
                    status_code INTEGER,
                    crawled_at INTEGER,
                    links_json TEXT
                )
            """)
            conn.commit()

    def put(self, page: ParsedPage, status_code: Optional[int] = None) -> None:
        """
        Store or replace a page in the cache.
        The status_code comes from the fetch result (default None).
        """
        with closing(sqlite3.connect(self.db_path, timeout=5.0)) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO pages
                (url, title, content, status_code, crawled_at, links_json)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                page.url,
                page.title,
                page.text,          # maps to 'content' column
                status_code,
                int(time.time()),   # Unix epoch seconds
                json.dumps(page.links),
            ))
            conn.commit()

    def get(self, url: str) -> Optional[ParsedPage]:
        """Retrieve a page by URL; returns None if not found."""
        with closing(sqlite3.connect(self.db_path, timeout=5.0)) as conn:
            cursor = conn.execute(
                "SELECT url, title, content, links_json FROM pages WHERE url = ?",
                (url,)
            )
            row = cursor.fetchone()
            if row is None:
                return None
            url, title, content, links_json = row
            links = json.loads(links_json) if links_json else []
            return ParsedPage(
                url=url,
                title=title,
                text=content,
                links=links
            )

    def has(self, url: str) -> bool:
        """Check if a URL exists in the cache."""
        with closing(sqlite3.connect(self.db_path, timeout=5.0)) as conn:
            cursor = conn.execute("SELECT 1 FROM pages WHERE url = ?", (url,))
            return cursor.fetchone() is not None

    def delete_all(self) -> None:
        """Wipe the cache (for testing)."""
        with closing(sqlite3.connect(self.db_path, timeout=5.0)) as conn:
            conn.execute("DELETE FROM pages")
            conn.commit()

    def close(self) -> None:
        """No persistent connection; placeholder for API consistency."""
        pass