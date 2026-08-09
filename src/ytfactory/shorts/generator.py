"""S2 — Short Script Generator."""

from __future__ import annotations

import json
import re

from loguru import logger

from video_core.providers.llm.factory import get_llm_for_role
from ytfactory.config.settings import Settings
from ytfactory.shorts.models import LongFormBridge, ShortOpportunity, ShortsScript
from ytfactory.shorts.prompts.script_generator import (
    SYSTEM_PROMPT,
    build_generation_prompt,
    build_retry_prompt,
)


class ShortScriptGenerator:
    def __init__(self, settings: Settings) -> None:
        self._llm = get_llm_for_role(settings, "script")
        self._settings = settings

    def generate(
        self,
        opportunity: ShortOpportunity,
        parent_title: str,
        parent_script_md: str,
        project_id: str,
        short_index: int,
    ) -> ShortsScript:
        short_id = f"short-{short_index:03d}"
        prompt = build_generation_prompt(opportunity, parent_title, parent_script_md)
        data = self._call_llm(prompt)
        return self._build_script(data, short_id, project_id, opportunity)

    def regenerate(
        self,
        opportunity: ShortOpportunity,
        parent_title: str,
        parent_script_md: str,
        project_id: str,
        short_index: int,
        failure_reasons: list[str],
    ) -> ShortsScript:
        short_id = f"short-{short_index:03d}"
        prompt = build_retry_prompt(
            opportunity, parent_title, parent_script_md, failure_reasons
        )
        data = self._call_llm(prompt)
        return self._build_script(data, short_id, project_id, opportunity)

    def _call_llm(self, prompt: str) -> dict:
        response = self._llm.generate(
            prompt, system_prompt=SYSTEM_PROMPT, temperature=0.5, json_mode=True
        )
        text = _strip_fences(response.text)
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Script generator: LLM returned invalid JSON. Preview: {text[:300]}"
            ) from exc

    def _build_script(
        self,
        data: dict,
        short_id: str,
        project_id: str,
        opportunity: ShortOpportunity,
    ) -> ShortsScript:
        hook = data.get("hook", "").strip()
        setup = data.get("setup", "").strip()
        story = data.get("story", "").strip()
        revelation = data.get("revelation", "").strip()
        open_loop = data.get("open_loop", "").strip()

        # full_script is always assembled in Python — never from LLM
        full_script = "\n\n".join([hook, setup, story, revelation, open_loop])
        word_count = len(full_script.split())
        duration = (word_count / self._settings.shorts_narration_wpm) * 60

        bridge_raw = data.get("long_form_bridge", {})
        bridge = _parse_bridge(bridge_raw, project_id)

        logger.debug(
            "Script generator: {} — {} words, {:.1f}s estimated",
            short_id,
            word_count,
            duration,
        )

        return ShortsScript(
            short_id=short_id,
            parent_video_id=project_id,
            angle=opportunity.angle,
            source_opportunity_id=opportunity.opportunity_id,
            title=data.get("title", "").strip(),
            hook=hook,
            setup=setup,
            story=story,
            revelation=revelation,
            open_loop=open_loop,
            full_script=full_script,
            long_form_bridge=bridge,
            target_duration_seconds=self._settings.shorts_target_duration_seconds,
            estimated_word_count=word_count,
            validation_passed=False,  # set by validator after scoring
        )


def _strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```\s*$", "", text)
    return text.strip()


def _parse_bridge(raw: dict, project_id: str) -> LongFormBridge:
    _VALID_RELATIONSHIPS = {
        "opens_question",
        "contradicts_assumption",
        "deepens_theme",
        "reveals_mechanism",
    }
    _VALID_BRIDGE_TYPES = {
        "open_question",
        "incomplete_explanation",
        "surprising_consequence",
        "deeper_mechanism",
        "story_continuation",
    }
    relationship = raw.get("relationship", "opens_question")
    if relationship not in _VALID_RELATIONSHIPS:
        relationship = "opens_question"
    bridge_type = raw.get("bridge_type", "open_question")
    if bridge_type not in _VALID_BRIDGE_TYPES:
        bridge_type = "open_question"
    return LongFormBridge(
        source_video=project_id,
        relationship=relationship,
        bridge_type=bridge_type,
        unresolved_question=raw.get("unresolved_question", ""),
        continuation_value=raw.get("continuation_value", ""),
    )
