"""Audio RCA analyzer — maps AUD_xxx validation failures to root causes."""

from __future__ import annotations

from pathlib import Path

from ytfactory.review.rca.framework import BaseRCAAnalyzer, RuleMapping
from ytfactory.review.rca.models import RCAIssue
from ytfactory.review.validation.models import ValidationResult

_MAPPINGS: dict[str, RuleMapping] = {
    "AUD_001": RuleMapping(
        root_cause_code="missing_asset",
        root_cause_description=(
            "Audio file was not generated for the scene; "
            "VoiceGenerator pipeline failed or was skipped"
        ),
        rca_category="audio",
        primary_engine="TTS Engine",
        secondary_engines=["VoiceGenerator"],
        base_confidence=100,
        suggested_fix=(
            "Add audio existence check to VoiceGenerator output validation; "
            "fail loudly rather than silently skipping scenes"
        ),
        suggested_tests=[
            "Assert scene-NNN.mp3 exists for every scene after VoiceGenerator.run()",
            "Test VoiceGenerator raises on TTS API failure instead of returning empty",
        ],
    ),
    "AUD_002": RuleMapping(
        root_cause_code="missing_asset",
        root_cause_description=(
            "Audio file exists but is suspiciously small — "
            "likely an empty or corrupt TTS response"
        ),
        rca_category="audio",
        primary_engine="TTS Engine",
        secondary_engines=["VoiceGenerator"],
        base_confidence=90,
        suggested_fix=(
            "Validate audio file size (>= 1 KB) immediately after TTS generation; "
            "discard and retry if the file is below the minimum threshold"
        ),
        suggested_tests=[
            "Assert all scene audio files are >= 1024 bytes",
            "Test VoiceGenerator retries when TTS response produces a tiny file",
        ],
    ),
    "AUD_003": RuleMapping(
        root_cause_code="silence",
        root_cause_description=(
            "Audio file is very short — likely near-silence or minimal speech; "
            "narration may be too brief or TTS failed to process the input"
        ),
        rca_category="audio",
        primary_engine="TTS Engine",
        secondary_engines=["ScriptWriter"],
        base_confidence=72,
        suggested_fix=(
            "Check scene narration is non-trivial before sending to TTS; "
            "increase minimum narration length; investigate TTS silence detection"
        ),
        suggested_tests=[
            "Assert all scene audio files are >= 5 KB (heuristic for real speech)",
            "Test that scenes with very short narration produce adequately-sized audio",
        ],
    ),
    "AUD_004": RuleMapping(
        root_cause_code="silence",
        root_cause_description=(
            "Voice clarity analysis is unavailable (requires librosa/scipy); "
            "audio quality cannot be verified automatically"
        ),
        rca_category="audio",
        primary_engine="TTS Engine",
        secondary_engines=[],
        base_confidence=0,
        suggested_fix=(
            "Install librosa and scipy to enable automated audio quality analysis; "
            "or validate audio quality manually for critical productions"
        ),
        suggested_tests=[
            "Add librosa/scipy to optional dependencies",
            "Test voice clarity analyzer runs when the dependencies are present",
        ],
    ),
}


class AudioRCAAnalyzer(BaseRCAAnalyzer):
    validation_category = "audio"

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
