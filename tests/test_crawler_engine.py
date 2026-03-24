"""Tests for the crawler engine."""

import sys
import os
import time
import shutil
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.crawler_engine import CrawlerEngine, _tokenize
from core.rate_limiter import DomainRateLimiter
from core.storage import Storage


class TestTokenize:
    """Tests for the _tokenize function."""

    def test_basic_tokenize(self):
        result = _tokenize("Hello World test")
        assert "hello" in result
        assert "world" in result
        assert "test" in result

    def test_frequency_counting(self):
        result = _tokenize("hello hello hello world")
        assert result["hello"] == 3
        assert result["world"] == 1

    def test_filters_short_words(self):
        result = _tokenize("I a to be or not go")
        # Single-letter words should be filtered
        assert "i" not in result
        assert "a" not in result

    def test_handles_empty_string(self):
        result = _tokenize("")
        assert len(result) == 0

    def test_handles_special_chars(self):
        result = _tokenize("hello! world? test@#$%")
        assert "hello" in result
        assert "world" in result
        assert "test" in result


class TestCrawlerEngine:
    """Tests for CrawlerEngine creation and status."""

    def setup_method(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.storage = Storage(data_dir=self.tmp_dir)
        self.rate_limiter = DomainRateLimiter(
            global_rate=100.0, global_capacity=100,
            domain_rate=100.0, domain_capacity=100,
        )

    def teardown_method(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_create_engine(self):
        engine = CrawlerEngine(
            origin="https://example.com",
            max_depth=2,
            storage=self.storage,
            rate_limiter=self.rate_limiter,
        )
        assert engine.origin == "https://example.com"
        assert engine.max_depth == 2
        assert engine.status == "created"

    def test_get_status(self):
        engine = CrawlerEngine(
            origin="https://example.com",
            max_depth=2,
            storage=self.storage,
            rate_limiter=self.rate_limiter,
        )
        status = engine.get_status()
        assert status["origin"] == "https://example.com"
        assert status["max_depth"] == 2
        assert status["status"] == "created"
        assert "stats" in status
        assert "queue_size" in status

    def test_queue_bounded(self):
        engine = CrawlerEngine(
            origin="https://example.com",
            max_depth=2,
            storage=self.storage,
            rate_limiter=self.rate_limiter,
            max_queue_size=5,
        )
        assert engine.max_queue_size == 5
        assert engine.url_queue.maxsize == 5

    def test_save_and_restore_state(self):
        engine = CrawlerEngine(
            origin="https://example.com",
            max_depth=3,
            storage=self.storage,
            rate_limiter=self.rate_limiter,
            crawler_id="test123",
        )
        engine._visited.add("https://example.com/page1")
        engine._visited.add("https://example.com/page2")
        engine.stats["pages_crawled"] = 10
        engine._save_state()

        # Load state
        state = self.storage.load_crawler_state("test123")
        assert state is not None
        assert len(state["visited"]) == 2
        assert state["stats"]["pages_crawled"] == 10

    def test_stop_engine(self):
        engine = CrawlerEngine(
            origin="https://example.com",
            max_depth=1,
            storage=self.storage,
            rate_limiter=self.rate_limiter,
        )
        engine.start()
        time.sleep(0.5)
        engine.stop()
        assert engine.status == "stopped"

    def test_pause_resume(self):
        engine = CrawlerEngine(
            origin="https://example.com",
            max_depth=0,
            storage=self.storage,
            rate_limiter=self.rate_limiter,
        )
        engine.start()
        time.sleep(0.2)
        engine.pause()
        assert engine.status == "paused"
        engine.resume()
        assert engine.status == "running"
        engine.stop()
