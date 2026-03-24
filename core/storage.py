"""
Storage Layer — File-based persistence for the crawler.

All data is stored as plain files in the data/ directory.
Designed for crash safety with append-only writes and atomic state saves.

Directory layout:
    data/
    ├── storage/         # Inverted word index, sharded by first letter
    │   ├── a.data
    │   ├── b.data
    │   └── ...
    ├── crawlers/        # Per-crawler state files
    │   └── {id}.json
    └── visited.jsonl    # Global visited URL log
"""

import json
import os
import threading
import time
from pathlib import Path


class Storage:
    """Thread-safe file-based storage for the crawler system."""

    def __init__(self, data_dir: str = "data") -> None:
        self.data_dir = Path(data_dir)
        self.storage_dir = self.data_dir / "storage"
        self.crawlers_dir = self.data_dir / "crawlers"
        self.visited_file = self.data_dir / "visited.jsonl"

        # Create directories
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.crawlers_dir.mkdir(parents=True, exist_ok=True)

        # Locks for thread-safe writes
        self._index_locks: dict[str, threading.Lock] = {}
        self._index_locks_lock = threading.Lock()
        self._visited_lock = threading.Lock()
        self._crawler_lock = threading.Lock()

    # ── Index operations ──────────────────────────────────────

    def _get_shard(self, word: str) -> str:
        """Determine which shard file a word belongs to."""
        ch = word[0].lower() if word else "_"
        return ch if ch.isalpha() else "_"

    def _get_index_lock(self, shard: str) -> threading.Lock:
        """Get or create a lock for a specific index shard."""
        with self._index_locks_lock:
            if shard not in self._index_locks:
                self._index_locks[shard] = threading.Lock()
            return self._index_locks[shard]

    def add_to_index(
        self,
        words: dict[str, int],
        url: str,
        origin: str,
        depth: int,
        title_words: set[str] | None = None,
        heading_words: set[str] | None = None,
    ) -> None:
        """
        Add word frequencies for a page to the inverted index.

        Each line in the .data file is: word url origin depth frequency
        (space-separated plain text)
        """
        title_words = title_words or set()
        heading_words = heading_words or set()

        # Group words by shard to minimize file operations
        shards: dict[str, list[str]] = {}
        for word, freq in words.items():
            shard = self._get_shard(word)
            # Format: word url origin depth frequency
            line = f"{word} {url} {origin} {depth} {freq}\n"
            shards.setdefault(shard, []).append(line)

        # Write each shard
        for shard, lines in shards.items():
            lock = self._get_index_lock(shard)
            shard_file = self.storage_dir / f"{shard}.data"
            with lock:
                with open(shard_file, "a", encoding="utf-8") as f:
                    f.writelines(lines)

    def search_index(self, query_words: list[str]) -> list[dict]:
        """
        Search the inverted index for pages matching query words.

        Scoring formula: (frequency × 10) + 1000 (exact match) - (depth × 5)

        Returns a list of dicts with url, origin, depth, and relevance_score.
        """
        # Collect matching entries from relevant shards
        matches: dict[str, dict] = {}  # url -> aggregated info

        for word in query_words:
            shard = self._get_shard(word)
            shard_file = self.storage_dir / f"{shard}.data"

            if not shard_file.exists():
                continue

            lock = self._get_index_lock(shard)
            with lock:
                with open(shard_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue

                        # Parse: word url origin depth frequency
                        parts = line.split(" ")
                        if len(parts) < 5:
                            continue

                        entry_word = parts[0]
                        entry_url = parts[1]
                        entry_origin = parts[2]
                        try:
                            entry_depth = int(parts[3])
                            entry_freq = int(parts[4])
                        except ValueError:
                            continue

                        # Check if this entry's word matches
                        if entry_word != word:
                            continue

                        # Score = (frequency × 10) + 1000 - (depth × 5)
                        score = (entry_freq * 10) + 1000 - (entry_depth * 5)

                        if entry_url not in matches:
                            matches[entry_url] = {
                                "url": entry_url,
                                "origin": entry_origin,
                                "depth": entry_depth,
                                "relevance_score": score,
                                "frequency": entry_freq,
                            }
                        else:
                            # Aggregate: add scores for multiple word matches
                            matches[entry_url]["relevance_score"] += score

        # Convert to list and sort by relevance_score
        results = list(matches.values())
        results.sort(key=lambda x: x["relevance_score"], reverse=True)
        return results

    # ── Visited URL tracking ──────────────────────────────────

    def log_visited(self, url: str, crawler_id: str, depth: int) -> None:
        """Append a visited URL to the global log."""
        entry = {
            "url": url,
            "crawler_id": crawler_id,
            "depth": depth,
            "timestamp": time.time(),
        }
        with self._visited_lock:
            with open(self.visited_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def get_all_visited(self) -> list[dict]:
        """Read all visited URL entries."""
        entries = []
        if not self.visited_file.exists():
            return entries
        with self._visited_lock:
            with open(self.visited_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            entries.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
        return entries

    # ── Crawler state persistence ─────────────────────────────

    def save_crawler_state(self, crawler_id: str, state: dict) -> None:
        """Atomically save crawler state to disk."""
        state_file = self.crawlers_dir / f"{crawler_id}.json"
        tmp_file = self.crawlers_dir / f"{crawler_id}.json.tmp"

        with self._crawler_lock:
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
            # Atomic rename
            tmp_file.replace(state_file)

    def load_crawler_state(self, crawler_id: str) -> dict | None:
        """Load crawler state from disk. Returns None if not found."""
        state_file = self.crawlers_dir / f"{crawler_id}.json"
        if not state_file.exists():
            return None
        with self._crawler_lock:
            with open(state_file, "r", encoding="utf-8") as f:
                return json.load(f)

    def list_crawler_states(self) -> list[dict]:
        """List all saved crawler states."""
        states = []
        with self._crawler_lock:
            for f in self.crawlers_dir.glob("*.json"):
                if f.name.endswith(".tmp"):
                    continue
                try:
                    with open(f, "r", encoding="utf-8") as fh:
                        states.append(json.load(fh))
                except (json.JSONDecodeError, OSError):
                    continue
        return states

    def get_index_stats(self) -> dict:
        """Return statistics about the index."""
        total_entries = 0
        shard_count = 0

        for f in self.storage_dir.glob("*.data"):
            shard_count += 1
            with open(f, "r", encoding="utf-8") as fh:
                total_entries += sum(1 for line in fh if line.strip())

        return {
            "total_entries": total_entries,
            "shard_count": shard_count,
        }

    def clear_all(self) -> None:
        """Clear all stored data. Use with caution."""
        import shutil
        if self.data_dir.exists():
            shutil.rmtree(self.data_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.crawlers_dir.mkdir(parents=True, exist_ok=True)
