"""PinnedCommentGenerator — LLM-based YouTube pinned comment generation."""

from __future__ import annotations

import json
import re

from ytfactory.publish.artifacts import pinned_comment_path
from ytfactory.publish.config import PublishConfig
from ytfactory.publish.models import PinnedCommentResult

_FALLBACK_COMMENT = (
    "Every single one of us carries a force within — most never stop long enough to feel it. "
    "What is the one moment in your life where you truly felt that inner power? "
    "Share below — I read every comment. 👇"
)

_MAX_CHARS = 500


def _parse_json_response(text: str) -> dict:
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned.strip())
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return {}


class PinnedCommentGenerator:
    """Generate an engaging pinned comment that sparks viewer conversation."""

    def __init__(self, llm, config: PublishConfig | None = None):
        self._llm = llm
        self._config = config or PublishConfig()

    def generate(
        self,
        project_id: str,
        project_title: str,
        script_excerpt: str,
    ) -> PinnedCommentResult:
        prompt = (
            "You are a YouTube creator writing the FIRST PINNED COMMENT for your own video.\n\n"
            f"Video Title: {project_title}\n"
            f"Script Excerpt: {script_excerpt[:800]}\n\n"
            "Write a pinned comment that:\n"
            "- Feels personal and genuine, like the creator wrote it in the moment\n"
            "- References a specific idea or emotion from the video (not generic)\n"
            "- Ends with ONE clear, specific question that invites the viewer to share their experience\n"
            "- Is 2-3 sentences max, under 500 characters total\n"
            "- No hashtags, no emojis except optionally one at the very end\n\n"
            "Return ONLY valid JSON with no explanation:\n"
            '{"comment": "<the pinned comment text>"}'
        )

        response = self._llm.generate(prompt)
        data = _parse_json_response(response.text)

        text = str(data.get("comment") or _FALLBACK_COMMENT).strip()
        text = text[:_MAX_CHARS]

        result = PinnedCommentResult(
            text=text,
            char_count=len(text),
            has_question="?" in text,
        )

        pinned_comment_path(project_id).write_text(result.text, encoding="utf-8")
        return result
