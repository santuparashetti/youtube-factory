from dataclasses import dataclass

from ytfactory.domain.search import SearchResult


@dataclass(slots=True)
class ResearchResult:
    topic: str
    markdown: str
    sources: list[SearchResult]