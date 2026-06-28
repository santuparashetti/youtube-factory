from ytfactory.config.settings import Settings
from ytfactory.providers.search.base import SearchProvider
from ytfactory.providers.search.tavily import TavilySearchProvider


def get_search_provider(settings: Settings) -> SearchProvider:

    match settings.search_provider.lower():
        case "tavily":
            return TavilySearchProvider(settings)

        case _:
            raise ValueError(
                f"Unsupported search provider: {settings.search_provider}"
            )