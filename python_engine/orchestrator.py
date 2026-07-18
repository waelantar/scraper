# python_engine/orchestrator.py
import threading
import logging
import time
from typing import List, Optional, Set, Callable, Dict
from urllib.parse import urlparse

from python_engine.bounded_queue import BoundedQueue
from python_engine.thread_pool import ThreadPool
from python_engine.fetcher import fetch, FetchResult
from python_engine.parser import parse_html, ParsedPage
from python_engine.cache import PageCache

logger = logging.getLogger(__name__)


class Crawler:
    """
    Orchestrator that wires fetcher, parser, and cache together.

    - Starts with seed URLs.
    - Uses a thread pool for parallel fetching.
    - Detects termination when all URLs are processed and no new ones are found.
    - Handles KeyboardInterrupt for graceful shutdown.
    """

    def __init__(
        self,
        seed_urls: List[str],
        db_path: str = "crawler.db",
        num_workers: int = 4,
        max_depth: Optional[int] = None,
        same_domain: bool = True,
        max_urls: Optional[int] = None,
        fetch_fn: Callable[[str], FetchResult] = fetch,
    ):
        """
        Args:
            seed_urls: Initial URLs to crawl.
            db_path: Path to SQLite database.
            num_workers: Number of worker threads.
            max_depth: Maximum crawl depth (None = unlimited).
            same_domain: If True, only crawl URLs from the same domain as seeds.
            max_urls: Maximum URLs to crawl (None = unlimited).
            fetch_fn: Function to fetch a URL (dependency injection for testing).
        """
        self.seed_urls = list(seed_urls)
        self.num_workers = num_workers
        self.max_depth = max_depth
        self.same_domain = same_domain
        self.max_urls = max_urls
        self.fetch_fn = fetch_fn

        # Components
        self.cache = PageCache(db_path)
        self.url_queue = BoundedQueue(maxsize=None)  # unbounded
        self.pool = ThreadPool(num_workers=num_workers)

        # Termination detection
        self._active_tasks = 0
        self._active_cond = threading.Condition()
        self._shutdown_event = threading.Event()
        self._shutdown_done = False

        # Track visited URLs to avoid duplicates in the queue
        self._visited: Set[str] = set()

        # Track depth per URL
        self._depth: Dict[str, int] = {}

        # Domain filter
        self._seed_domain = None
        if same_domain and seed_urls:
            parsed = urlparse(seed_urls[0])
            self._seed_domain = parsed.netloc

        # Statistics
        self._attempted = 0         # URLs reserved for processing (used for max_urls)
        self.crawled_count = 0      # URLs successfully fetched + parsed
        self.error_count = 0        # URLs that failed during fetch/parse

    def crawl(self) -> None:
        """Start the crawling process and block until complete."""
        try:
            self._start_workers()
            self._seed_initial_urls()
            self._wait_for_completion()
        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt received – shutting down gracefully")
        finally:
            self.shutdown()

    def _seed_initial_urls(self) -> None:
        """Add seed URLs to the queue."""
        for url in self.seed_urls:
            self._enqueue_url(url, depth=0)

    def _start_workers(self) -> None:
        """Start worker threads that process URLs from the queue."""
        for _ in range(self.num_workers):
            self.pool.submit(self._worker_loop)

    def _worker_loop(self) -> None:
        """
        Main worker logic:
        1. Get a URL from the queue.
        2. Fetch it.
        3. Parse it.
        4. Store it.
        5. Enqueue new links.
        """
        while not self._shutdown_event.is_set():
            try:
                # Block until a URL is available or queue shuts down
                url, depth = self.url_queue.get()
            except RuntimeError:
                # Queue was shut down – exit gracefully
                break

            # Reserve and validate under lock
            with self._active_cond:
                if url in self._visited:
                    self._task_done_locked()
                    continue
                if self.max_urls is not None and self._attempted >= self.max_urls:
                    self._task_done_locked()
                    continue
                # Mark visited and increment attempted count
                self._visited.add(url)
                self._attempted += 1

            try:
                self._process_url(url, depth)
            except Exception as e:
                logger.error(f"Error processing {url}: {e}", exc_info=True)
                with self._active_cond:
                    self.error_count += 1
            finally:
                with self._active_cond:
                    self._task_done_locked()

    def _process_url(self, url: str, depth: int) -> None:
        """
        Fetch, parse, and store a single URL.
        Enqueues new links if within depth limit.
        """
        # 1. Check cache (idempotent)
        if self.cache.has(url):
            return

        # 2. Fetch
        fetch_result = self.fetch_fn(url)
        if fetch_result.status_code != 200 or fetch_result.html is None:
            # Store the failure (so we don't retry)
            failed_page = ParsedPage(url=url, title="", text="", links=[])
            self.cache.put(failed_page, status_code=fetch_result.status_code)
            with self._active_cond:
                self.error_count += 1
            logger.debug(f"Failed to fetch {url}: {fetch_result.error}")
            return

        # 3. Parse
        parsed = parse_html(url, fetch_result.html)

        # 4. Store in cache (with status code from fetch)
        self.cache.put(parsed, status_code=fetch_result.status_code)
        with self._active_cond:
            self.crawled_count += 1
        logger.info(f"Crawled {url} (depth {depth}) - {len(parsed.links)} links found")

        # 5. Enqueue new links
        if self.max_depth is None or depth < self.max_depth:
            for link in parsed.links:
                # Domain filter
                if self.same_domain and self._seed_domain:
                    parsed_link = urlparse(link)
                    if parsed_link.netloc != self._seed_domain:
                        continue
                self._enqueue_url(link, depth=depth + 1)

    def _enqueue_url(self, url: str, depth: int) -> None:
        """
        Add a URL to the queue if not already visited.
        Thread-safe: called from multiple workers.
        """
        with self._active_cond:
            if url in self._visited:
                return
            # Track depth
            self._depth[url] = depth
            # Increment active tasks BEFORE putting to prevent premature termination
            self._active_tasks += 1
            # NOTE: url_queue is unbounded, so put() never blocks.
            # If we later bound the frontier, we must not hold _active_cond
            # across a blocking put() to avoid deadlock with shutdown().
            self.url_queue.put((url, depth))

    def _task_done_locked(self) -> None:
        """Called when a task finishes (success or failure)."""
        self._active_tasks -= 1
        if self._active_tasks == 0:
            self._active_cond.notify_all()

    def _wait_for_completion(self) -> None:
        """
        Block until all work is complete:
        - No active tasks (including tasks in the queue).
        """
        with self._active_cond:
            while self._active_tasks != 0 and not self._shutdown_event.is_set():
                self._active_cond.wait(timeout=0.5)
        logger.info("All tasks complete")

    def shutdown(self) -> None:
        """
        Gracefully shut down the crawler:
        1. Signal workers to stop.
        2. Close the URL queue (wakes blocked workers).
        3. Shut down the thread pool.
        4. Close the database.
        """
        # Idempotent guard
        with self._active_cond:
            if self._shutdown_done:
                return
            self._shutdown_done = True

        logger.info("Shutting down crawler...")

        # Signal workers to stop accepting new tasks
        self._shutdown_event.set()

        # Close the URL queue to wake blocked workers
        self.url_queue.shutdown()

        # Wait for the thread pool to finish
        self.pool.shutdown(wait=True, timeout=5.0)

        # Close database
        self.cache.close()

        with self._active_cond:
            logger.info(
                f"Crawler shut down. Attempted: {self._attempted}, "
                f"Crawled: {self.crawled_count}, Errors: {self.error_count}"
            )

    def get_stats(self) -> dict:
        """Return current statistics."""
        with self._active_cond:
            return {
                "attempted": self._attempted,
                "crawled": self.crawled_count,
                "errors": self.error_count,
                "visited": len(self._visited),
                "queue_size": len(self.url_queue),
                "active_tasks": self._active_tasks,
            }