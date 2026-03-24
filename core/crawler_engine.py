"""
Crawler Engine — Multi-threaded BFS web crawler.

Uses stdlib threading + queue + urllib for the core crawl loop.
Features:
  - BFS traversal with depth tracking
  - Thread pool via concurrent.futures
  - Bounded queue for back pressure
  - Per-domain + global rate limiting
  - Pause / resume / stop controls
  - Periodic state checkpointing for resumability
"""

import queue
import ssl
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from core.html_parser import parse_html
from core.rate_limiter import DomainRateLimiter
from core.storage import Storage


# Default user agent
_USER_AGENT = (
    "Mozilla/5.0 (compatible; PythonCrawler/1.0; "
    "+https://github.com/crawler-demo)"
)

# HTTP timeout for fetching pages
_FETCH_TIMEOUT = 15

# How often to checkpoint state (seconds)
_CHECKPOINT_INTERVAL = 10


def _tokenize(text: str) -> dict[str, int]:
    """
    Tokenize text into word frequencies.
    Simple but effective: lowercase, split on non-alpha, filter short words.
    """
    import re
    words = re.findall(r"[a-zA-ZğüşıöçĞÜŞİÖÇ]{2,}", text.lower())
    freq: dict[str, int] = {}
    for w in words:
        freq[w] = freq.get(w, 0) + 1
    return freq


