from ytfactory.config.settings import Settings
from ytfactory.providers.llm.factory import get_llm_provider
from ytfactory.providers.search.factory import get_search_provider

settings = Settings()

search = get_search_provider(settings)
results = search.search("History of Shivaji", max_results=3)

print(results[0].title)

llm = get_llm_provider(settings)

response = llm.generate("Say hello in one sentence.")

print(response.text)