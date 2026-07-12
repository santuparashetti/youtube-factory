from dataclasses import dataclass

from video_core.domain.search import SearchResult


@dataclass(slots=True)
class ResearchResult:
    topic: str
    markdown: str
    sources: list[SearchResult]
