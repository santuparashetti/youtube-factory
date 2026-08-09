"""S3 — Shorts Scene Planner (9:16 vertical)."""

from __future__ import annotations

import json
import re

from loguru import logger

from video_core.providers.llm.factory import get_llm_for_role
from ytfactory.config.settings import Settings
from ytfactory.shorts.models import (
    ShortsScene,
    ShortsScenePlan,
    ShortsScript,
    VideoResolution,
)
from ytfactory.shorts.prompts.scene_planner import SYSTEM_PROMPT, build_scene_plan_prompt


class ShortsScenePlanner:
    def __init__(self, settings: Settings) -> None:
        self._llm = get_llm_for_role(settings, "scene_planner")
        self._settings = settings

    def plan(self, script: ShortsScript) -> ShortsScenePlan:
        prompt = build_scene_plan_prompt(script)
        response = self._llm.generate(
            prompt, system_prompt=SYSTEM_PROMPT, temperature=0.3, json_mode=True
        )

        text = _strip_fences(response.text)
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Shorts scene planner: LLM returned invalid JSON. Preview: {text[:300]}"
            ) from exc

        scenes_raw = data.get("scenes", [])
        scenes = [_parse_scene(s, self._settings.shorts_narration_wpm) for s in scenes_raw]

        # Enforce scene 0 is always the hook
        if scenes:
            scenes[0] = scenes[0].model_copy(
                update={"is_hook_scene": True, "first_frame_priority": "maximum"}
            )

        # Enforce last scene is open_loop
        if len(scenes) > 1:
            scenes[-1] = scenes[-1].model_copy(
                update={"section": "open_loop"}
            )

        scene_count = len(scenes)
        s = self._settings
        if not (s.shorts_scene_count_min <= scene_count <= s.shorts_scene_count_max):
            logger.warning(
                "Shorts scene planner: {} scenes generated for {} (expected {}-{})",
                scene_count,
                script.short_id,
                s.shorts_scene_count_min,
                s.shorts_scene_count_max,
            )

        total_duration = sum(sc.duration_seconds for sc in scenes)

        return ShortsScenePlan(
            short_id=script.short_id,
            parent_video_id=script.parent_video_id,
            aspect_ratio="9:16",
            resolution=VideoResolution(width=1080, height=1920),
            target_duration_seconds=script.target_duration_seconds,
            total_estimated_duration=round(total_duration, 2),
            scene_count=scene_count,
            scenes=scenes,
            visual_hook_description=data.get("visual_hook_description", ""),
            provenance={
                "parent_video": script.parent_video_id,
                "short_id": script.short_id,
                "source_opportunity": script.source_opportunity_id,
            },
        )


def _strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```\s*$", "", text)
    return text.strip()


def _word_count(text: str) -> int:
    return len(text.split())


def _compute_duration(narration: str, wpm: int) -> float:
    """Duration derived from word count — never hardcoded."""
    return round((_word_count(narration) / wpm) * 60, 2)


def _parse_scene(raw: dict, wpm: int) -> ShortsScene:
    narration = raw.get("narration", "").strip()
    # Always derive duration from word count — discard LLM-provided value
    duration = _compute_duration(narration, wpm)

    _VALID_SECTIONS = {"hook", "setup", "story", "revelation", "open_loop"}
    section = raw.get("section", "story")
    if section not in _VALID_SECTIONS:
        section = "story"

    _VALID_SHOT_TYPES = {
        "portrait_close_up",
        "portrait_medium",
        "portrait_wide",
        "portrait_silhouette",
    }
    shot_type = raw.get("shot_type", "portrait_medium")
    if shot_type not in _VALID_SHOT_TYPES:
        shot_type = "portrait_medium"

    _VALID_PRIORITIES = {"maximum", "high", "normal"}
    priority = raw.get("first_frame_priority", "normal")
    if priority not in _VALID_PRIORITIES:
        priority = "normal"

    return ShortsScene(
        index=int(raw.get("index", 0)),
        section=section,
        narration=narration,
        visual_prompt=raw.get("visual_prompt", "").strip(),
        duration_seconds=duration,
        is_hook_scene=bool(raw.get("is_hook_scene", False)),
        first_frame_priority=priority,
        shot_type=shot_type,
        # motion_type excluded per Phase 1A spec
    )
