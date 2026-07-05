"""Narration RCA analyzer — maps NARR_xxx validation failures to root causes."""

from __future__ import annotations

from pathlib import Path

from ytfactory.review.rca.framework import BaseRCAAnalyzer, RuleMapping
from ytfactory.review.rca.models import RCAIssue
from ytfactory.review.validation.models import ValidationResult

_MAPPINGS: dict[str, RuleMapping] = {
    "NARR_001": RuleMapping(
        root_cause_code="missing_narration",
        root_cause_description=(
            "Scene has no narration — ScenePlanner failed to assign narration text "
            "or the field was left empty in scene-plan.json"
        ),
        rca_category="narration",
        primary_engine="Scene Planner",
        secondary_engines=["ScriptWriter"],
        base_confidence=100,
        suggested_fix=(
            "Add a non-empty narration validation step in ScenePlanner before writing "
            "scene-plan.json; ensure ScriptWriter always produces scene-level narration"
        ),
        suggested_tests=[
            "Assert every scene has a non-empty 'narration' field after ScenePlanner.run()",
            "Test ScenePlanner rejects scenes with empty or whitespace-only narration",
        ],
    ),
    "NARR_002": RuleMapping(
        root_cause_code="wrong_duration",
        root_cause_description=(
            "Scene narration word count is outside the valid range — "
            "either too brief to fill the scene or too long to be read in time"
        ),
        rca_category="narration",
        primary_engine="ScriptWriter",
        secondary_engines=["Script Pacing Engine"],
        base_confidence=85,
        suggested_fix=(
            "Add per-scene word count targets to the ScriptWriter prompt; "
            "use scene duration to calculate narration length budget"
        ),
        suggested_tests=[
            "Assert scene narration word count in [5, 300] for all scenes",
            "Test that narration length scales with scene duration",
        ],
    ),
    "NARR_003": RuleMapping(
        root_cause_code="padding",
        root_cause_description=(
            "A single narration block is extremely long — "
            "content should be split across multiple scenes"
        ),
        rca_category="narration",
        primary_engine="ScriptWriter",
        secondary_engines=["Scene Planner"],
        base_confidence=75,
        suggested_fix=(
            "Instruct ScenePlanner to split long content into shorter, focused scenes; "
            "set a per-scene narration word limit in ScriptWriter"
        ),
        suggested_tests=[
            "Assert no single narration block exceeds 100 words",
        ],
    ),
    "NARR_004": RuleMapping(
        root_cause_code="fast_pace",
        root_cause_description=(
            "Average narration length per scene is very low — "
            "scenes are too sparse for TTS to produce engaging audio"
        ),
        rca_category="narration",
        primary_engine="TTS Engine",
        secondary_engines=["ScriptWriter"],
        base_confidence=70,
        suggested_fix=(
            "Increase minimum per-scene narration word count; "
            "combine short sparse scenes in ScenePlanner"
        ),
        suggested_tests=[
            "Assert average narration word count per scene >= 10",
        ],
    ),
}


class NarrationRCAAnalyzer(BaseRCAAnalyzer):
    validation_category = "narration"

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
