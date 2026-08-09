"""S4 — Shorts Image Prompt Engine.

Enriches every scene visual_prompt with vertical framing, anatomy constraints,
and clothing policy before writing the manifest to disk.
"""

from __future__ import annotations

from ytfactory.images.clothing_policy import apply_clothing_policy
from ytfactory.images.human_detector import add_anatomy_constraints
from ytfactory.shorts.models import (
    ShortsImageManifest,
    ShortsImageManifestItem,
    ShortsScenePlan,
    VideoResolution,
)
from ytfactory.shorts.repository import ShortsRepository

_VERTICAL_PREAMBLE = (
    "VERTICAL PORTRAIT COMPOSITION, 9:16, 1080x1920px. "
    "Portrait-oriented cinematic framing. "
    "Subject vertically centered and occupying approximately 40–70% of frame height. "
    "Keep the top 15% and bottom 25% visually clear for text overlays. "
    "Prioritize a single strong focal subject. "
)

_HOOK_PREAMBLE = (
    "SCROLL-STOPPING FIRST FRAME. "
    "Maximum visual impact. "
    "Immediately readable focal subject. "
    "Strong visual contrast. "
    "Striking composition. "
    "The image must communicate an intriguing situation within approximately 0.5 seconds of viewing. "
)


class ShortsImagePromptEngine:
    def __init__(self) -> None:
        self._repo = ShortsRepository()

    def generate(
        self,
        scene_plan: ShortsScenePlan,
        project_id: str,
        short_id: str,
    ) -> ShortsImageManifest:
        images: list[ShortsImageManifestItem] = []

        for scene in scene_plan.scenes:
            enriched = _enrich_prompt(scene.visual_prompt, is_hook=scene.is_hook_scene)
            filename = f"scene-{scene.index:03d}.png"
            images.append(
                ShortsImageManifestItem(
                    scene_index=scene.index,
                    filename=filename,
                    prompt=enriched,
                )
            )

        # Create the images/ directory
        self._repo.ensure_images_dir(project_id, short_id)

        manifest = ShortsImageManifest(
            short_id=short_id,
            parent_video_id=project_id,
            aspect_ratio="9:16",
            resolution=VideoResolution(width=1080, height=1920),
            ready_for_image_generation=True,
            images=images,
        )
        self._repo.save_image_manifest(project_id, short_id, manifest)
        return manifest


def _enrich_prompt(raw_prompt: str, *, is_hook: bool) -> str:
    """Build the final prompt: preambles → vertical → anatomy → clothing."""
    preamble = _HOOK_PREAMBLE if is_hook else ""
    base = preamble + _VERTICAL_PREAMBLE + raw_prompt.strip()

    # Apply anatomy constraints (reuse existing utility)
    base = add_anatomy_constraints(base)

    # Apply clothing policy (reuse existing utility)
    result = apply_clothing_policy(base)
    return result.final_prompt
