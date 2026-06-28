from ytfactory.domain.search import SearchResult


class PromptBuilder:
    """Build prompts for the research agent."""

    def build(
        self,
        topic: str,
        sources: list[SearchResult],
    ) -> str:

        context = "\n\n".join(
            f"""
Title: {source.title}

URL: {source.url}

Content:
{source.content}
""".strip()
            for source in sources
        )

        return f"""
You are an expert YouTube researcher.

Research Topic:
{topic}

Use the following sources.

{context}

Generate markdown with:

# Overview

# Timeline

# Key Facts

# Important People

# Interesting Stories

# Statistics

# References
""".strip()