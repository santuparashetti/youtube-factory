from ytfactory.domain.llm import LLMResponse
from ytfactory.providers.llm.base import LLMProvider
from ytfactory.providers.search.base import SearchProvider
from ytfactory.research.models import ResearchRequest, ResearchResult
from ytfactory.research.prompt_builder import PromptBuilder


class ResearchPipeline:
    """Coordinates the complete research workflow."""

    def __init__(
        self,
        search_provider: SearchProvider,
        llm_provider: LLMProvider,
    ):
        self.search = search_provider
        self.llm = llm_provider
        self.prompts = PromptBuilder()

    def run(
        self,
        request: ResearchRequest,
    ) -> ResearchResult:

        sources = self.search.search(
            request.topic,
            max_results=request.max_sources,
        )

        prompt = self.prompts.build(
            request.topic,
            sources,
        )

        response: LLMResponse = self.llm.generate(prompt)

        return ResearchResult(
            topic=request.topic,
            markdown=response.text,
            sources=sources,
        )