class CrawlerEngine:
    """
    Manages one crawl job: BFS from an origin URL to depth k.
    """

    def __init__(
        self,
        origin: str,
        max_depth: int,
        storage: Storage,
        rate_limiter: DomainRateLimiter,
        crawler_id: str | None = None,
        max_workers: int = 8,
        max_queue_size: int = 10000,
    ) -> None:
        self.crawler_id = crawler_id or str(uuid.uuid4())[:8]
        self.origin = origin
        self.max_depth = max_depth
        self.storage = storage
        self.rate_limiter = rate_limiter
        self.max_workers = max_workers
        self.max_queue_size = max_queue_size

        # BFS queue: items are (url, depth)
        self.url_queue: queue.Queue[tuple[str, int]] = queue.Queue(
            maxsize=max_queue_size
        )

        # Visited set (thread-safe via lock)
        self._visited: set[str] = set()
        self._visited_lock = threading.Lock()

        # Lifecycle control
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()  # Not paused initially

        # Statistics
        self.stats = {
            "pages_crawled": 0,
            "pages_errored": 0,
            "links_discovered": 0,
            "links_dropped": 0,
            "queue_high_water": 0,
        }
        self._stats_lock = threading.Lock()

        # Active worker tracking (in-flight requests)
        self._active_workers = 0
        self._active_lock = threading.Lock()

        # Pages per second tracking
        self._rate_window: list[float] = []  # timestamps of recent completions

        # State
        self.status = "created"  # created | running | paused | stopped | completed
        self.created_at = time.time()
        self.started_at: float | None = None
        self.finished_at: float | None = None
        self.errors: list[dict] = []

        # SSL context that doesn't verify (for broad crawling)
        self._ssl_ctx = ssl.create_default_context()
        self._ssl_ctx.check_hostname = False
        self._ssl_ctx.verify_mode = ssl.CERT_NONE

    # ── Public API ────────────────────────────────────────────

    def start(self) -> None:
        """Start the crawl in a background thread."""
        self.status = "running"
        self.started_at = time.time()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def pause(self) -> None:
        """Pause the crawl. Workers will block until resumed."""
        self._pause_event.clear()
        self.status = "paused"
        self._save_state()

    def resume(self) -> None:
        """Resume a paused crawl."""
        self._pause_event.set()
        self.status = "running"

    def stop(self) -> None:
        """Stop the crawl permanently."""
        self._stop_event.set()
        self._pause_event.set()  # Unblock paused workers
        self.status = "stopped"
        self.finished_at = time.time()
        self._save_state()

    def get_status(self) -> dict:
        """Return current crawler status for the API."""
        with self._stats_lock:
            stats_copy = dict(self.stats)

        with self._active_lock:
            active = self._active_workers

        raw_queue = self.url_queue.qsize()
        # Total pending = items in queue + items being processed by workers
        total_pending = raw_queue + active
        # Utilization based on total pending work vs capacity
        utilization = round(
            total_pending / max(self.max_queue_size, 1) * 100, 1
        )

        # Pages per second (rolling 30-second window)
        now = time.time()
        recent = [t for t in self._rate_window if now - t < 30]
        self._rate_window = recent
        pages_per_sec = round(len(recent) / min(30, max(now - (self.started_at or now), 1)), 2) if recent else 0.0

        return {
            "crawler_id": self.crawler_id,
            "origin": self.origin,
            "max_depth": self.max_depth,
            "status": self.status,
            "stats": stats_copy,
            "queue_size": raw_queue,
            "active_workers": active,
            "total_pending": total_pending,
            "max_queue_size": self.max_queue_size,
            "queue_utilization": utilization,
            "pages_per_sec": pages_per_sec,
            "visited_count": len(self._visited),
            "max_workers": self.max_workers,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "elapsed_seconds": round(
                (self.finished_at or time.time()) - (self.started_at or time.time()), 1
            ),
            "errors_count": len(self.errors),
            "recent_errors": self.errors[-5:],
        }

    # ── Internal crawl loop ───────────────────────────────────

    def _run(self) -> None:
        """Main crawl loop executed in a background thread."""
        # Seed the queue
        self.url_queue.put((self.origin, 0))

        last_checkpoint = time.monotonic()

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            active_futures = set()

            while not self._stop_event.is_set():
                # Periodic checkpoint
                if time.monotonic() - last_checkpoint > _CHECKPOINT_INTERVAL:
                    self._save_state()
                    last_checkpoint = time.monotonic()

                # Check if we're done
                if self.url_queue.empty() and not active_futures:
                    break

                # Wait if paused
                self._pause_event.wait()

                # Clean up completed futures
                done = {f for f in active_futures if f.done()}
                active_futures -= done
                
                with self._active_lock:
                    self._active_workers = len(active_futures)

                # Backpressure: Don't pull from url_queue if thread pool is busy
                if len(active_futures) >= self.max_workers * 2:
                    time.sleep(0.01)
                    continue

                try:
                    url, depth = self.url_queue.get(timeout=0.1)
                except queue.Empty:
                    continue

                # Check if already visited
                with self._visited_lock:
                    if url in self._visited:
                        continue
                    self._visited.add(url)

                # Submit to thread pool
                future = pool.submit(self._crawl_page, url, depth)
                active_futures.add(future)
                
                with self._active_lock:
                    self._active_workers = len(active_futures)

                # Update high water mark (queue + active)
                with self._stats_lock:
                    total = self.url_queue.qsize() + len(active_futures)
                    self.stats["queue_high_water"] = max(
                        self.stats["queue_high_water"], total
                    )

        if not self._stop_event.is_set():
            self.status = "completed"

        self.finished_at = time.time()
        self._save_state()

    def _crawl_page(self, url: str, depth: int) -> None:
        """Fetch and process a single page."""
        try:
            # Wait if paused
            self._pause_event.wait()
            if self._stop_event.is_set():
                return

            # Rate limit
            if not self.rate_limiter.acquire(url, timeout=30.0):
                self._record_error(url, "Rate limit timeout")
                return

            # Fetch
            html = self._fetch(url)
            if html is None:
                return

            # Parse
            result = parse_html(html, url)

            # Index the content
            self._index_page(url, depth, result)

            # Log visited
            self.storage.log_visited(url, self.crawler_id, depth)

            with self._stats_lock:
                self.stats["pages_crawled"] += 1

            # Track completion time for pages/sec
            self._rate_window.append(time.time())

            # Enqueue discovered links (if within depth limit)
            if depth < self.max_depth:
                for link in result["links"]:
                    # Only crawl same scheme (http/https)
                    link_parsed = urlparse(link)
                    if link_parsed.scheme not in ("http", "https"):
                        continue

                    with self._visited_lock:
                        if link in self._visited:
                            continue

                    with self._stats_lock:
                        self.stats["links_discovered"] += 1

                    try:
                        self.url_queue.put_nowait((link, depth + 1))
                    except queue.Full:
                        # Back pressure: queue is full, drop and record
                        with self._stats_lock:
                            self.stats["links_dropped"] += 1

        except Exception as e:
            self._record_error(url, str(e))

    def _fetch(self, url: str) -> str | None:
        """Fetch a URL and return its HTML content."""
        try:
            req = Request(url, headers={"User-Agent": _USER_AGENT})
            with urlopen(req, timeout=_FETCH_TIMEOUT, context=self._ssl_ctx) as resp:
                content_type = resp.headers.get("Content-Type", "")
                if "text/html" not in content_type and "text/plain" not in content_type:
                    return None
                charset = "utf-8"
                if "charset=" in content_type:
                    charset = content_type.split("charset=")[-1].split(";")[0].strip()
                raw = resp.read(5 * 1024 * 1024)  # Max 5MB
                return raw.decode(charset, errors="replace")
        except (URLError, HTTPError, OSError, ValueError) as e:
            self._record_error(url, str(e))
            return None

    def _index_page(self, url: str, depth: int, parsed: dict) -> None:
        """Tokenize page content and add to the inverted index."""
        text = parsed["text"]
        if not text:
            return

        words = _tokenize(text)
        if not words:
            return

        title_words = set(_tokenize(parsed.get("title", "")).keys())
        heading_text = " ".join(parsed.get("headings", []))
        heading_words = set(_tokenize(heading_text).keys())

        self.storage.add_to_index(
            words=words,
            url=url,
            origin=self.origin,
            depth=depth,
            title_words=title_words,
            heading_words=heading_words,
        )

    def _record_error(self, url: str, message: str) -> None:
        """Record an error for monitoring."""
        with self._stats_lock:
            self.stats["pages_errored"] += 1
        self.errors.append({
            "url": url,
            "error": message[:200],
            "timestamp": time.time(),
        })
        # Keep only last 100 errors
        if len(self.errors) > 100:
            self.errors = self.errors[-100:]

    # ── State persistence ─────────────────────────────────────

    def _save_state(self) -> None:
        """Save current state for resumability."""
        # Drain queue to list for saving
        queued_urls = []
        temp_items = []
        while not self.url_queue.empty():
            try:
                item = self.url_queue.get_nowait()
                temp_items.append(item)
                queued_urls.append({"url": item[0], "depth": item[1]})
            except queue.Empty:
                break
        # Put items back
        for item in temp_items:
            try:
                self.url_queue.put_nowait(item)
            except queue.Full:
                break

        with self._visited_lock:
            visited_list = list(self._visited)

        state = {
            "crawler_id": self.crawler_id,
            "origin": self.origin,
            "max_depth": self.max_depth,
            "status": self.status,
            "stats": dict(self.stats),
            "visited": visited_list,
            "queue": queued_urls[:1000],  # Save at most 1000 queued URLs
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "max_workers": self.max_workers,
            "max_queue_size": self.max_queue_size,
        }

        self.storage.save_crawler_state(self.crawler_id, state)

    def restore_from_state(self, state: dict) -> None:
        """Restore crawler from a saved state for resumability."""
        with self._visited_lock:
            self._visited = set(state.get("visited", []))

        self.stats = state.get("stats", self.stats)
        self.created_at = state.get("created_at", self.created_at)

        # Re-queue saved URLs
        for item in state.get("queue", []):
            try:
                self.url_queue.put_nowait((item["url"], item["depth"]))
            except queue.Full:
                break
