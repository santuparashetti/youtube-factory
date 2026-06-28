from loguru import logger
from tavily import TavilyClient
from tenacity import retry, stop_after_attempt, wait_exponential

from ytfactory.config.settings import Settings
from ytfactory.domain.search import SearchResult
from ytfactory.providers.search.base import SearchProvider


class TavilySearchProvider(SearchProvider):
    """Tavily Search implementation."""

    def __init__(self, settings: Settings):
        self._client = TavilyClient(api_key=settings.tavily_api_key)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def search(
        self,
        query: str,
        *,
        max_results: int = 10,
    ) -> list[SearchResult]:

        logger.info(f"Searching Tavily: {query}")

        response = self._client.search(
            query=query,
            max_results=max_results,
            include_raw_content=True,
        )

        results: list[SearchResult] = []

        for item in response.get("results", []):

            results.append(
                SearchResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    snippet=item.get("content", ""),
                    content=item.get("raw_content") or item.get("content", ""),
                    source="tavily",
                    score=float(item.get("score", 0.0)),
                )
            )

        return results