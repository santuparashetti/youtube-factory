"""Motion RCA analyzer — maps MOT_xxx validation failures to root causes."""

from __future__ import annotations

from pathlib import Path

from ytfactory.review.rca.framework import BaseRCAAnalyzer, RuleMapping
from ytfactory.review.rca.models import RCAIssue
from ytfactory.review.validation.models import ValidationResult

_MAPPINGS: dict[str, RuleMapping] = {
    "MOT_001": RuleMapping(
        root_cause_code="wrong_duration",
        root_cause_description=(
            "Scene duration is outside the valid range — "
            "too short to display content meaningfully or too long to hold attention"
        ),
        rca_category="motion",
        primary_engine="Scene Planner",
        secondary_engines=["Motion Engine"],
        base_confidence=85,
        suggested_fix=(
            "Add per-scene duration validation in ScenePlanner; "
            "enforce minimum (2 s) and maximum (120 s) duration constraints during planning"
        ),
        suggested_tests=[
            "Assert all scene durations are in [2.0, 120.0] seconds",
            "Test ScenePlanner clamps duration to valid range",
        ],
    ),
    "MOT_002": RuleMapping(
        root_cause_code="wrong_duration",
        root_cause_description=(
            "Scene duration is zero or negative — "
            "duration_seconds field was not set or was computed incorrectly"
        ),
        rca_category="motion",
        primary_engine="Scene Planner",
        secondary_engines=["Motion Engine"],
        base_confidence=100,
        suggested_fix=(
            "Make duration_seconds a required field in ScenePlanner; "
            "derive it from narration word count if not explicitly provided "
            "(approximately 130 words/minute)"
        ),
        suggested_tests=[
            "Assert all scene duration_seconds > 0",
            "Test ScenePlanner derives a positive duration from narration length",
        ],
    ),
    "MOT_003": RuleMapping(
        root_cause_code="static_scene",
        root_cause_description=(
            "Scene has no shot_type assigned — "
            "Motion Engine cannot apply camera movement metadata"
        ),
        rca_category="motion",
        primary_engine="Motion Engine",
        secondary_engines=["Scene Planner"],
        base_confidence=60,
        suggested_fix=(
            "Add shot_type to the ScenePlanner output schema; "
            "default to 'medium_shot' when not otherwise specified by the LLM"
        ),
        suggested_tests=[
            "Assert every scene has a non-empty 'shot_type' in scene-plan.json",
        ],
    ),
    "MOT_004": RuleMapping(
        root_cause_code="poor_transition",
        root_cause_description=(
            "Scene has no transition assigned — "
            "video will use a hard cut between scenes by default"
        ),
        rca_category="motion",
        primary_engine="Motion Engine",
        secondary_engines=["Scene Planner"],
        base_confidence=60,
        suggested_fix=(
            "Add transition field to ScenePlanner output; "
            "default to 'fade' for the first and last scenes, 'cut' for middle scenes"
        ),
        suggested_tests=[
            "Assert every scene has a 'transition' field in scene-plan.json",
        ],
    ),
}


class MotionRCAAnalyzer(BaseRCAAnalyzer):
    validation_category = "motion"

    def _analyze_one(
        self,
        result: ValidationResult,
        project_dir: Path,
        scenes: list[dict],
        context: dict,
    ) -> RCAIssue | None:
        mapping = _MAPPINGS.get(result.rule_id)
        if not mapping:
            return self._unknown_issue(result)
        return self._from_mapping(result, mapping)
