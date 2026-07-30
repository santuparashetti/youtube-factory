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

import logging
from dataclasses import asdict, dataclass

from video_core.cinematic.profiles import ProfileConfig, get_profile_config
from video_core.providers.tts.emotion import classify_scene

logger = logging.getLogger(__name__)

# Anti-jerk RULE 6: max magnitude for a secondary/micro drift axis added on
# top of a motion type's primary movement (1.2% of frame width/height).
_SECONDARY_DRIFT_CAP = 0.012


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
        easing:       Interpolation curve — see ffmpeg_filters._t_factor for
                      the full list (linear, ease_in, ease_out, ease_in_out,
                      smoothstep, sine, sine_power, cubic, quint, settle).
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


# ── Composition-aware anchoring (CHANGE 4) ───────────────────────────────────

_CLOSE_UP_SHOTS = frozenset({"close_up", "portrait"})
_DRONE_SHOTS = frozenset({"drone_shot", "aerial"})
_WIDE_SHOTS = frozenset({"wide_shot", "establishing"})


def _apply_shot_type_anchor(
    anchor_x: float, anchor_y: float, shot_type: str
) -> tuple[float, float]:
    """Nudge the resolved anchor point based on shot composition.

    macro_shot deliberately falls through unchanged — the resolved anchor
    already fits close macro framing.
    """
    if shot_type in _CLOSE_UP_SHOTS:
        return anchor_x, 0.40
    if shot_type in _DRONE_SHOTS:
        return anchor_x, 0.45
    if shot_type == "macro_shot":
        return anchor_x, anchor_y
    if shot_type in _WIDE_SHOTS:
        return 0.5, 0.5
    return anchor_x, anchor_y


def _cap_secondary(value: float) -> float:
    return max(-_SECONDARY_DRIFT_CAP, min(_SECONDARY_DRIFT_CAP, value))


def _scale_endpoint(value: float, duration_factor: float) -> float:
    """Scale a fixed-geometry endpoint's deviation from 1.0 by duration_factor.

    Mirrors the existing tier-based lo/hi scaling so long scenes stay
    proportionally more dynamic and short scenes stay subtler, for the new
    motion types' literal start/end values exactly as it already works for
    the tier-based scale_range_* types.
    """
    return 1.0 + (value - 1.0) * duration_factor


# ── Per-motion-type easing overrides ─────────────────────────────────────────
# The cinematic motion type library (Cinematic Camera System V1) was designed
# with a distinct easing curve per motion type — sine for gentle push/pulls,
# cubic/quint for punchier ones, linear for drift pans where a constant-speed
# pan reads clearest. Types not listed here (legacy 8-type set: static,
# push_in, push_in_slow, push_in_fast, pull_out, pull_out_wide, drift,
# tilt_up, hold_locked) fall back to the profile's global easing, unchanged.
_MOTION_EASING: dict[str, str] = {
    "push_slow": "sine_power",
    "push_emotional": "cubic",
    "push_hero": "quint",
    "push_reveal": "cubic",
    "push_suspense": "sine_power",
    "pull_reflection": "sine",
    "pull_isolation": "ease_out",
    "pull_ending": "cubic",
    "pull_wide": "ease_out",
    "drift_float": "linear",
    "drift_horizon": "linear",
    "drift_vertical_up": "sine",
    "drift_vertical_down": "linear",
    "drift_river": "sine",
    "hold_tripod": "sine",
    "reveal_corner": "ease_out",
    "reveal_window": "smoothstep",
    "reveal_light": "cubic",
    "reveal_subject": "ease_out",
    "macro_detail": "cubic",
    "macro_drift": "linear",
}


def _resolve_easing(motion_type: str, cfg: ProfileConfig) -> str:
    """Per-motion-type easing, falling back to the profile's default.

    hold_breathing/macro_breathing are intentionally absent — their
    oscillation is built directly in ffmpeg_filters._build_breathing_filter
    and doesn't consume the 'easing' field.
    """
    return _MOTION_EASING.get(motion_type, cfg.easing)


