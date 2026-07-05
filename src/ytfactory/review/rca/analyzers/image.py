"""Image RCA analyzer — maps IMG_xxx validation failures to root causes."""

from __future__ import annotations

from pathlib import Path

from ytfactory.review.rca.framework import BaseRCAAnalyzer, RuleMapping
from ytfactory.review.rca.models import RCAIssue
from ytfactory.review.validation.models import ValidationResult

_MAPPINGS: dict[str, RuleMapping] = {
    "IMG_001": RuleMapping(
        root_cause_code="missing_asset",
        root_cause_description=(
            "Scene image file was not generated; "
            "ImageGenerator pipeline failed or was skipped for this scene"
        ),
        rca_category="image",
        primary_engine="Image Prompt Engine",
        secondary_engines=["ImageGenerator"],
        base_confidence=100,
        suggested_fix=(
            "Add image existence check to ImageGenerator output validation; "
            "ensure per-scene retry logic handles API failures before proceeding"
        ),
        suggested_tests=[
            "Assert scene-NNN.png exists for every non-stock scene after ImageGenerator.run()",
            "Test ImageGenerator retries and raises on persistent API failure",
        ],
    ),
    "IMG_002": RuleMapping(
        root_cause_code="missing_asset",
        root_cause_description=(
            "Scene image file exists but is suspiciously small — "
            "likely a partial download, API error response saved as a file, or corrupt image"
        ),
        rca_category="image",
        primary_engine="Image Prompt Engine",
        secondary_engines=["ImageGenerator"],
        base_confidence=90,
        suggested_fix=(
            "Validate image file size (>= 1 KB) immediately after download; "
            "discard and retry if the file is below the threshold"
        ),
        suggested_tests=[
            "Assert all scene images are >= 1024 bytes",
            "Test ImageGenerator discards and retries when response is < 1 KB",
        ],
    ),
    "IMG_003": RuleMapping(
        root_cause_code="weak_prompt",
        root_cause_description=(
            "Scene has no visual_prompt — ScenePlanner failed to generate an image description"
        ),
        rca_category="image",
        primary_engine="Image Prompt Engine",
        secondary_engines=["Scene Planner"],
        base_confidence=100,
        suggested_fix=(
            "Make visual_prompt a required field in ScenePlanner output; "
            "validate scene-plan.json schema before ImageGenerator runs"
        ),
        suggested_tests=[
            "Assert every scene has a non-empty 'visual_prompt' in scene-plan.json",
            "Test ScenePlanner rejects output missing visual_prompt fields",
        ],
    ),
    "IMG_004": RuleMapping(
        root_cause_code="repeated_imagery",
        root_cause_description=(
            "Multiple scenes share nearly identical visual prompts — "
            "images will look the same across scenes, reducing visual variety"
        ),
        rca_category="image",
        primary_engine="Image Prompt Engine",
        secondary_engines=["Scene Planner"],
        base_confidence=80,
        suggested_fix=(
            "Add visual diversity check to Image Prompt Engine; "
            "post-process visual prompts to ensure sufficient variation across scenes"
        ),
        suggested_tests=[
            "Assert no two visual_prompt pairs have Jaccard similarity >= 0.5",
            "Test Image Prompt Engine produces distinct prompts for consecutive scenes",
        ],
    ),
    "IMG_005": RuleMapping(
        root_cause_code="weak_prompt",
        root_cause_description=(
            "Scene has no shot_type assigned — Image Prompt Engine skipped cinematography metadata"
        ),
        rca_category="image",
        primary_engine="Image Prompt Engine",
        secondary_engines=["Scene Planner"],
        base_confidence=65,
        suggested_fix=(
            "Make shot_type a required field in Image Prompt Engine output; "
            "default to 'medium_shot' when not otherwise specified"
        ),
        suggested_tests=[
            "Assert every scene has a non-empty 'shot_type' field",
        ],
    ),
    "IMG_006": RuleMapping(
        root_cause_code="weak_prompt",
        root_cause_description=(
            "Visual prompt lacks style markers — "
            "image generation will produce inconsistent aesthetic results"
        ),
        rca_category="image",
        primary_engine="Image Prompt Engine",
        secondary_engines=[],
        base_confidence=70,
        suggested_fix=(
            "Append style guide (lighting, color palette, aspect ratio, art style) "
            "to every visual prompt in Image Prompt Engine"
        ),
        suggested_tests=[
            "Assert every visual_prompt contains at least one style descriptor",
            "Test Image Prompt Engine appends style markers to generated prompts",
        ],
    ),
}


class ImageRCAAnalyzer(BaseRCAAnalyzer):
    validation_category = "image"

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
