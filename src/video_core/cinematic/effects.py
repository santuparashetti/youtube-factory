"""
Effects Planner — per-scene visual effect assignments.

Assigns film grain, vignette, and emotion-aware colour grading to every
scene.  All effects are gated by the rendering profile:

  draft / balanced  — no effects (fastest render, clean image)
  cinematic         — colour grade + vignette
  premium           — colour grade + vignette + film grain

Gaussian blur is added independently for scenes with a blur_dissolve
transition, regardless of profile.

The FFmpegRenderer inserts the generated filter strings BEFORE the subtitle
burn-in so subtitle text stays clean on top of the processed image.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from video_core.cinematic.profiles import RenderProfile


@dataclass(frozen=True)
class EffectSpec:
    """
    Visual effect assignments for one scene.

    Applied by FFmpegRenderer as additional vf filters between the
    spatial / motion layer and the subtitle burn-in.

    Attributes:
        color_grade: FFmpeg 'eq' filter string (e.g. "eq=contrast=1.08:
                     saturation=1.12"). Empty string = skip.
        vignette:    Add a vignette filter that darkens frame edges.
        film_grain:  Add luma-channel noise for a film-grain texture.
        blur_sigma:  Gaussian blur sigma applied to the whole clip.
                     > 0 for blur_dissolve transitions; 0.0 = no blur.
    """

    color_grade: str
    vignette: bool
    film_grain: bool
    blur_sigma: float

    def to_dict(self) -> dict:
        return asdict(self)


# ── Emotion → colour grade ────────────────────────────────────────────────────
#
# FFmpeg 'eq' filter values are intentionally subtle so they reinforce
# emotional tone without distorting AI-generated imagery.
#
# eq parameters:
#   contrast   (default 1.0) — higher = punchier shadows and highlights
#   brightness (default 0.0) — positive = lifted, negative = crushed
#   saturation (default 1.0) — higher = vivid, lower = desaturated
#   gamma      (default 1.0) — < 1.0 brightens mid-tones slightly

_EMOTION_GRADE: dict[str, str] = {
    # High energy / vivid
    "curiosity": "eq=contrast=1.06:saturation=1.12",
    "wonder": "eq=contrast=1.05:saturation=1.15:gamma=0.97",
    "awe": "eq=contrast=1.08:saturation=1.12",
    "urgency": "eq=contrast=1.12:brightness=-0.02:saturation=1.20",
    "determination": "eq=contrast=1.10:saturation=1.10",
    "revelation": "eq=contrast=1.15:brightness=0.02:saturation=1.05",
    # Introspective / desaturated
    "reflection": "eq=contrast=1.02:saturation=0.92",
    "mystery": "eq=contrast=1.08:brightness=-0.04:saturation=0.88",
    "sadness": "eq=contrast=1.00:brightness=-0.02:saturation=0.82",
    # Warm / gentle
    "peace": "eq=contrast=1.00:brightness=0.01:saturation=1.05",
    "hope": "eq=contrast=1.04:brightness=0.02:saturation=1.08",
    "compassion": "eq=contrast=1.02:brightness=0.01:saturation=1.05",
}

# Profile sets that enable each effect tier
_GRADE_PROFILES: frozenset[str] = frozenset(
    {RenderProfile.CINEMATIC, RenderProfile.PREMIUM}
)
_GRAIN_PROFILES: frozenset[str] = frozenset({RenderProfile.PREMIUM})


def _blur_sigma(scene: dict) -> float:
    """Return blur sigma when a blur_dissolve transition is assigned to this scene."""
    for key in ("transition_in", "transition_out"):
        if scene.get(key, {}).get("transition_type") == "blur_dissolve":
            return 2.0
    return 0.0


class EffectsPlanner:
    """
    Assigns EffectSpec to every scene based on emotion and rendering profile.

    Reads the 'motion' key (added by MotionPlanner) to obtain the dominant
    emotion — no additional LLM classification is performed.

    Usage:
        planner = EffectsPlanner()
        scenes = planner.plan(scenes, profile="cinematic")
        # Each scene now has scene["effects"] = EffectSpec.to_dict()

    The planner is stateless; safe to reuse across projects.
    """

    def plan(
        self,
        scenes: list[dict],
        profile: str = "balanced",
    ) -> list[dict]:
        """
        Enrich each scene with an 'effects' key containing an EffectSpec dict.

        Mutates in-place and returns the same list (consistent with
        MotionPlanner and TransitionPlanner conventions).

        Args:
            scenes:  Scene dicts with 'motion' key already populated.
            profile: Rendering profile — draft | balanced | cinematic | premium.

        Returns:
            The same scene list with 'effects' added to every scene.
        """
        effects_on = profile in _GRADE_PROFILES
        grain_on = profile in _GRAIN_PROFILES

        for scene in scenes:
            sigma = _blur_sigma(scene)

            if not effects_on:
                spec = EffectSpec(
                    color_grade="",
                    vignette=False,
                    film_grain=False,
                    blur_sigma=sigma,
                )
            else:
                # Emotion comes from MotionPlanner — no re-classification needed
                emotion = scene.get("motion", {}).get("emotion", "reflection")
                color_grade = (
                    "" if emotion == "asset" else _EMOTION_GRADE.get(emotion, "")
                )

                spec = EffectSpec(
                    color_grade=color_grade,
                    vignette=True,
                    film_grain=grain_on,
                    blur_sigma=sigma,
                )

            scene["effects"] = spec.to_dict()

        return scenes
