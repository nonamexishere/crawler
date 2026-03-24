"""
Crawler Service — Manages the lifecycle of multiple crawler instances.

This is the orchestration layer between the API and the crawler engine.
"""

import threading
from core.crawler_engine import CrawlerEngine
from core.rate_limiter import DomainRateLimiter
from core.storage import Storage


class CrawlerService:
    """
    Manages all crawler instances. Provides methods to create,
    control, and query crawlers.
    """

    def __init__(self, storage: Storage, rate_limiter: DomainRateLimiter) -> None:
        self.storage = storage
        self.rate_limiter = rate_limiter
        self._crawlers: dict[str, CrawlerEngine] = {}
        self._lock = threading.Lock()

        # Try to load previously saved crawler states
        self._load_previous_states()

    def _load_previous_states(self) -> None:
        """Load crawler states from disk for the status display."""
        for state in self.storage.list_crawler_states():
            cid = state.get("crawler_id")
            status = state.get("status", "")
            if cid and status in ("completed", "stopped"):
                # Create a placeholder engine for status display
                engine = CrawlerEngine(
                    origin=state["origin"],
                    max_depth=state["max_depth"],
                    storage=self.storage,
                    rate_limiter=self.rate_limiter,
                    crawler_id=cid,
                    max_workers=state.get("max_workers", 8),
                    max_queue_size=state.get("max_queue_size", 10000),
                )
                engine.status = status
                engine.stats = state.get("stats", engine.stats)
                engine.created_at = state.get("created_at", engine.created_at)
                engine.started_at = state.get("started_at")
                engine.finished_at = state.get("finished_at")
                with self._lock:
                    self._crawlers[cid] = engine

    def create_crawler(
        self,
        origin: str,
        max_depth: int = 2,
        max_workers: int = 8,
        max_queue_size: int = 10000,
    ) -> CrawlerEngine:
        """Create and start a new crawler."""
        engine = CrawlerEngine(
            origin=origin,
            max_depth=max_depth,
            storage=self.storage,
            rate_limiter=self.rate_limiter,
            max_workers=max_workers,
            max_queue_size=max_queue_size,
        )

        with self._lock:
            self._crawlers[engine.crawler_id] = engine

        engine.start()
        return engine

    def resume_crawler(self, crawler_id: str) -> CrawlerEngine | None:
        """Resume a previously interrupted crawler from saved state."""
        state = self.storage.load_crawler_state(crawler_id)
        if not state:
            return None

        if state.get("status") in ("completed", "stopped"):
            return None  # Can't resume finished crawlers

        engine = CrawlerEngine(
            origin=state["origin"],
            max_depth=state["max_depth"],
            storage=self.storage,
            rate_limiter=self.rate_limiter,
            crawler_id=crawler_id,
            max_workers=state.get("max_workers", 8),
            max_queue_size=state.get("max_queue_size", 10000),
        )
        engine.restore_from_state(state)

        with self._lock:
            self._crawlers[crawler_id] = engine

        engine.start()
        return engine

    def get_crawler(self, crawler_id: str) -> CrawlerEngine | None:
        """Get a crawler by ID."""
        with self._lock:
            return self._crawlers.get(crawler_id)

    def list_crawlers(self) -> list[dict]:
        """Get status of all crawlers."""
        with self._lock:
            crawlers = list(self._crawlers.values())

        return [c.get_status() for c in crawlers]

    def pause_crawler(self, crawler_id: str) -> bool:
        """Pause a running crawler."""
        crawler = self.get_crawler(crawler_id)
        if crawler and crawler.status == "running":
            crawler.pause()
            return True
        return False

    def resume_running_crawler(self, crawler_id: str) -> bool:
        """Resume a paused crawler."""
        crawler = self.get_crawler(crawler_id)
        if crawler and crawler.status == "paused":
            crawler.resume()
            return True
        return False

    def stop_crawler(self, crawler_id: str) -> bool:
        """Stop a crawler permanently."""
        crawler = self.get_crawler(crawler_id)
        if crawler and crawler.status in ("running", "paused"):
            crawler.stop()
            return True
        return False

    def get_system_status(self) -> dict:
        """Get overall system status including rate limiter info."""
        crawlers = self.list_crawlers()
        active = sum(1 for c in crawlers if c["status"] == "running")
        paused = sum(1 for c in crawlers if c["status"] == "paused")

        return {
            "total_crawlers": len(crawlers),
            "active_crawlers": active,
            "paused_crawlers": paused,
            "rate_limiter": self.rate_limiter.get_status(),
            "index_stats": self.storage.get_index_stats(),
        }
