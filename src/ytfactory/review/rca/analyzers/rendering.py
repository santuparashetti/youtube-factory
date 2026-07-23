"""Rendering RCA analyzer — maps REND_xxx validation failures to root causes."""

from __future__ import annotations

from pathlib import Path

from ytfactory.review.rca.framework import BaseRCAAnalyzer, RuleMapping
from ytfactory.review.rca.models import RCAIssue
from ytfactory.review.validation.models import ValidationResult

_MAPPINGS: dict[str, RuleMapping] = {
    "REND_001": RuleMapping(
        root_cause_code="missing_asset",
        root_cause_description=(
            "Per-scene video clip was not rendered; "
            "VideoRenderer pipeline failed or was skipped for this scene"
        ),
        rca_category="rendering",
        primary_engine="Video Renderer",
        secondary_engines=[],
        base_confidence=100,
        suggested_fix=(
            "Add clip existence check to VideoRenderer output validation; "
            "fail loudly when FFmpeg exits with a non-zero code"
        ),
        suggested_tests=[
            "Assert scene-NNN.mp4 exists for every scene after VideoRenderer.run()",
            "Test VideoRenderer raises on FFmpeg failure",
        ],
    ),
    "REND_002": RuleMapping(
        root_cause_code="missing_asset",
        root_cause_description=(
            "Scene video clip exists but is suspiciously small — "
            "likely a corrupt or empty FFmpeg output"
        ),
        rca_category="rendering",
        primary_engine="Video Renderer",
        secondary_engines=[],
        base_confidence=90,
        suggested_fix=(
            "Validate video clip file size (>= 10 KB) immediately after FFmpeg completes; "
            "delete and re-render if below the threshold"
        ),
        suggested_tests=[
            "Assert all scene video clips are >= 10240 bytes",
            "Test VideoRenderer discards clips smaller than the minimum size",
        ],
    ),
    "REND_003": RuleMapping(
        root_cause_code="missing_asset",
        root_cause_description=(
            "Final concatenated video (final.mp4) was not produced; "
            "video concatenation step was skipped or FFmpeg concat failed"
        ),
        rca_category="rendering",
        primary_engine="Video Renderer",
        secondary_engines=[],
        base_confidence=100,
        suggested_fix=(
            "Ensure the concatenation step runs after all per-scene clips are ready; "
            "check FFmpeg concat demuxer exit code and fail loudly on error"
        ),
        suggested_tests=[
            "Assert video/final.mp4 exists after VideoRenderer.run()",
            "Test that final.mp4 is produced even when only one scene exists",
        ],
    ),
    "REND_004": RuleMapping(
        root_cause_code="missing_asset",
        root_cause_description=(
            "Final video exists but is too small — "
            "likely truncated output or a failed FFmpeg concat"
        ),
        rca_category="rendering",
        primary_engine="Video Renderer",
        secondary_engines=[],
        base_confidence=90,
        suggested_fix=(
            "Validate final.mp4 size (>= 100 KB) and duration after concatenation; "
            "re-run concat if the output is below the threshold"
        ),
        suggested_tests=[
            "Assert final.mp4 is >= 102400 bytes",
            "Test VideoRenderer validates final video size before returning",
        ],
    ),
    "REND_005": RuleMapping(
        root_cause_code="missing_asset",
        root_cause_description=(
            "Not all expected per-scene video clips are present — "
            "some scenes were skipped during rendering"
        ),
        rca_category="rendering",
        primary_engine="Video Renderer",
        secondary_engines=[],
        base_confidence=88,
        suggested_fix=(
            "Add a post-render completeness check in VideoRenderer; "
            "compare expected clip filenames against actual files before concatenation"
        ),
        suggested_tests=[
            "Assert clip count in video/ equals scene count after VideoRenderer.run()",
            "Test VideoRenderer aborts concatenation when any clip is missing",
        ],
    ),
    "REND_007": RuleMapping(
        root_cause_code="missing_brand_card",
        root_cause_description=(
            "Final scene is not the dedicated brand card asset — "
            "closing/CTA/signature block was not matched and the fallback "
            "brand card append did not fire, or the scene list was reverted "
            "to a stale cached plan without the brand card"
        ),
        rca_category="branding",
        primary_engine="Scene Planner",
        secondary_engines=["Branding Config", "Video Renderer"],
        base_confidence=95,
        suggested_fix=(
            "Ensure _mark_asset_scenes() always appends a brand_card scene "
            "as the final scene; re-apply it on cached plan reload so stale "
            "plans are repaired on re-render"
        ),
        suggested_tests=[
            "Assert scene_plan.json ends with scene_type=brand_card",
            "Test _mark_asset_scenes appends brand card when no closing match is found",
            "Test cached plan path re-appends brand card on reload",
        ],
    ),
}


class RenderingRCAAnalyzer(BaseRCAAnalyzer):
    validation_category = "rendering"

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
