"""SEOGenerator — LLM-based YouTube SEO metadata generation."""

from __future__ import annotations

import json
import re

from ytfactory.publish.artifacts import hashtags_path, keywords_path, youtube_tags_path
from ytfactory.publish.config import PublishConfig
from ytfactory.publish.models import SEOResult


def _parse_json_response(text: str) -> dict:
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned.strip())
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return {}


def _clamp_tags(tags: list[str], max_chars: int) -> list[str]:
    """Trim tag list so comma-joined total ≤ max_chars."""
    kept: list[str] = []
    chars = 0
    for tag in tags:
        addition = len(tag) + (2 if kept else 0)  # ", " separator
        if chars + addition > max_chars:
            break
        kept.append(tag)
        chars += addition
    return kept


class SEOGenerator:
    def __init__(self, llm, config: PublishConfig | None = None):
        self._llm = llm
        self._config = config or PublishConfig()

    def generate(
        self,
        project_id: str,
        project_title: str,
        script_excerpt: str,
        scene_titles: list[str],
    ) -> SEOResult:
        top_scenes = ", ".join(scene_titles[: self._config.scene_titles_in_prompt])
        prompt = (
            "You are a YouTube SEO expert. Generate comprehensive SEO metadata.\n\n"
            f"Video Topic: {project_title}\n"
            f"Scene Titles: {top_scenes}\n"
            f"Script Excerpt: {script_excerpt[: self._config.script_excerpt_chars]}\n\n"
            "Return ONLY valid JSON with no explanation:\n"
            "{\n"
            '  "primary_keywords": ["<kw1>", "<kw2>", "<kw3>"],\n'
            '  "secondary_keywords": ["<kw4>", "<kw5>", "<kw6>"],\n'
            '  "long_tail_keywords": ["<phrase1>", "<phrase2>", "<phrase3>"],\n'
            '  "hashtags": ["#tag1", "#tag2", "#tag3"],\n'
            '  "youtube_tags": ["tag1", "tag2", "tag3"]\n'
            "}"
        )
        response = self._llm.generate(prompt)
        data = _parse_json_response(response.text)

        primary_kw = [str(k) for k in (data.get("primary_keywords") or [])][:10]
        secondary_kw = [str(k) for k in (data.get("secondary_keywords") or [])][:10]
        long_tail_kw = [str(k) for k in (data.get("long_tail_keywords") or [])][:10]
        hashtags = [
            (h if h.startswith("#") else f"#{h}") for h in (data.get("hashtags") or [])
        ][: self._config.max_hashtags]
        youtube_tags = _clamp_tags(
            [str(t) for t in (data.get("youtube_tags") or [])],
            self._config.max_tags_chars,
        )

        result = SEOResult(
            primary_keywords=primary_kw,
            secondary_keywords=secondary_kw,
            long_tail_keywords=long_tail_kw,
            hashtags=hashtags,
            youtube_tags=youtube_tags,
            total_tags_chars=len(", ".join(youtube_tags)),
        )
        all_kw = (
            result.primary_keywords
            + result.secondary_keywords
            + result.long_tail_keywords
        )
        keywords_path(project_id).write_text("\n".join(all_kw), encoding="utf-8")
        hashtags_path(project_id).write_text(
            "\n".join(result.hashtags), encoding="utf-8"
        )
        youtube_tags_path(project_id).write_text(
            ", ".join(result.youtube_tags), encoding="utf-8"
        )
        return result
