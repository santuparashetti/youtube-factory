from ytfactory.config.settings import Settings
from video_core.providers.search.base import SearchProvider
from video_core.providers.search.tavily import TavilySearchProvider


def get_search_provider(settings: Settings) -> SearchProvider:
    """Return the configured search provider."""

    match settings.search_provider.lower():
        case "tavily":
            return TavilySearchProvider(settings)

        case _:
            raise ValueError(f"Unsupported search provider: {settings.search_provider}")
