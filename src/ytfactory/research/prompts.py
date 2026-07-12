from video_core.domain.search import SearchResult


class PromptBuilder:
    def build(
        self,
        topic: str,
        sources: list[SearchResult],
    ) -> str:

        context = "\n\n".join(
            f"""
Title:
{item.title}

URL:
{item.url}

Content:
{item.content}
""".strip()
            for item in sources
        )

        return f"""
You are an expert historical researcher.

Research the following topic.

Topic:
{topic}

Use ONLY the information below.

{context}

Generate a detailed markdown document.

Include:

# Overview

# Timeline

# Important Events

# Key People

# Interesting Facts

# References
""".strip()
