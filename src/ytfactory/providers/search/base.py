from abc import ABC, abstractmethod

from ytfactory.domain.search import SearchResult


class SearchProvider(ABC):
    """Base interface for all search providers."""

    @abstractmethod
    def search(
        self,
        query: str,
        *,
        max_results: int = 10,
    ) -> list[SearchResult]:
        """Search the web and return normalized results."""
        raise NotImplementedError
