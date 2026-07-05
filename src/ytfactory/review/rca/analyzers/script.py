"""Script RCA analyzer — maps SCRIPT_xxx validation failures to root causes."""

from __future__ import annotations

from pathlib import Path

from ytfactory.review.rca.framework import BaseRCAAnalyzer, RuleMapping
from ytfactory.review.rca.models import RCAIssue
from ytfactory.review.validation.models import ValidationResult

_MAPPINGS: dict[str, RuleMapping] = {
    "SCRIPT_001": RuleMapping(
        root_cause_code="missing_script",
        root_cause_description=(
            "Script file was not generated or was removed before review; "
            "ScriptWriter pipeline did not complete successfully"
        ),
        rca_category="script",
        primary_engine="ScriptWriter",
        secondary_engines=[],
        base_confidence=100,
        suggested_fix=(
            "Ensure ScriptWriter pipeline completes and writes script/script.md "
            "before proceeding to scene planning; add existence check to BuildPipeline"
        ),
        suggested_tests=[
            "Assert script/script.md exists after ScriptWriter.run()",
            "Assert script/script.md is non-empty after ScriptWriter.run()",
            "Test ScriptWriter handles empty research output with a clear error",
        ],
    ),
    "SCRIPT_002_too_short": RuleMapping(
        root_cause_code="wrong_duration",
        root_cause_description=(
            "Script is too short — insufficient content depth or early LLM truncation"
        ),
        rca_category="script",
        primary_engine="Script Pacing Engine",
        secondary_engines=["ScriptWriter"],
        base_confidence=85,
        suggested_fix=(
            "Increase research depth; raise the minimum word count target in "
            "ScriptWriter prompt; enable self-critique loop to expand thin content"
        ),
        suggested_tests=[
            "Assert script word count >= configured minimum after ScriptWriter.run()",
            "Test ScriptWriter with minimal research input still meets word minimum",
        ],
    ),
    "SCRIPT_002_too_long": RuleMapping(
        root_cause_code="padding",
        root_cause_description=(
            "Script is too long — likely padding, repetition, or unconstrained LLM output"
        ),
        rca_category="script",
        primary_engine="Script Pacing Engine",
        secondary_engines=["ScriptWriter"],
        base_confidence=75,
        suggested_fix=(
            "Add a strict maximum word count constraint to the ScriptWriter prompt; "
            "enable deduplication post-processing to remove repeated sections"
        ),
        suggested_tests=[
            "Assert script word count <= configured maximum after ScriptWriter.run()",
        ],
    ),
    "SCRIPT_003": RuleMapping(
        root_cause_code="padding",
        root_cause_description=(
            "Script contains highly similar paragraphs — LLM recycled content across sections"
        ),
        rca_category="script",
        primary_engine="ScriptWriter",
        secondary_engines=["Script Pacing Engine"],
        base_confidence=80,
        suggested_fix=(
            "Add anti-repetition instruction to ScriptWriter prompt; "
            "implement post-processing deduplication before saving script.md"
        ),
        suggested_tests=[
            "Assert no paragraph pair has Jaccard similarity >= 0.8",
            "Test ScriptWriter produces unique paragraphs for distinct sections",
        ],
    ),
    "SCRIPT_004": RuleMapping(
        root_cause_code="weak_flow",
        root_cause_description=(
            "Script has too few sentences — likely a fragment or severely truncated output"
        ),
        rca_category="script",
        primary_engine="ScriptWriter",
        secondary_engines=[],
        base_confidence=80,
        suggested_fix=(
            "Investigate ScriptWriter for output truncation; "
            "add minimum sentence count to output validation within ScriptWriter"
        ),
        suggested_tests=[
            "Assert sentence count >= 3 after ScriptWriter.run()",
            "Test ScriptWriter does not truncate output on long research inputs",
        ],
    ),
    "SCRIPT_005": RuleMapping(
        root_cause_code="weak_flow",
        root_cause_description=(
            "Script has very few content lines — likely missing structural organization"
        ),
        rca_category="script",
        primary_engine="ScriptWriter",
        secondary_engines=[],
        base_confidence=65,
        suggested_fix=(
            "Add section headers and explicit paragraph breaks to the ScriptWriter prompt template"
        ),
        suggested_tests=[
            "Assert script has >= 3 content lines",
        ],
    ),
}


class ScriptRCAAnalyzer(BaseRCAAnalyzer):
    validation_category = "script"

    def _analyze_one(
        self,
        result: ValidationResult,
        project_dir: Path,
        scenes: list[dict],
        context: dict,
    ) -> RCAIssue | None:
        if result.rule_id == "SCRIPT_002":
            key = (
                "SCRIPT_002_too_short"
                if "too short" in result.description.lower()
                else "SCRIPT_002_too_long"
            )
            return self._from_mapping(result, _MAPPINGS[key])
        mapping = _MAPPINGS.get(result.rule_id)
        if not mapping:
            return self._unknown_issue(result)
        return self._from_mapping(result, mapping)
