"""Tests for the search service and storage index."""

import sys
import os
import shutil
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.storage import Storage
from services.search_service import SearchService


class TestSearchService:
    """Tests for SearchService with a temporary storage directory."""

    def setup_method(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.storage = Storage(data_dir=self.tmp_dir)
        self.search = SearchService(self.storage)

    def teardown_method(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _index_page(self, url, origin, depth, words, title_words=None, heading_words=None):
        freq = {w: words.count(w) for w in set(words)}
        self.storage.add_to_index(
            words=freq,
            url=url,
            origin=origin,
            depth=depth,
            title_words=set(title_words or []),
            heading_words=set(heading_words or []),
        )

    def test_basic_search(self):
        self._index_page(
            "https://example.com",
            "https://example.com",
            0,
            ["hello", "world", "test"],
        )
        results = self.search.search("hello")
        assert len(results) >= 1
        assert results[0]["url"] == "https://example.com"

    def test_returns_triples(self):
        self._index_page(
            "https://example.com/page1",
            "https://example.com",
            1,
            ["python", "programming"],
        )
        results = self.search.search("python")
        assert len(results) >= 1
        r = results[0]
        assert "url" in r
        assert "origin" in r
        assert "depth" in r

    def test_scoring_formula(self):
        """Test the exact scoring formula: (freq * 10) + 1000 - (depth * 5)"""
        self._index_page(
            "https://example.com",
            "https://origin.com",
            2,
            ["python", "python", "python"],  # frequency = 3
        )
        results = self.search.search("python")
        assert len(results) == 1
        # score = (3 * 10) + 1000 - (2 * 5) = 30 + 1000 - 10 = 1020
        assert results[0]["relevance_score"] == 1020

    def test_shallower_pages_rank_higher(self):
        self._index_page(
            "https://deep.com",
            "https://origin.com",
            5,
            ["crawler"],
        )
        self._index_page(
            "https://shallow.com",
            "https://origin.com",
            0,
            ["crawler"],
        )
        results = self.search.search("crawler")
        assert len(results) == 2
        # shallow: (1*10)+1000-(0*5) = 1010
        # deep: (1*10)+1000-(5*5) = 985
        assert results[0]["url"] == "https://shallow.com"

    def test_multi_word_query(self):
        self._index_page(
            "https://both.com",
            "https://origin.com",
            0,
            ["web", "crawler", "tool"],
        )
        self._index_page(
            "https://partial.com",
            "https://origin.com",
            0,
            ["web", "design"],
        )
        results = self.search.search("web crawler")
        assert len(results) >= 1
        # Page matching both words should rank higher (2 x score vs 1)
        assert results[0]["url"] == "https://both.com"

    def test_no_results(self):
        self._index_page(
            "https://example.com",
            "https://example.com",
            0,
            ["hello"],
        )
        results = self.search.search("zzzznonexistent")
        assert len(results) == 0

    def test_empty_query(self):
        results = self.search.search("")
        assert len(results) == 0

    def test_frequency_affects_score(self):
        self._index_page(
            "https://frequent.com",
            "https://origin.com",
            0,
            ["python", "python", "python", "python", "python"],
        )
        self._index_page(
            "https://rare.com",
            "https://origin.com",
            0,
            ["python"],
        )
        results = self.search.search("python")
        assert len(results) == 2
        assert results[0]["url"] == "https://frequent.com"

    def test_limit_parameter(self):
        for i in range(10):
            self._index_page(
                f"https://example.com/page{i}",
                "https://example.com",
                0,
                ["common"],
            )
        results = self.search.search("common", limit=3)
        assert len(results) == 3


class TestStorageIndex:
    """Tests for Storage index sharding and persistence."""

    def setup_method(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.storage = Storage(data_dir=self.tmp_dir)

    def teardown_method(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_shard_by_first_letter(self):
        self.storage.add_to_index(
            words={"apple": 1},
            url="https://example.com",
            origin="https://example.com",
            depth=0,
        )
        shard_file = os.path.join(self.tmp_dir, "storage", "a.data")
        assert os.path.exists(shard_file)

    def test_non_alpha_shard(self):
        self.storage.add_to_index(
            words={"123test": 1},
            url="https://example.com",
            origin="https://example.com",
            depth=0,
        )
        shard_file = os.path.join(self.tmp_dir, "storage", "_.data")
        assert os.path.exists(shard_file)

    def test_data_format(self):
        """Test that data files use plain text format: word url origin depth frequency"""
        self.storage.add_to_index(
            words={"python": 3},
            url="https://example.com",
            origin="https://origin.com",
            depth=2,
        )
        shard_file = os.path.join(self.tmp_dir, "storage", "p.data")
        with open(shard_file, "r") as f:
            line = f.readline().strip()
        parts = line.split(" ")
        assert len(parts) == 5
        assert parts[0] == "python"
        assert parts[1] == "https://example.com"
        assert parts[2] == "https://origin.com"
        assert parts[3] == "2"
        assert parts[4] == "3"

    def test_visited_logging(self):
        self.storage.log_visited("https://example.com", "crawler1", 0)
        visited = self.storage.get_all_visited()
        assert len(visited) == 1
        assert visited[0]["url"] == "https://example.com"

    def test_crawler_state_persistence(self):
        state = {"crawler_id": "test1", "status": "running", "stats": {"pages_crawled": 5}}
        self.storage.save_crawler_state("test1", state)
        loaded = self.storage.load_crawler_state("test1")
        assert loaded is not None
        assert loaded["crawler_id"] == "test1"
        assert loaded["stats"]["pages_crawled"] == 5

    def test_list_crawler_states(self):
        self.storage.save_crawler_state("c1", {"crawler_id": "c1", "status": "completed"})
        self.storage.save_crawler_state("c2", {"crawler_id": "c2", "status": "running"})
        states = self.storage.list_crawler_states()
        assert len(states) == 2

    def test_index_stats(self):
        self.storage.add_to_index(
            words={"hello": 2, "world": 1},
            url="https://example.com",
            origin="https://example.com",
            depth=0,
        )
        stats = self.storage.get_index_stats()
        assert stats["total_entries"] == 2
        assert stats["shard_count"] >= 1
