"""Research agent node — multi-query search, self-critique, auto-outline."""

from __future__ import annotations

import json
from dataclasses import asdict

from loguru import logger
from rich.console import Console
from rich.panel import Panel

from ytfactory.agents.prompts.research import (
    DETECT_TOPIC_CATEGORY,
    GENERATE_SEARCH_QUERIES,
    RESEARCH_DRAFT,
    SCRIPT_OUTLINE,
    SELF_CRITIQUE,
    TOPIC_PERSONAS,
)
from ytfactory.agents.state import VideoState
from ytfactory.config.settings import Settings
from video_core.providers.llm.factory import get_llm_provider
from ytfactory.providers.search.factory import get_search_provider
from ytfactory.storage.artifact_repository import ArtifactRepository
from ytfactory.storage.project_repository import ProjectRepository

console = Console()


def _parse_json_list(text: str, default: list) -> list:
    """Extract a JSON array from LLM response, tolerating markdown fences."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        result = json.loads(text)
        return result if isinstance(result, list) else default
    except json.JSONDecodeError:
        return default


def _parse_category(raw: str) -> str:
    valid = {"history", "tech", "science", "finance", "health", "other"}
    for token in raw.lower().split():
        if token in valid:
            return token
    return "other"


_MAX_SOURCES_PER_PROMPT = 12
_MAX_CHARS_PER_SOURCE = 1200


def _format_sources(results: list) -> str:
    parts = []
    for i, r in enumerate(results[:_MAX_SOURCES_PER_PROMPT], 1):
        content = r.content
        if len(content) > _MAX_CHARS_PER_SOURCE:
            content = content[:_MAX_CHARS_PER_SOURCE] + "…"
        parts.append(f"[Source {i}] {r.title}\nURL: {r.url}\n{content}\n")
    return "\n---\n".join(parts)


def research_node(state: VideoState) -> dict:
    """
    Research agent:
    1. Detect topic category → select expert persona
    2. Generate 4 diverse search queries
    3. Execute searches, deduplicate by URL
    4. Draft research with self-critique loop
    5. Generate script outline
    """
    settings = Settings()
    llm = get_llm_provider(settings)
    search = get_search_provider(settings)
    artifact_repo = ArtifactRepository()
    project_repo = ProjectRepository()

    topic = state["topic"]
    project_id = state["project_id"]

    project_repo.update_stage(project_id, "research", "running")
    console.print(
        f"\n[bold cyan]🔬 Research Agent[/bold cyan] — topic: [italic]{topic}[/italic]\n"
    )

    # ── Step 1: Detect topic category ────────────────────────────────────
    category_response = llm.generate(DETECT_TOPIC_CATEGORY.format(topic=topic))
    category = _parse_category(category_response.text)
    persona = TOPIC_PERSONAS.get(category, TOPIC_PERSONAS["other"])
    console.print(f"  [green]✓[/green] Category detected: [bold]{category}[/bold]")

    # ── Step 2: Generate diverse search queries ───────────────────────────
    queries_response = llm.generate(GENERATE_SEARCH_QUERIES.format(topic=topic))
    queries = _parse_json_list(queries_response.text, default=[topic])
    console.print(f"  [green]✓[/green] Generated {len(queries)} search queries")

    # ── Step 3: Execute searches (deduplicated) ───────────────────────────
    all_results = []
    seen_urls: set[str] = set()

    for query in queries[:4]:
        try:
            results = search.search(query, max_results=5)
            for r in results:
                if r.url not in seen_urls:
                    seen_urls.add(r.url)
                    all_results.append(r)
        except Exception as exc:
            logger.warning("Search failed for query '{}': {}", query, exc)

    console.print(f"  [green]✓[/green] Collected {len(all_results)} unique sources")

    # ── Step 4: Generate research draft ──────────────────────────────────
    draft_response = llm.generate(
        RESEARCH_DRAFT.format(topic=topic, context=_format_sources(all_results)),
        system_prompt=persona,
        temperature=0.3,
    )
    research_md = draft_response.text

    # ── Step 5: Self-critique loop ────────────────────────────────────────
    critique_response = llm.generate(
        SELF_CRITIQUE.format(topic=topic, research_draft=research_md)
    )
    gap_queries = _parse_json_list(critique_response.text, default=[])

    if gap_queries:
        console.print(
            f"  [yellow]→[/yellow] Self-critique found gaps, running {len(gap_queries)} follow-up searches"
        )
        for query in gap_queries[:2]:
            try:
                results = search.search(query, max_results=4)
                for r in results:
                    if r.url not in seen_urls:
                        seen_urls.add(r.url)
                        all_results.append(r)
            except Exception as exc:
                logger.warning("Follow-up search failed: {}", exc)

        # Regenerate with fuller context
        final_response = llm.generate(
            RESEARCH_DRAFT.format(topic=topic, context=_format_sources(all_results)),
            system_prompt=persona,
            temperature=0.3,
        )
        research_md = final_response.text
        console.print(
            f"  [green]✓[/green] Research enriched to {len(all_results)} sources"
        )

    # ── Step 6: Generate script outline ──────────────────────────────────
    outline_response = llm.generate(
        SCRIPT_OUTLINE.format(topic=topic, research=research_md),
        system_prompt=persona,
    )
    script_outline = outline_response.text

    # ── Persist artifacts ─────────────────────────────────────────────────
    artifact_repo.write_markdown(project_id, "research", "research.md", research_md)
    artifact_repo.write_json(
        project_id,
        "research",
        "research.json",
        {"topic": topic, "category": category, "markdown": research_md},
    )
    artifact_repo.write_json(
        project_id,
        "research",
        "sources.json",
        [asdict(r) for r in all_results],
    )
    artifact_repo.write_markdown(
        project_id, "research", "script_outline.md", script_outline
    )

    project_repo.update_stage(project_id, "research", "completed")
    console.print(
        Panel(
            f"[green]Research complete[/green] — {len(research_md.split())} words, "
            f"{len(all_results)} sources, outline saved",
            title="Research Agent",
            border_style="green",
        )
    )

    return {
        "topic_category": category,
        "research_md": research_md,
    }
