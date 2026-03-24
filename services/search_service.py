"""
Search Service — Interface to the inverted index for searching.

Reads from disk on each query, so results reflect newly indexed
pages in near real-time even while crawlers are active.

Scoring formula: (frequency × 10) + 1000 (exact match bonus) - (depth × 5)
"""

import re
from core.storage import Storage


class SearchService:
    """
    Provides search capabilities over the crawled content index.
    """

    def __init__(self, storage: Storage) -> None:
        self.storage = storage

    def search(self, query: str, limit: int = 50, sort_by: str = "relevance") -> list[dict]:
        """
        Search for pages matching the query.

        Args:
            query: search string (space-separated terms)
            limit: maximum number of results
            sort_by: sort order ('relevance' by default)

        Returns:
            List of dicts: {url, origin, depth, relevance_score, frequency}
        """
        # Tokenize query
        words = self._tokenize_query(query)
        if not words:
            return []

        # Search the index
        results = self.storage.search_index(words)

        # Sort by relevance_score (default) or other criteria
        if sort_by == "relevance":
            results.sort(key=lambda x: x["relevance_score"], reverse=True)

        return results[:limit]

    def _tokenize_query(self, query: str) -> list[str]:
        """Tokenize a search query into lowercase words."""
        words = re.findall(r"[a-zA-ZğüşıöçĞÜŞİÖÇ]{2,}", query.lower())
        # Deduplicate while preserving order
        seen = set()
        unique = []
        for w in words:
            if w not in seen:
                seen.add(w)
                unique.append(w)
        return unique
