from rich.console import Console

from ytfactory.research.models import ResearchRequest
from ytfactory.research.service import ResearchService

console = Console()


def research(topic: str) -> None:
    """Generate research for a topic."""

    service = ResearchService()

    result = service.run(
        ResearchRequest(topic=topic)
    )

    console.print(result.markdown)