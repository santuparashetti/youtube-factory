from dataclasses import asdict

from ytfactory.config.settings import Settings
from video_core.providers.llm.factory import get_llm_provider
from video_core.providers.search.factory import get_search_provider
from ytfactory.research.models import ResearchResult
from ytfactory.research.prompts import PromptBuilder
from ytfactory.storage.artifact_repository import ArtifactRepository
from ytfactory.storage.project_repository import ProjectRepository


class ResearchPipeline:
    def __init__(self):

        settings = Settings()

        self.project_repo = ProjectRepository()

        self.artifact_repo = ArtifactRepository()

        self.search = get_search_provider(settings)

        self.llm = get_llm_provider(settings)

        self.prompts = PromptBuilder()

    def run(
        self,
        project_id: str,
    ) -> None:

        project = self.project_repo.load(project_id)

        self.project_repo.update_stage(
            project_id,
            "research",
            "running",
        )

        sources = self.search.search(
            project.title,
            max_results=5,
        )

        prompt = self.prompts.build(
            project.title,
            sources,
        )

        response = self.llm.generate(prompt)

        result = ResearchResult(
            topic=project.title,
            markdown=response.text,
            sources=sources,
        )

        self.artifact_repo.write_markdown(
            project_id,
            "research",
            "research.md",
            result.markdown,
        )

        self.artifact_repo.write_json(
            project_id,
            "research",
            "research.json",
            {
                "topic": result.topic,
                "markdown": result.markdown,
            },
        )

        self.artifact_repo.write_json(
            project_id,
            "research",
            "sources.json",
            [asdict(s) for s in result.sources],
        )

        self.project_repo.update_stage(
            project_id,
            "research",
            "completed",
        )