# ── Minimum motion visibility floor ──────────────────────────────────────────
# motion.py is resolution-agnostic (drift_x/y are fractions of frame
# width/height, consumed at any target resolution by ffmpeg_filters.py), so
# there's no real output width to check pixel visibility against here. 1280
# is the documented default render width (HD 720p, per CLAUDE.md) and is
# what the showcase/verification scripts measure diff against — used as a
# reference for "would this read as visible motion" only.
_REFERENCE_OUTPUT_WIDTH = 1280
_REFERENCE_OUTPUT_HEIGHT = 720
_MIN_DRIFT_PX = 60.0
_MIN_SCALE_DELTA = 0.20
_ZOOM_FAMILY_PREFIXES = ("push", "pull", "reveal")


def _enforce_min_velocity(
    motion_type: str,
    start_scale: float,
    end_scale: float,
    drift_x: float,
    drift_y: float,
) -> tuple[float, float, float, float]:
    """Boost geometry that would render as sub-pixel, invisible motion.

    Below ~1 output pixel of total travel, zoompan's per-frame integer
    rounding dominates the intended continuous motion and reads as shake
    instead of a deliberate pan/zoom (see ffmpeg_filters' sub-pixel
    smoothing for the render-side half of this fix). Breathing/tripod are
    excluded — intentionally subtle, and capped to short scenes instead
    (see the >8s override in _plan_generated).
    """
    if motion_type.startswith("drift"):
        # drift_x is a fraction of frame width, drift_y a fraction of
        # height — each checked against its own axis's reference pixel
        # count, not both against width.
        if 0.0 < abs(drift_x) * _REFERENCE_OUTPUT_WIDTH < _MIN_DRIFT_PX:
            sign = 1.0 if drift_x > 0 else -1.0
            drift_x = sign * (_MIN_DRIFT_PX / _REFERENCE_OUTPUT_WIDTH)
        if 0.0 < abs(drift_y) * _REFERENCE_OUTPUT_HEIGHT < _MIN_DRIFT_PX:
            sign = 1.0 if drift_y > 0 else -1.0
            drift_y = sign * (_MIN_DRIFT_PX / _REFERENCE_OUTPUT_HEIGHT)
    elif motion_type.startswith(_ZOOM_FAMILY_PREFIXES):
        if abs(end_scale - start_scale) < _MIN_SCALE_DELTA:
            if end_scale >= start_scale:
                end_scale = start_scale + _MIN_SCALE_DELTA
            else:
                start_scale = end_scale + _MIN_SCALE_DELTA

    return start_scale, end_scale, drift_x, drift_y


# ── Motion type → geometry resolver ──────────────────────────────────────────


