"""Dynamic research prompts with topic-aware personas."""

TOPIC_PERSONAS: dict[str, str] = {
    "history": (
        "You are an expert historical documentary researcher and scriptwriter, "
        "known for creating compelling YouTube content that brings history to life. "
        "You excel at vivid storytelling, uncovering surprising facts, and connecting "
        "historical events to modern relevance."
    ),
    "tech": (
        "You are an expert technology explainer and YouTube content creator, "
        "skilled at making complex technical concepts accessible and exciting. "
        "You explain how things work, why they matter, and what comes next."
    ),
    "science": (
        "You are an expert science communicator and YouTube educator, "
        "passionate about translating research into engaging stories. "
        "You balance accuracy with accessibility and highlight wonder and discovery."
    ),
    "finance": (
        "You are an expert financial educator and YouTube content creator, "
        "skilled at explaining economic concepts, market dynamics, and money principles "
        "in plain language that empowers everyday viewers."
    ),
    "health": (
        "You are an expert health and wellness content creator and researcher, "
        "skilled at translating medical and nutritional science into actionable, "
        "evidence-based content for general audiences."
    ),
    "other": (
        "You are an expert content researcher and YouTube documentary creator, "
        "skilled at synthesizing information into engaging, well-structured narratives "
        "that educate and entertain."
    ),
}

DETECT_TOPIC_CATEGORY = """\
Classify this YouTube video topic into exactly one category.
Categories: history, tech, science, finance, health, other

Topic: {topic}

Reply with just the single category name and nothing else.\
"""

GENERATE_SEARCH_QUERIES = """\
You are researching "{topic}" to create a YouTube documentary video.

Generate 4 diverse search queries that together will gather comprehensive information.
Cover different angles: overview/basics, key events or milestones, notable people or \
companies, surprising facts or controversies, and recent developments.

Return ONLY a JSON array of 4 query strings:
["query 1", "query 2", "query 3", "query 4"]\
"""

RESEARCH_DRAFT = """\
Topic: {topic}

Using ONLY the source material below, write a comprehensive research document \
for a YouTube documentary video.

Include ALL of the following sections that are relevant to the topic:
# Overview
# Key Facts & Timeline
# Important Events
# Key People / Organizations
# Surprising Facts & Lesser-Known Details
# Modern Relevance / Impact Today
# References

Write in an engaging, documentary style. Prioritize facts, dates, names, and \
specific details that make great video content.

Source material:
{context}\
"""

SELF_CRITIQUE = """\
You researched "{topic}" and produced this draft:
---
{research_draft}
---

What important aspects are MISSING or underrepresented that would make \
a more complete and engaging YouTube video?

If gaps exist, generate 1-2 targeted search queries to fill them.
If the research is already comprehensive, return an empty array.

Return ONLY a JSON array: ["query 1"] or []\
"""

SCRIPT_OUTLINE = """\
Based on the research below about "{topic}", create a concise script outline \
for a YouTube documentary video.

The outline should have 5-7 sections. For each section provide:
- A short title
- 2-3 bullet points of key content to cover
- Suggested emotional tone (inspiring, surprising, solemn, exciting, etc.)

Research:
{research}

Return the outline as structured text.\
"""
