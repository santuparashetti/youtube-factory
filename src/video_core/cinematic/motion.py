"""
Motion Planner — assigns emotion-aware camera movement to every scene.

Output: each scene dict gains a 'motion' key containing a MotionSpec dict.
The renderer (Phase 3) reads this dict to drive the FFmpeg zoompan filter.

This module does NO I/O and calls NO LLMs. Pure data transformation:
    list[scene_dict] → list[scene_dict with 'motion' added]

Reuses the existing emotion classifier (providers/tts/emotion.py) so the
same 12-emotion system drives both TTS prosody and camera movement — no
duplicate classification logic anywhere.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from video_core.cinematic.profiles import ProfileConfig, get_profile_config
from video_core.providers.tts.emotion import classify_scene


@dataclass(frozen=True)
class MotionSpec:
    """
    Complete camera movement specification for one scene.

    All values are normalised so the renderer can translate them
    directly to FFmpeg zoompan expressions in Phase 3.

    Attributes:
        motion_type:  Semantic motion name. Renderer dispatches on this.
        start_scale:  Zoom level at frame 0 (1.0 = full frame, no zoom).
        end_scale:    Zoom level at last frame.
        anchor_x:     Horizontal focus point in [0.0, 1.0] (0.5 = centre).
        anchor_y:     Vertical focus point in [0.0, 1.0] (0.5 = centre).
        drift_x:      Horizontal travel as fraction of frame width.
                      Positive = camera drifts left→right.
                      0.0 = no horizontal drift.
        drift_y:      Vertical travel as fraction of frame height.
                      Positive = camera drifts bottom→top (tilt up).
                      0.0 = no vertical drift.
        easing:       Interpolation curve: "linear" | "ease_in_out".
        emotion:      Name of the dominant emotion that drove this choice.
    """

    motion_type: str
    start_scale: float
    end_scale: float
    anchor_x: float
    anchor_y: float
    drift_x: float
    drift_y: float
    easing: str
    emotion: str

    def to_dict(self) -> dict:
        return asdict(self)


# ── Motion type → geometry resolver ──────────────────────────────────────────


def _resolve_motion(
    motion_type: str,
    scale_tier: str,
    cfg: ProfileConfig,
    scene_index: int,
) -> tuple[float, float, float, float, float, float]:
    """
    Resolve (start_scale, end_scale, anchor_x, anchor_y, drift_x, drift_y)
    from a motion_type + scale_tier + profile config.

    scene_index is used only to alternate drift direction so consecutive
    drift scenes don't all pan in the same direction.
    """
    lo, hi = {
        "small": cfg.scale_range_small,
        "medium": cfg.scale_range_medium,
        "large": cfg.scale_range_large,
    }.get(scale_tier, cfg.scale_range_medium)

    d = cfg.drift_amount
    # Alternate drift direction by index (even = left→right, odd = right→left)
    drift_sign = 1.0 if scene_index % 2 == 0 else -1.0

    match motion_type:
        case "static":
            return (1.0, 1.0, 0.5, 0.5, 0.0, 0.0)

        case "push_in":
            return (lo, hi, 0.5, 0.5, 0.0, 0.0)

        case "push_in_slow":
            # Half the normal zoom range — weighted, unhurried
            mid = lo + (hi - lo) * 0.5
            return (lo, mid, 0.5, 0.5, 0.0, 0.0)

        case "push_in_fast":
            # Uses the large scale range regardless of tier argument
            _, hi_large = cfg.scale_range_large
            return (lo, hi_large, 0.5, 0.5, 0.0, 0.0)

        case "pull_out":
            return (hi, lo, 0.5, 0.5, 0.0, 0.0)

        case "pull_out_wide":
            # Starts more zoomed in → bigger reveal
            _, hi_large = cfg.scale_range_large
            return (hi_large, 1.0, 0.5, 0.5, 0.0, 0.0)

        case "drift":
            # Constant slight zoom; motion comes from horizontal x shift
            zoom = (
                1.0 + d if d > 0 else 1.04
            )  # enough headroom to pan without black bars
            return (zoom, zoom, 0.5, 0.5, d * drift_sign, 0.0)

        case "tilt_up":
            # Camera rises: anchor below centre, zoom stays mild
            # y anchor > 0.5 means the focus point starts lower in the frame
            return (lo, hi, 0.5, 0.65, 0.0, d * 0.5)

        case _:
            return (1.0, 1.0, 0.5, 0.5, 0.0, 0.0)


# ── Asset scene → MotionSpec ──────────────────────────────────────────────────


def _asset_motion(scene: dict, cfg: ProfileConfig) -> MotionSpec:
    """
    Convert an existing 'animation' string (Asset Scene System V1) into a
    MotionSpec so the renderer uses a single unified code path.

    If no animation is set, defaults to slow_zoom (brand card standard).
    """
    animation = scene.get("animation", "slow_zoom")
    _, hi = cfg.scale_range_medium

    match animation:
        case "slow_zoom":
            ss, es, ax, ay, dx, dy = (1.0, hi, 0.5, 0.5, 0.0, 0.0)
            mtype = "push_in"
        case "slow_zoom_out":
            ss, es, ax, ay, dx, dy = (hi, 1.0, 0.5, 0.5, 0.0, 0.0)
            mtype = "pull_out"
        case "drift":
            zoom = 1.0 + cfg.drift_amount
            d = cfg.drift_amount
            ss, es, ax, ay, dx, dy = (zoom, zoom, 0.5, 0.5, d, 0.0)
            mtype = "drift"
        case _:
            ss, es, ax, ay, dx, dy = (1.0, 1.0, 0.5, 0.5, 0.0, 0.0)
            mtype = "static"

    return MotionSpec(
        motion_type=mtype,
        start_scale=round(ss, 4),
        end_scale=round(es, 4),
        anchor_x=ax,
        anchor_y=ay,
        drift_x=round(dx, 4),
        drift_y=round(dy, 4),
        easing=cfg.easing,
        emotion="asset",
    )


# ── Motion Planner ────────────────────────────────────────────────────────────


class MotionPlanner:
    """
    Assigns camera movement to every scene in a scene plan.

    Usage:
        planner = MotionPlanner()
        scenes = planner.plan(scenes, profile="cinematic")
        # Each scene now has scene["motion"] = MotionSpec.to_dict()

    The planner is stateless — safe to reuse across projects.
    """

    def plan(
        self,
        scenes: list[dict],
        profile: str = "balanced",
    ) -> list[dict]:
        """
        Enrich each scene dict with a 'motion' key containing a MotionSpec.

        For generated_image scenes: classify dominant emotion, map to motion
        type via the profile's motion_map, then resolve geometry.

        For asset scenes: convert existing 'animation' string to a MotionSpec
        so the renderer only needs to read 'motion'.

        Mutates in-place and returns the same list (consistent with
        _mark_asset_scenes() pattern used in the scene planner).

        Args:
            scenes:  Scene dicts from scene-plan.json.
            profile: Rendering profile name — draft | balanced | cinematic | premium.

        Returns:
            The same scene list with 'motion' added to every scene.
        """
        cfg = get_profile_config(profile)
        total = len(scenes)

        for scene in scenes:
            scene_position = (
                (scene["index"] - 1) / max(total - 1, 1) if total > 1 else 0.5
            )
            scene_type = scene.get("scene_type", "generated_image")

            if scene_type == "asset":
                spec = _asset_motion(scene, cfg)
            else:
                spec = self._plan_generated(scene, scene_position, cfg)

            scene["motion"] = spec.to_dict()

        return scenes

    def _plan_generated(
        self,
        scene: dict,
        scene_position: float,
        cfg: ProfileConfig,
    ) -> MotionSpec:
        """Classify emotion and assign motion for an AI-generated scene."""
        narration = scene.get("narration", "")
        profile_map = cfg.motion_map

        # Reuse the TTS emotion classifier — same 12-emotion system
        emotion_profile = classify_scene(narration, scene_position)
        emotion_name = emotion_profile.emotion.value  # e.g. "curiosity"

        motion_type, scale_tier = profile_map.get(emotion_name, ("static", "small"))

        start_s, end_s, ax, ay, dx, dy = _resolve_motion(
            motion_type, scale_tier, cfg, scene["index"]
        )

        return MotionSpec(
            motion_type=motion_type,
            start_scale=round(start_s, 4),
            end_scale=round(end_s, 4),
            anchor_x=ax,
            anchor_y=ay,
            drift_x=round(dx, 4),
            drift_y=round(dy, 4),
            easing=cfg.easing,
            emotion=emotion_name,
        )