def _resolve_motion(
    motion_type: str,
    scale_tier: str,
    cfg: ProfileConfig,
    scene_index: int,
    scene_duration: float = 5.0,
    shot_type: str = "",
) -> tuple[float, float, float, float, float, float]:
    """
    Resolve (start_scale, end_scale, anchor_x, anchor_y, drift_x, drift_y)
    from a motion_type + scale_tier + profile config.

    scene_index is used only to alternate drift direction so consecutive
    drift scenes don't all pan in the same direction.

    scene_duration is used to scale drift_amount and the zoom range with scene
    length so shorter scenes feel brisk and longer scenes maintain deliberate
    continuous movement without fading to a static hold.

    Zoom range scales as: start = 1.0, end = 1.0 + (hi - 1.0) * duration_factor.
    This makes long scenes more dynamic (larger zoom) and short scenes subtler.

    shot_type (optional) applies a composition-aware anchor adjustment after
    geometry is resolved — see _apply_shot_type_anchor.
    """
    base_lo, base_hi = {
        "small": cfg.scale_range_small,
        "medium": cfg.scale_range_medium,
        "large": cfg.scale_range_large,
    }.get(scale_tier, cfg.scale_range_medium)

    duration_factor = max(
        1.0, min(scene_duration / cfg.reference_duration_seconds, cfg.max_drift_scale_factor)
    )
    lo = 1.0 + (base_lo - 1.0) * duration_factor
    hi = 1.0 + (base_hi - 1.0) * duration_factor
    d = cfg.drift_amount * duration_factor
    # Alternate drift direction by index (even = left→right, odd = right→left)
    drift_sign = 1.0 if scene_index % 2 == 0 else -1.0

    match motion_type:
        case "static":
            result = (1.0, 1.0, 0.5, 0.5, 0.0, 0.0)

        case "push_in":
            result = (lo, hi, 0.5, 0.5, 0.0, 0.0)

        case "push_in_slow":
            # Half the normal zoom range — weighted, unhurried
            mid = lo + (hi - lo) * 0.5
            result = (lo, mid, 0.5, 0.5, 0.0, 0.0)

        case "push_in_fast":
            # Uses the large scale range regardless of tier argument
            _, hi_large = cfg.scale_range_large
            result = (lo, hi_large, 0.5, 0.5, 0.0, 0.0)

        case "pull_out":
            result = (hi, lo, 0.5, 0.5, 0.0, 0.0)

        case "pull_out_wide":
            # Starts more zoomed in → bigger reveal
            _, hi_large = cfg.scale_range_large
            result = (hi_large, 1.0, 0.5, 0.5, 0.0, 0.0)

        case "drift":
            # Constant slight zoom; motion comes from horizontal x shift
            zoom = (
                1.0 + d if d > 0 else 1.04
            )  # enough headroom to pan without black bars
            result = (zoom, zoom, 0.5, 0.5, d * drift_sign, 0.0)

        case "tilt_up":
            # Camera rises: anchor near centre so zoom gives headroom for upward pan.
            # drift_y scales the full drift amount for a visible vertical travel.
            result = (lo, hi, 0.5, 0.45, 0.0, d)

        # ── New cinematic motion types ───────────────────────────────────────
        # Zoom family (push/pull/reveal): compound motion — primary movement
        # via start/end scale, plus a small secondary y drift toward the
        # subject anchor and alternating x micro-lateral drift, both capped
        # at _SECONDARY_DRIFT_CAP. Where the type table gives an explicit
        # drift value, that explicit value is used as-is instead.

        case "push_slow":
            # sy deliberately bypasses _cap_secondary — 0.025 is an explicit
            # per-type target (visibility fix), not the generic ±0.008 rule.
            end = _scale_endpoint(1.2692, duration_factor)
            sx = _cap_secondary(0.005 * duration_factor * drift_sign)
            sy = 0.025 * duration_factor
            result = (1.0, end, 0.5, 0.5, sx, sy)

        case "push_emotional":
            end = _scale_endpoint(1.30, duration_factor)
            sx = _cap_secondary(0.005 * duration_factor * drift_sign)
            sy = 0.030 * duration_factor
            result = (1.0, end, 0.5, 0.45, sx, sy)

        case "push_hero":
            end = _scale_endpoint(1.40, duration_factor)
            sx = _cap_secondary(0.005 * duration_factor * drift_sign)
            sy = 0.035 * duration_factor
            result = (1.0, end, 0.5, 0.45, sx, sy)

        case "push_reveal":
            start = _scale_endpoint(1.2154, duration_factor)
            sx = _cap_secondary(0.005 * duration_factor * drift_sign)
            sy = _cap_secondary(0.008 * duration_factor)
            result = (start, 1.0, 0.5, 0.5, sx, sy)

        case "push_suspense":
            # sy secondary removed (was 0.045 * duration_factor) — it drove
            # a perpendicular drift on top of the push, which combined with
            # a separate easing curve to produce a wobble.
            end = _scale_endpoint(1.2154, duration_factor)
            sx = _cap_secondary(0.005 * duration_factor * drift_sign)
            sy = 0.0
            result = (1.0, end, 0.5, 0.55, sx, sy)

        case "pull_reflection":
            start = _scale_endpoint(1.15, duration_factor)
            sx = _cap_secondary(0.005 * duration_factor * drift_sign)
            sy = _cap_secondary(0.008 * duration_factor)
            result = (start, 1.0, 0.5, 0.5, sx, sy)

        case "pull_isolation":
            start = _scale_endpoint(1.20, duration_factor)
            sx = _cap_secondary(0.005 * duration_factor * drift_sign)
            sy = _cap_secondary(0.008 * duration_factor)
            result = (start, 1.0, 0.5, 0.4, sx, sy)

        case "pull_ending":
            start = _scale_endpoint(1.2154, duration_factor)
            sx = _cap_secondary(0.005 * duration_factor * drift_sign)
            sy = _cap_secondary(0.008 * duration_factor)
            result = (start, 1.0, 0.5, 0.5, sx, sy)

        case "pull_wide":
            start = _scale_endpoint(1.25, duration_factor)
            sx = _cap_secondary(0.005 * duration_factor * drift_sign)
            sy = _cap_secondary(0.008 * duration_factor)
            result = (start, 1.0, 0.5, 0.5, sx, sy)

        case "reveal_corner":
            start = _scale_endpoint(1.20, duration_factor)
            sx = _cap_secondary(0.005 * duration_factor * drift_sign)
            sy = _cap_secondary(0.008 * duration_factor)
            result = (start, 1.0, 0.15, 0.15, sx, sy)

        case "reveal_window":
            start = _scale_endpoint(1.30, duration_factor)
            sx = _cap_secondary(0.005 * duration_factor * drift_sign)
            sy = _cap_secondary(0.008 * duration_factor)
            result = (start, 1.0, 0.5, 0.5, sx, sy)

        case "reveal_light":
            start = _scale_endpoint(1.15, duration_factor)
            sx = _cap_secondary(0.005 * duration_factor * drift_sign)
            sy = _cap_secondary(0.008 * duration_factor)
            result = (start, 1.0, 0.5, 0.4, sx, sy)

        case "reveal_subject":
            start = _scale_endpoint(1.25, duration_factor)
            end = _scale_endpoint(1.05, duration_factor)
            sx = _cap_secondary(0.005 * duration_factor * drift_sign)
            sy = _cap_secondary(0.008 * duration_factor)
            result = (start, end, 0.5, 0.45, sx, sy)

        # Drift family: primary travel as specified, plus a secondary
        # perpendicular component at 30% of the primary magnitude.

        case "drift_float":
            # start/end scale raised so _clamp_drift's crop-safety room
            # (room = 1 - 1/zoom, split around the center anchor) can
            # actually admit the full 0.12 primary travel instead of capping
            # it back down. dx is the PRIMARY axis. z is held constant
            # (start == end) and the perpendicular dy is zeroed — drift
            # motion is a clean linear pan on one axis only, no wobble.
            z = _scale_endpoint(1.5385, duration_factor)
            dx = 0.12 * duration_factor * drift_sign
            dy = 0.0
            result = (z, z, 0.5, 0.5, dx, dy)

        case "drift_horizon":
            z = _scale_endpoint(1.5385, duration_factor)
            dx = 0.15 * duration_factor * drift_sign
            dy = 0.0
            result = (z, z, 0.5, 0.5, dx, dy)

        case "drift_vertical_up":
            z = _scale_endpoint(1.18, duration_factor)
            dy = 0.12 * duration_factor
            dx = 0.0
            result = (z, z, 0.5, 0.6, dx, dy)

        case "drift_vertical_down":
            # dy is negative: anchor_y=0.4 combined with this zoom already
            # sits the crop window right at the top edge (y=0) at rest, so
            # a positive drift_y (doc convention: positive = bottom->top)
            # pushes straight into that same boundary and gets clipped flat
            # for the whole clip — zero visible motion despite a nonzero
            # value. Negative drift_y moves the window down into the room
            # available below instead, which is where "vertical_down" is
            # actually supposed to pan.
            z = _scale_endpoint(1.1923, duration_factor)
            dy = -0.13 * duration_factor
            dx = 0.0
            result = (z, z, 0.5, 0.4, dx, dy)

        case "drift_river":
            z = _scale_endpoint(1.5385, duration_factor)
            dx = 0.10 * duration_factor * drift_sign
            dy = 0.0
            result = (z, z, 0.5, 0.5, dx, dy)

        # Hold / breathing family: build_zoompan_filter special-cases these
        # motion_type names and derives a sinusoidal oscillation from
        # start_scale (used as the baseline) and scene duration — the
        # start/end values here are the shared baseline, not a linear range.

        case "hold_breathing":
            result = (1.020, 1.020, 0.5, 0.5, 0.0, 0.0)

        case "hold_tripod":
            # Small alternating-by-scene-index lateral amplitude, carried in
            # drift_x for build_zoompan_filter's breathing dispatch to read.
            # 0.012 (not the doc's literal 0.004) — empirically verified as
            # the threshold where the oscillation reads as visible motion
            # rather than static (see hold_breathing amplitude below).
            amp = 0.012 * drift_sign
            result = (1.02, 1.02, 0.5, 0.5, amp, 0.0)

        case "hold_locked":
            # Exact static — build_zoompan_filter routes this to the plain
            # scale+crop path, same as 'static'. Geometry here is bookkeeping
            # only (never drives a real zoompan expression).
            result = (1.0, 1.0, 0.5, 0.5, 0.0, 0.0)

        # Macro family: explicit primary/secondary drift pairs from the type
        # table — larger zoom gives more crop headroom than a typical zoom
        # motion, so these are not subject to _SECONDARY_DRIFT_CAP.

        case "macro_detail":
            start = _scale_endpoint(1.3692, duration_factor)
            end = _scale_endpoint(1.6308, duration_factor)
            dx = 0.01 * duration_factor * drift_sign
            result = (start, end, 0.5, 0.5, dx, 0.0)

        case "macro_breathing":
            result = (1.40, 1.40, 0.5, 0.5, 0.0, 0.0)

        case "macro_drift":
            # end == start (constant scale) — drift carries the motion.
            start = _scale_endpoint(1.3231, duration_factor)
            end = _scale_endpoint(1.3231, duration_factor)
            dx = 0.10 * duration_factor * drift_sign
            dy = 0.05 * duration_factor
            result = (start, end, 0.5, 0.5, dx, dy)

        case _:
            logger.warning(
                "_resolve_motion: unrecognized motion_type %r for scene_index=%s — "
                "falling back to drift. "
                "Tier 2 types (fog/dust/particles/light_rays) are deferred; "
                "add explicit case branches when assets are available.",
                motion_type,
                scene_index,
            )
            result = (1.0, 1.04, 0.5, 0.5, d * drift_sign, 0.0)

    start_s, end_s, ax, ay, dx, dy = result
    ax, ay = _apply_shot_type_anchor(ax, ay, shot_type)
    return start_s, end_s, ax, ay, dx, dy


