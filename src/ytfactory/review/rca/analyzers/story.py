"""Story RCA analyzer — maps STOR_xxx validation failures to root causes.

Story validation covers narrative structure (scene ordering, scene count,
title uniqueness, narration variety, opening strength).  These issues are
mapped to the closest of the 7 RCA categories: script, narration, or rendering.
"""

from __future__ import annotations

from pathlib import Path

from ytfactory.review.rca.framework import BaseRCAAnalyzer, RuleMapping
from ytfactory.review.rca.models import RCAIssue
from ytfactory.review.validation.models import ValidationResult

_MAPPINGS: dict[str, RuleMapping] = {
    "STOR_001": RuleMapping(
        root_cause_code="wrong_order",
        root_cause_description=(
            "Scene indices are non-sequential or do not start from 1 — "
            "likely a scene ordering or indexing bug in ScenePlanner"
        ),
        rca_category="rendering",
        primary_engine="Scene Planner",
        secondary_engines=["Video Renderer"],
        base_confidence=90,
        suggested_fix=(
            "Enforce sequential 1-based scene indices in ScenePlanner output; "
            "re-index scenes after any re-ordering or filtering step"
        ),
        suggested_tests=[
            "Assert scene indices are sequential starting from 1 in scene-plan.json",
            "Test ScenePlanner re-indexes scenes correctly after filtering",
        ],
    ),
    "STOR_002": RuleMapping(
        root_cause_code="wrong_duration",
        root_cause_description=(
            "Scene count is outside the valid range — "
            "script may be too long/short or scene splitting went wrong"
        ),
        rca_category="script",
        primary_engine="Scene Planner",
        secondary_engines=["Script Pacing Engine"],
        base_confidence=80,
        suggested_fix=(
            "Add scene count validation in ScenePlanner; "
            "adjust Script Pacing Engine targets to produce the expected number of scenes"
        ),
        suggested_tests=[
            "Assert scene count is in [3, 50] after ScenePlanner.run()",
            "Test ScenePlanner handles very short and very long scripts correctly",
        ],
    ),
    "STOR_003": RuleMapping(
        root_cause_code="weak_flow",
        root_cause_description=(
            "Multiple scenes share the same title — "
            "ScenePlanner produced non-unique scene identifiers"
        ),
        rca_category="script",
        primary_engine="Scene Planner",
        secondary_engines=["ScriptWriter"],
        base_confidence=80,
        suggested_fix=(
            "Add title uniqueness validation in ScenePlanner; "
            "require unique, descriptive titles in the LLM prompt"
        ),
        suggested_tests=[
            "Assert all scene titles are unique in scene-plan.json",
        ],
    ),
    "STOR_004": RuleMapping(
        root_cause_code="repeated_content",
        root_cause_description=(
            "Multiple scenes have identical narration text — "
            "ScenePlanner or ScriptWriter produced duplicate content across scenes"
        ),
        rca_category="narration",
        primary_engine="ScriptWriter",
        secondary_engines=["Scene Planner"],
        base_confidence=85,
        suggested_fix=(
            "Add narration deduplication check in ScenePlanner; "
            "add anti-repetition instruction to ScriptWriter prompt"
        ),
        suggested_tests=[
            "Assert all narration values are unique across scenes",
        ],
    ),
    "STOR_005": RuleMapping(
        root_cause_code="weak_flow",
        root_cause_description=(
            "Opening scene narration is too brief — "
            "introduction may fail to hook the viewer"
        ),
        rca_category="narration",
        primary_engine="ScriptWriter",
        secondary_engines=[],
        base_confidence=72,
        suggested_fix=(
            "Instruct ScriptWriter to produce a strong, substantive opening scene "
            "with a minimum of 10 words of narration"
        ),
        suggested_tests=[
            "Assert first scene narration has >= 10 words",
        ],
    ),
}


class StoryRCAAnalyzer(BaseRCAAnalyzer):
    validation_category = "story"

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
