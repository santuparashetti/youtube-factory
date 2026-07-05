"""DescriptionGenerator — LLM-based YouTube description generation."""

from __future__ import annotations

import json
import re

from ytfactory.publish.artifacts import description_path
from ytfactory.publish.config import PublishConfig
from ytfactory.publish.models import DescriptionResult


def _parse_json_response(text: str) -> dict:
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned.strip())
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return {}


_FALLBACK_DESCRIPTION = (
    "Watch this video to learn more about the topic.\n\n"
    "Don't forget to like, subscribe, and hit the bell icon for more content!"
)


class DescriptionGenerator:
    def __init__(self, llm, config: PublishConfig | None = None):
        self._llm = llm
        self._config = config or PublishConfig()

    def generate(
        self,
        project_id: str,
        project_title: str,
        script_excerpt: str,
        chapters_block: str,
        seo_keywords: list[str],
    ) -> DescriptionResult:
        top_kw = ", ".join(seo_keywords[:10])
        prompt = (
            "You are a YouTube content strategist. Write a complete YouTube video description.\n\n"
            f"Video Title: {project_title}\n"
            f"Chapters:\n{chapters_block}\n"
            f"Top Keywords: {top_kw}\n"
            f"Script Excerpt: {script_excerpt[: self._config.script_excerpt_chars]}\n\n"
            "Include: hook (first 2 lines), body summary, chapters block, call to action.\n"
            "Return ONLY valid JSON with no explanation:\n"
            '{"description": "<full description text>"}'
        )
        response = self._llm.generate(prompt)
        data = _parse_json_response(response.text)

        full_text = str(data.get("description") or _FALLBACK_DESCRIPTION)
        full_text = full_text[: self._config.max_description_length]

        result = DescriptionResult(
            full_text=full_text,
            word_count=len(full_text.split()),
            has_chapters="0:00" in full_text or "chapters" in full_text.lower(),
            has_cta=any(
                cta in full_text.lower()
                for cta in ("subscribe", "like", "comment", "follow")
            ),
        )
        description_path(project_id).write_text(result.full_text, encoding="utf-8")
        return result
