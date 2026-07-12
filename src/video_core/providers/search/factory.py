from video_core.config.shared_settings import SharedSettings
from video_core.providers.search.base import SearchProvider
from video_core.providers.search.tavily import TavilySearchProvider


def get_search_provider(settings: SharedSettings) -> SearchProvider:
    """Return the configured search provider."""

    match settings.search_provider.lower():
        case "tavily":
            return TavilySearchProvider(settings)

        case _:
            raise ValueError(f"Unsupported search provider: {settings.search_provider}")
