"""TitleGenerator — LLM-based YouTube title generation."""

from __future__ import annotations

import json
import re

from ytfactory.publish.artifacts import alternate_titles_path, title_path
from ytfactory.publish.config import PublishConfig
from ytfactory.publish.models import TitleResult


def _parse_json_response(text: str) -> dict:
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned.strip())
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return {}


_FALLBACK_ALTERNATIVES = [
    "Learn More About This Topic",
    "An In-Depth Look",
    "Everything You Need to Know",
    "The Complete Guide",
    "A Deep Dive",
]


class TitleGenerator:
    def __init__(self, llm, config: PublishConfig | None = None):
        self._llm = llm
        self._config = config or PublishConfig()

    def generate(
        self,
        project_id: str,
        project_title: str,
        script_excerpt: str,
        scene_titles: list[str],
    ) -> TitleResult:
        top_scenes = ", ".join(scene_titles[: self._config.scene_titles_in_prompt])
        prompt = (
            "You are a YouTube SEO expert. Generate a compelling YouTube video title.\n\n"
            f"Video Topic: {project_title}\n"
            f"Top Scene Titles: {top_scenes}\n"
            f"Script Excerpt: {script_excerpt[: self._config.script_excerpt_chars]}\n\n"
            "Return ONLY valid JSON with no explanation:\n"
            '{"primary": "<title>", "alternatives": ["<alt1>", "<alt2>", "<alt3>", "<alt4>", "<alt5>"]}'
        )
        response = self._llm.generate(prompt)
        data = _parse_json_response(response.text)

        primary = str(data.get("primary") or project_title)
        alternatives: list[str] = list(data.get("alternatives") or [])
        if len(alternatives) < 5:
            alternatives += _FALLBACK_ALTERNATIVES[len(alternatives) : 5]
        alternatives = alternatives[:5]

        result = TitleResult(
            primary=primary,
            alternatives=alternatives,
            length_valid=len(primary) <= self._config.max_title_length,
            length_warning=len(primary) > self._config.optimal_title_length,
        )
        title_path(project_id).write_text(result.primary, encoding="utf-8")
        alternate_titles_path(project_id).write_text(
            "\n".join(result.alternatives), encoding="utf-8"
        )
        return result