# ── Asset scene → MotionSpec ──────────────────────────────────────────────────


def _asset_motion(scene: dict, cfg: ProfileConfig) -> MotionSpec:
    """
    Convert an existing 'animation' string (Asset Scene System V1) into a
    MotionSpec so the renderer uses a single unified code path.

    If no animation is set, defaults to slow_zoom. Unrecognized animation
    strings also fall back to slow_zoom instead of static, to prevent a
    plain asset scene from rendering as a frozen frame.

    brand_card is the one exception: it always renders fully static
    (no zoom/pan/drift) regardless of any 'animation' value present —
    a plain held cut, not a Ken Burns shot.
    """
    if scene.get("scene_type") == "brand_card":
        return MotionSpec(
            motion_type="static",
            start_scale=1.0,
            end_scale=1.0,
            anchor_x=0.5,
            anchor_y=0.5,
            drift_x=0.0,
            drift_y=0.0,
            easing=cfg.easing,
            emotion="asset",
        )

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
            logger.warning(
                "_asset_motion: unrecognized animation %r — "
                "falling back to slow_zoom. Expected: slow_zoom, slow_zoom_out, drift.",
                animation,
            )
            ss, es, ax, ay, dx, dy = (1.0, hi, 0.5, 0.5, 0.0, 0.0)
            mtype = "push_in"

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


