# python_engine/parser.py
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from typing import List, Dict, Optional
from dataclasses import dataclass, field


@dataclass
class ParsedPage:
    url: str
    title: str
    text: str
    links: List[str] = field(default_factory=list)


class CrawlerHTMLParser(HTMLParser):
    def __init__(self, base_url: str, max_text_size: int = 1_000_000):
        super().__init__()
        self.base_url = base_url
        self.max_text_size = max_text_size

        self.title = ""
        self._title_parts: List[str] = []
        self._in_title = False

        self._text_parts: List[str] = []
        self._text_size = 0

        # Skip tags that contain non‑visible content
        self._skip_tags = {"script", "style", "noscript"}
        self._skip_depth = 0

        # Use a dict to deduplicate while preserving insertion order
        self._links: Dict[str, None] = {}

    def handle_starttag(self, tag: str, attrs: List[tuple]) -> None:
        tag = tag.lower()

        # Track skip depth for script/style/noscript
        if tag in self._skip_tags:
            self._skip_depth += 1
            return

        # Enter title tag
        if tag == "title":
            self._in_title = True
            self._title_parts = []

        # Extract links only if we're not inside a skipped tag
        if self._skip_depth == 0 and tag == "a":
            for attr, value in attrs:
                if attr.lower() == "href" and value:
                    # Skip purely fragment anchors
                    if value.startswith("#"):
                        continue

                    # Resolve relative to absolute
                    resolved = urljoin(self.base_url, value)

                    # Only keep http/https schemes
                    parsed = urlparse(resolved)
                    if parsed.scheme in ("http", "https"):
                        self._links[resolved] = None

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()

        if tag in self._skip_tags:
            self._skip_depth -= 1
            return

        if tag == "title":
            self._in_title = False
            self.title = " ".join(self._title_parts).strip()

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data.strip())
            return

        # Skip data inside script/style blocks
        if self._skip_depth > 0:
            return

        stripped = data.strip()
        if not stripped:
            return

        # Enforce text size cap
        if self._text_size + len(stripped) > self.max_text_size:
            # Truncate to the limit
            remaining = self.max_text_size - self._text_size
            if remaining > 0:
                self._text_parts.append(stripped[:remaining])
                self._text_size = self.max_text_size
            return

        self._text_parts.append(stripped)
        self._text_size += len(stripped)

    def get_parsed_page(self) -> ParsedPage:
      full_text = " ".join(self._text_parts)
      # Guarantee the invariant: text <= max_text_size
      if len(full_text) > self.max_text_size:
          full_text = full_text[:self.max_text_size]
  
      return ParsedPage(
          url=self.base_url,
          title=self.title,
          text=full_text,
          links=list(self._links.keys()),
      )


def parse_html(url: str, html: str, max_text_size: int = 1_000_000) -> ParsedPage:
    """
    Parse HTML and return title, visible text, and absolute links.
    """
    parser = CrawlerHTMLParser(base_url=url, max_text_size=max_text_size)
    try:
        parser.feed(html)
    except Exception:
        # Malformed HTML should not crash the crawler
        pass
    return parser.get_parsed_page()