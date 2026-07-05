"""Subtitle RCA analyzer — maps SUBT_xxx validation failures to root causes."""

from __future__ import annotations

from pathlib import Path

from ytfactory.review.rca.framework import BaseRCAAnalyzer, RuleMapping
from ytfactory.review.rca.models import RCAIssue
from ytfactory.review.validation.models import ValidationResult

_MAPPINGS: dict[str, RuleMapping] = {
    "SUBT_001": RuleMapping(
        root_cause_code="missing_subtitle",
        root_cause_description=(
            "SRT subtitle file was not generated for the scene; "
            "CaptionGenerator pipeline did not complete or failed silently"
        ),
        rca_category="subtitle",
        primary_engine="CaptionGenerator",
        secondary_engines=["ASS Subtitle Engine"],
        base_confidence=100,
        suggested_fix=(
            "Add SRT existence check to CaptionGenerator output validation; "
            "fail loudly instead of silently skipping scenes"
        ),
        suggested_tests=[
            "Assert scene-NNN.srt exists for every scene after CaptionGenerator.run()",
            "Test CaptionGenerator raises an error when TTS audio is missing",
        ],
    ),
    "SUBT_002": RuleMapping(
        root_cause_code="sync_issue",
        root_cause_description=(
            "SRT timestamps overlap or are malformed — "
            "likely a timing calculation bug in CaptionGenerator or ASS Subtitle Engine"
        ),
        rca_category="subtitle",
        primary_engine="ASS Subtitle Engine",
        secondary_engines=["CaptionGenerator"],
        base_confidence=85,
        suggested_fix=(
            "Validate SRT timestamp ordering in CaptionGenerator before writing; "
            "ensure end timestamp > start timestamp for every cue"
        ),
        suggested_tests=[
            "Assert no two SRT cues overlap in any generated file",
            "Assert every SRT cue has end_time > start_time",
        ],
    ),
    "SUBT_003": RuleMapping(
        root_cause_code="reading_speed",
        root_cause_description=(
            "Subtitle characters-per-second (CPS) exceeds the readable limit — "
            "cues are too dense for the available display time"
        ),
        rca_category="subtitle",
        primary_engine="CaptionGenerator",
        secondary_engines=["ASS Subtitle Engine"],
        base_confidence=80,
        suggested_fix=(
            "Split long subtitle cues into shorter phrases; "
            "extend scene duration or reduce narration density"
        ),
        suggested_tests=[
            "Assert all subtitle cues have CPS <= 18.0",
            "Test CaptionGenerator splits cues when CPS would exceed the limit",
        ],
    ),
    "SUBT_004": RuleMapping(
        root_cause_code="formatting",
        root_cause_description=(
            "Subtitle lines exceed the character-per-line limit — "
            "text will wrap or be cut off in the video player"
        ),
        rca_category="subtitle",
        primary_engine="CaptionGenerator",
        secondary_engines=["ASS Subtitle Engine"],
        base_confidence=75,
        suggested_fix=(
            "Add line-break logic to CaptionGenerator to wrap lines at 42 characters; "
            "configure ASS Subtitle Engine with the same line-length constraint"
        ),
        suggested_tests=[
            "Assert no subtitle line exceeds 42 characters in any generated SRT",
        ],
    ),
    "SUBT_005": RuleMapping(
        root_cause_code="formatting",
        root_cause_description=(
            "Empty subtitle cues present — CaptionGenerator wrote cue entries with no text"
        ),
        rca_category="subtitle",
        primary_engine="CaptionGenerator",
        secondary_engines=[],
        base_confidence=80,
        suggested_fix=(
            "Filter out empty cues before writing the SRT file in CaptionGenerator"
        ),
        suggested_tests=[
            "Assert no SRT cue has empty text after CaptionGenerator.run()",
        ],
    ),
    "SUBT_006": RuleMapping(
        root_cause_code="sync_issue",
        root_cause_description=(
            "Subtitle text has low word overlap with narration — "
            "subtitles may not match the spoken audio"
        ),
        rca_category="subtitle",
        primary_engine="CaptionGenerator",
        secondary_engines=[],
        base_confidence=65,
        suggested_fix=(
            "Verify CaptionGenerator sources subtitles directly from narration text; "
            "ensure transcription-based caption workflows align with the narration script"
        ),
        suggested_tests=[
            "Assert Jaccard similarity between subtitle text and narration >= 0.3",
        ],
    ),
}


class SubtitleRCAAnalyzer(BaseRCAAnalyzer):
    validation_category = "subtitle"

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