# ── Visual metadata secondary signal (CHANGE 3) ──────────────────────────────

_SHOT_TYPE_PREFERENCE: dict[str, tuple[str, str]] = {
    "drone_shot": ("pull_wide", "large"),
    "aerial": ("pull_wide", "large"),
    "close_up": ("hold_breathing", "small"),
    "extreme_close": ("hold_breathing", "small"),
    "macro_shot": ("macro_detail", "large"),
    "wide_shot": ("drift_float", "small"),
    "establishing": ("drift_float", "small"),
    "tracking_shot": ("drift_river", "medium"),
}

_MOOD_PREFERENCE: dict[str, tuple[str, str]] = {
    "MYSTERIOUS": ("push_suspense", "small"),
    "REVERENT": ("push_slow", "small"),
    "FEARFUL": ("push_suspense", "medium"),
    "HOPEFUL": ("drift_vertical_up", "small"),
    "DETERMINED": ("push_emotional", "medium"),
}

_TIER_DOWN: dict[str, str] = {"large": "medium", "medium": "small", "small": "small"}

_NARRATIVE_ROLE_PREFERENCE: dict[str, tuple[str, str]] = {
    "ESTABLISHING": ("pull_wide", "medium"),
    "CTA": ("hold_locked", "small"),
    "METAPHOR": ("reveal_light", "small"),
    "RESOLUTION": ("pull_ending", "medium"),
}


