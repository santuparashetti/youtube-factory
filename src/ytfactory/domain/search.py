from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class SearchResult:
    """Normalized search result returned by any search provider."""

    title: str
    url: str
    snippet: str
    content: str

    source: str
    score: float

    published_at: datetime | None = None