def _motion_family(motion_type: str) -> str:
    return motion_type.split("_")[0]


def _apply_visual_metadata_overrides(
    scene: dict, motion_type: str, scale_tier: str
) -> tuple[str, str]:
    """Soft secondary-signal adjustment using shot_type/mood/narrative_role,
    applied after the primary emotion-driven selection.

    Priority: shot_type > mood > narrative_role for motion_type swaps (mood's
    PEACEFUL scale-down is independent and always applies). A swap is only
    made when the candidate is not already in the same motion family as the
    current choice, so a stronger primary result (e.g. push_hero) is never
    diluted by a softer secondary signal (e.g. push_slow).
    """
    shot_type = scene.get("shot_type", "")
    visual_metadata = scene.get("visual_metadata") or {}
    mood = visual_metadata.get("mood", "")
    narrative_role = visual_metadata.get("narrative_role", "")

    swapped = False

    candidate = _SHOT_TYPE_PREFERENCE.get(shot_type)
    if candidate and _motion_family(candidate[0]) != _motion_family(motion_type):
        motion_type, scale_tier = candidate
        swapped = True

    if mood == "PEACEFUL":
        scale_tier = _TIER_DOWN.get(scale_tier, scale_tier)

    if not swapped:
        candidate = _MOOD_PREFERENCE.get(mood)
        if candidate and _motion_family(candidate[0]) != _motion_family(motion_type):
            motion_type, scale_tier = candidate
            swapped = True

    if not swapped:
        candidate = _NARRATIVE_ROLE_PREFERENCE.get(narrative_role)
        if candidate and _motion_family(candidate[0]) != _motion_family(motion_type):
            motion_type, scale_tier = candidate

    return motion_type, scale_tier


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
        emotional_intensity: dict[int, str] | None = None,
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
            emotional_intensity: Optional mapping of scene index -> intensity
                ("normal" | "emotional" | "peak" | "reflection"). When provided,
                overrides scale tier and motion type per scene.

        Returns:
            The same scene list with 'motion' added to every scene.
        """
        cfg = get_profile_config(profile)
        total = len(scenes)

        prev_motion_type = None
        repeat_count = 0

        for scene in scenes:
            scene_position = (
                (scene["index"] - 1) / max(total - 1, 1) if total > 1 else 0.5
            )
            scene_type = scene.get("scene_type", "generated_image")
            intensity = "normal"
            if emotional_intensity is not None:
                intensity = emotional_intensity.get(scene["index"], "normal")

            if scene_type in ("asset", "brand_card"):
                spec = _asset_motion(scene, cfg)
            else:
                spec = self._plan_generated(scene, scene_position, cfg, intensity)

            motion_type = spec.motion_type
            if prev_motion_type == motion_type:
                repeat_count += 1
            else:
                repeat_count = 1

            # brand_card must stay static — never swapped out by the
            # repeat-run variety override below.
            if repeat_count >= 3 and scene_type != "brand_card":
                scene_duration = float(scene.get("duration_seconds", 5.0))
                shot_type = scene.get("shot_type", "")
                alts = []
                seen: set[str] = set()
                for mt, _ in cfg.motion_map.values():
                    if mt != motion_type and mt not in seen:
                        alts.append(mt)
                        seen.add(mt)
                if alts:
                    alt = alts[(scene["index"] - 1) % len(alts)]
                    scale_tier = next(
                        (st for mt, st in cfg.motion_map.values() if mt == alt),
                        next(
                            (st for mt, st in cfg.motion_map.values() if mt == motion_type),
                            "medium",
                        ),
                    )
                    start_s, end_s, ax, ay, dx, dy = _resolve_motion(
                        alt, scale_tier, cfg, scene["index"], scene_duration, shot_type
                    )
                    start_s, end_s, dx, dy = _enforce_min_velocity(
                        alt, start_s, end_s, dx, dy
                    )
                    spec = MotionSpec(
                        motion_type=alt,
                        start_scale=round(start_s, 4),
                        end_scale=round(end_s, 4),
                        anchor_x=ax,
                        anchor_y=ay,
                        drift_x=round(dx, 4),
                        drift_y=round(dy, 4),
                        easing=_resolve_easing(alt, cfg),
                        emotion=spec.emotion,
                    )
                    repeat_count = 1

            scene["motion"] = spec.to_dict()
            prev_motion_type = spec.motion_type

        return scenes

    def _plan_generated(
        self,
        scene: dict,
        scene_position: float,
        cfg: ProfileConfig,
        emotional_intensity: str = "normal",
    ) -> MotionSpec:
        """Classify emotion and assign motion for an AI-generated scene."""
        narration = scene.get("narration", "")
        profile_map = cfg.motion_map

        # Reuse the TTS emotion classifier — same 12-emotion system
        emotion_profile = classify_scene(narration, scene_position)
        emotion_name = emotion_profile.emotion.value  # e.g. "curiosity"

        motion_type, scale_tier = profile_map.get(emotion_name, ("drift", "small"))

        # CHANGE 3 — visual metadata secondary signal. Soft override only;
        # the emotional-intensity override below always takes priority.
        if emotional_intensity not in ("peak", "emotional"):
            motion_type, scale_tier = _apply_visual_metadata_overrides(
                scene, motion_type, scale_tier
            )

        # Override motion type and scale tier based on emotional intensity
        if emotional_intensity == "peak":
            motion_type = "push_in_slow"
            scale_tier = "large"
        elif emotional_intensity == "emotional":
            scale_tier = "medium"
        elif emotional_intensity == "reflection":
            motion_type = "drift"
            scale_tier = "small"

        scene_duration = float(scene.get("duration_seconds", 5.0))

        # Breathing/tripod are subtle by design — fine for a short held
        # shot, but on a long scene the near-static oscillation reads as
        # "nothing is happening" rather than a deliberate slow hold.
        if motion_type in ("hold_breathing", "hold_tripod") and scene_duration > 8.0:
            motion_type = "drift_float"
            scale_tier = "small"

        shot_type = scene.get("shot_type", "")
        start_s, end_s, ax, ay, dx, dy = _resolve_motion(
            motion_type, scale_tier, cfg, scene["index"], scene_duration, shot_type
        )
        start_s, end_s, dx, dy = _enforce_min_velocity(motion_type, start_s, end_s, dx, dy)

        return MotionSpec(
            motion_type=motion_type,
            start_scale=round(start_s, 4),
            end_scale=round(end_s, 4),
            anchor_x=ax,
            anchor_y=ay,
            drift_x=round(dx, 4),
            drift_y=round(dy, 4),
            easing=_resolve_easing(motion_type, cfg),
            emotion=emotion_name,
        )
