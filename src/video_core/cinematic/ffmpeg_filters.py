"""Standalone FFmpeg filter-string builders for pan/zoom (Ken Burns) motion.

These functions are pure — no I/O, no Settings, no side effects.
They accept all parameters explicitly so they work at any target resolution,
including portrait formats (e.g. 1080×1920 for shorts).

Primary public API:
    build_zoompan_filter(width, height, fps, motion, duration_hint) -> str
    build_scale_crop_filter(width, height) -> str
"""

from __future__ import annotations

import logging
import math

logger = logging.getLogger(__name__)

_HALF_PI = math.pi / 2
_TWO_PI = 2 * math.pi

# Anti-jerk RULE 10: max safe scale change per frame (0.45/s @ 30fps).
_MAX_SCALE_VELOCITY_PER_FRAME = 0.015

# Motion types that oscillate around a baseline scale instead of
# interpolating linearly from start_scale to end_scale.
_BREATHING_MOTION_TYPES = frozenset({"hold_breathing", "macro_breathing", "hold_tripod"})


def _t_factor(
    total_frames: int,
    easing: str,
    fade_in_frames: int = 0,
    fade_out_frames: int = 0,
) -> str:
    """Return an FFmpeg expression for the time interpolation factor t ∈ [0, 1].

    RULE 1: uses inv_n = 1/max(total_frames-1, 1) — never divides by
    (total_frames-1) directly, avoiding division by zero on single-frame
    scenes.

    RULE 7: when fade_in_frames/fade_out_frames are given, motion is delayed
    until the fade-in completes and finishes before the fade-out begins —
    t is computed from (on - fade_in_frames) over the active (non-fade)
    window instead of from on=0 over the full clip.

    RULE 2 + 3: every curve reaches exactly 0.0 at on=0 (or on=fade_in_frames)
    and exactly 1.0 at on=total_frames-1 (or the start of the fade-out
    window), with an explicit clamp so floating point drift can never push
    the result outside [0, 1].

    linear:       t
    ease_in:      t^2
    ease_out:     1-(1-t)^2
    ease_in_out:  smoothstep(t) = t^2*(3-2t)
    smoothstep:   same as ease_in_out, exposed under its own name
    sine:         sin(PI/2*t)               — fast start, eases into the end
    sine_power:   sin(PI/2*t)^1.8           — asymmetric, lingers at start
    cubic:        t^3
    quint:        t^5
    settle:       sin(PI/2*t)^0.7           — fast start, long settle
    """
    active_frames = max(total_frames - fade_in_frames - fade_out_frames, 1)
    inv_active = 1.0 / max(active_frames - 1, 1)

    if fade_in_frames:
        raw_t = f"(on-{fade_in_frames})*{inv_active:.8f}"
    else:
        raw_t = f"(on)*{inv_active:.8f}"

    # Only pay for the clamp wrapper when a fade window is actually in play —
    # keeps the common (no-transition) expression identical to before.
    t = f"max(0,min(1,{raw_t}))" if (fade_in_frames or fade_out_frames) else raw_t

    match easing:
        case "linear":
            curve = t
        case "ease_in":
            curve = f"({t})*({t})"
        case "ease_out":
            curve = f"(1-(1-({t}))*(1-({t})))"
        case "ease_in_out" | "smoothstep":
            curve = f"({t})*({t})*(3-2*({t}))"
        case "sine":
            curve = f"sin({_HALF_PI:.10f}*({t}))"
        case "sine_power":
            curve = f"pow(sin({_HALF_PI:.10f}*({t})),1.8)"
        case "cubic":
            curve = f"({t})*({t})*({t})"
        case "quint":
            curve = f"({t})*({t})*({t})*({t})*({t})"
        case "settle":
            curve = f"pow(sin({_HALF_PI:.10f}*({t})),0.7)"
        case _:
            curve = t

    return f"max(0,min(1,{curve}))"


def _clamp_drift(
    drift: float,
    anchor: float,
    start_zoom: float,
    end_zoom: float,
) -> float:
    """Clamp a drift value so the pan never crops outside the image bounds.

    RULE 6: applied to every drift value inserted into a filter expression,
    including the secondary/micro drifts added to compound motions.
    """
    if abs(drift) < 1e-9:
        return drift
    worst_zoom = min(start_zoom, end_zoom)
    x0 = anchor - 1.0 / (2.0 * worst_zoom)
    upper = 1.0 - 1.0 / worst_zoom
    room = min(upper - x0, x0)
    if abs(drift) > room and room > 1e-9:
        return room * (1.0 if drift > 0 else -1.0)
    return drift


_MIN_PER_FRAME_PX = 0.5


def _drift_component_expr(
    drift: float,
    out_dim: int,
    dim_var: str,
    t: str,
    active_frames: int,
) -> str:
    """Build one axis's drift term, stepping to whole pixels if too slow.

    A continuous `iw*drift*t` expression moves less than a pixel per frame
    when total travel is small relative to duration — zoompan floors each
    frame's position to an integer pixel anyway, so a sub-pixel-per-frame
    ramp quantizes into an irregular stop/hold/stop pattern that reads as
    shake. Below that threshold, round the total travel to a whole pixel
    count up front and step it directly (`floor(px_count*t)`), which still
    quantizes but does so evenly across the clip instead of by accident.
    """
    if abs(drift) <= 1e-6:
        return ""
    total_px = drift * out_dim
    per_frame_px = abs(total_px) / max(active_frames - 1, 1)
    if per_frame_px < _MIN_PER_FRAME_PX:
        px_count = round(total_px)
        return f"floor({px_count}*({t}))" if px_count != 0 else ""
    return f"{dim_var}*{drift:.6f}*({t})"


def _validate_motion_curve(
    motion_type: str,
    start_scale: float,
    end_scale: float,
    easing: str,
    total_frames: int,
    fps: int,
    fade_in_frames: int,
    fade_out_frames: int,
) -> None:
    """RULE 10 — sanity-check the z curve with plain Python math (no FFmpeg).

    Samples on=0, total_frames//2, total_frames-1 and logs a warning if any
    sample falls outside [1.0, 2.0] or if the implied per-frame scale
    velocity exceeds the safe threshold. The returned filter expression is
    already exact-boundary and floor-clamped by construction (RULE 2/8), so
    this is a diagnostic check only — it does not rewrite the expression.
    """

    def _ease(tt: float) -> float:
        match easing:
            case "ease_in":
                return tt * tt
            case "ease_out":
                return 1 - (1 - tt) * (1 - tt)
            case "ease_in_out" | "smoothstep":
                return tt * tt * (3 - 2 * tt)
            case "sine":
                return math.sin(_HALF_PI * tt)
            case "sine_power":
                return math.sin(_HALF_PI * tt) ** 1.8
            case "cubic":
                return tt**3
            case "quint":
                return tt**5
            case "settle":
                return math.sin(_HALF_PI * tt) ** 0.7
            case _:
                return tt

    active_frames = max(total_frames - fade_in_frames - fade_out_frames, 1)
    inv_active = 1.0 / max(active_frames - 1, 1)

    def _t_at(on: int) -> float:
        raw = (on - fade_in_frames) * inv_active
        return min(1.0, max(0.0, raw))

    samples_on = [0, total_frames // 2, max(total_frames - 1, 0)]
    values = [
        max(1.001, start_scale + (end_scale - start_scale) * _ease(_t_at(n)))
        for n in samples_on
    ]

    if any(v < 1.0 or v > 2.0 for v in values):
        logger.warning(
            "build_zoompan_filter: motion_type=%s sampled scale %s outside [1.0, 2.0]",
            motion_type,
            values,
        )

    for i in range(1, len(values)):
        frame_gap = max(samples_on[i] - samples_on[i - 1], 1)
        velocity = abs(values[i] - values[i - 1]) / frame_gap
        if velocity > _MAX_SCALE_VELOCITY_PER_FRAME:
            logger.warning(
                "build_zoompan_filter: motion_type=%s scale velocity %.5f/frame exceeds "
                "safe threshold %.5f (%.3f/s @ %sfps) — risk of jerky motion",
                motion_type,
                velocity,
                _MAX_SCALE_VELOCITY_PER_FRAME,
                _MAX_SCALE_VELOCITY_PER_FRAME * fps,
                fps,
            )
            break


def build_scale_crop_filter(width: int, height: int) -> str:
    """Return a static scale+crop filter string (no motion, no zoompan overhead)."""
    return (
        f"scale={width}:{height}:"
        "force_original_aspect_ratio=increase,"
        f"crop={width}:{height}"
    )


def _build_breathing_filter(
    motion_type: str,
    motion: dict,
    prefix: str,
    suffix: str,
    out_w: int,
    out_h: int,
    fps: int,
    duration_hint: float,
) -> str:
    """Build a sinusoidal breathing/tripod filter (RULE 4, 5, 6, 8, 9).

    Unlike push/pull/drift motions, breathing motions oscillate around a
    fixed baseline scale rather than interpolating from start to end.
    RULE 5: sin(0) = 0 at on=0, so every scene starts at rest at the
    baseline scale — no cross-scene snap.

    All axes share a single master oscillation (same period, same phase).
    The previous implementation used independent periods per axis
    (z/2.1, x/1.7, y/3.3); those periods drift in and out of phase with
    each other, and at some frames the axes' velocities point opposite
    directions — measured as a velocity sign reversal (e.g. vx flips
    +0.262 -> -0.391 between consecutive frames), which reads as a shake.
    A single shared sine removes that: every axis peaks and troughs
    together, so the camera moves as one coordinated pulse.

    period = duration / 2.3 (not an exact fraction of duration, e.g. not
    duration/2.0) deliberately — an exact integer number of cycles across
    the clip returns the oscillation to (near) its starting phase at the
    last frame, which visibility QA (first-frame vs last-frame pixel diff)
    measures as static even though the motion is clearly visible mid-clip.
    2.3 cycles per clip keeps multiple visible breaths while landing the
    last frame near a phase extreme instead of near a phase repeat.
    """
    baseline = float(motion.get("start_scale", 1.02))
    anchor_x = float(motion.get("anchor_x", 0.5))
    anchor_y = float(motion.get("anchor_y", 0.5))

    safe_duration = max(duration_hint, 0.1)
    period = safe_duration / 2.3
    master = f"sin({_TWO_PI:.10f}*on/({period:.6f}*{fps}))"

    if motion_type == "hold_tripod":
        # amp_x carries the alternating-by-scene-index lateral direction
        # via drift_x's sign (set in motion.py's hold_tripod case). Capped
        # by the ~1.2%-of-frame-width room that baseline zoom 1.02 leaves
        # around center before the crop-boundary floor (see build_zoompan_
        # filter's x_expr) pins the position flat — amplitudes past this
        # plateau produce no further measurable motion at this baseline.
        sign = 1.0 if float(motion.get("drift_x", 0.0)) >= 0 else -1.0
        amp_z, amp_x, amp_y = 0.0, 0.06 * sign, 0.02
    else:
        amp_z, amp_x, amp_y = 0.10, 0.04, 0.06

    if abs(amp_z) > 1e-9:
        z_body = f"{baseline:.4f}+{amp_z:.6f}*{master}"
    else:
        z_body = f"{baseline:.4f}"
    z_expr = f"'max(1.001,{z_body})'"

    dx = f"+iw*{amp_x:.6f}*{master}" if abs(amp_x) > 1e-9 else ""
    dy = f"-ih*{amp_y:.6f}*{master}" if abs(amp_y) > 1e-9 else ""

    x_expr = f"'max(0,min(iw*{anchor_x:.4f}-iw/(2*zoom){dx},iw*zoom-{out_w}))'"
    y_expr = f"'max(0,min(ih*{anchor_y:.4f}-ih/(2*zoom){dy},ih*zoom-{out_h}))'"

    return (
        f"{prefix}zoompan=z={z_expr}:x={x_expr}:y={y_expr}"
        f":d=1:s={out_w}x{out_h}:fps={fps}{suffix}"
    )


def build_zoompan_filter(
    width: int,
    height: int,
    fps: int,
    motion: dict,
    duration_hint: float,
    supersample: int = 1,
    fade_in_frames: int = 0,
    fade_out_frames: int = 0,
) -> str:
    """Build the spatial/motion filter chain from a MotionSpec dict.

    Works at any target resolution — pass 1920×1080 for landscape or
    1080×1920 for portrait (shorts). Does NOT include a subtitle filter;
    callers append that separately.

    Static motion (and hold_locked, its explicit-stillness alias) uses a fast
    scale+crop path (no zoompan overhead). Breathing motions (hold_breathing,
    macro_breathing, hold_tripod) oscillate around a baseline scale. All
    other animated motions drive a zoompan expression via start/end scale,
    anchor point, optional drift, and easing.

    Supersampling (supersample > 1) renders zoompan at a higher internal
    resolution then downscales with lanczos to suppress sub-pixel rounding
    jitter (RULE 9 — the clamp expressions use the supersampled dimensions).

    Args:
        width:           Target frame width in pixels.
        height:          Target frame height in pixels.
        fps:             Frames per second.
        motion:          MotionSpec dict (keys: motion_type, start_scale,
                         end_scale, anchor_x, anchor_y, drift_x, drift_y,
                         easing).
        duration_hint:   Approximate scene duration in seconds.
        supersample:     Internal render scale factor (1 = disabled).
        fade_in_frames:  RULE 7 — frames covered by the incoming transition;
                         motion holds still during this window. Default 0
                         (backward compatible with existing callers).
        fade_out_frames: RULE 7 — frames covered by the outgoing transition;
                         motion finishes before this window begins. Default 0.

    Returns:
        FFmpeg -vf filter string (no leading/trailing comma).
    """
    motion_type = motion.get("motion_type", "static")

    if motion_type in ("static", "hold_locked"):
        return build_scale_crop_filter(width, height)

    if supersample > 1:
        sw = width * supersample
        sh = height * supersample
        prefix = f"scale={sw}:{sh}:flags=lanczos,"
        suffix = f",scale={width}:{height}:flags=lanczos"
        out_w, out_h = sw, sh
    else:
        prefix = ""
        suffix = ""
        out_w, out_h = width, height

    total_frames = max(1, round(duration_hint * fps))

    if motion_type in _BREATHING_MOTION_TYPES:
        return _build_breathing_filter(
            motion_type, motion, prefix, suffix, out_w, out_h, fps, duration_hint
        )

    start_scale = float(motion.get("start_scale", 1.0))
    end_scale = float(motion.get("end_scale", 1.0))
    anchor_x = float(motion.get("anchor_x", 0.5))
    anchor_y = float(motion.get("anchor_y", 0.5))
    easing = motion.get("easing", "linear")

    t = _t_factor(total_frames, easing, fade_in_frames, fade_out_frames)

    # Zoom — absolute formula: no dependency on initial 'zoom' state.
    # RULE 8: floor at 1.001 (not 1.0) — 0.1% safety margin against a
    # zoom-out-past-boundary from floating point evaluation at frame edges.
    dz = end_scale - start_scale
    z_expr = f"'max(1.001,{start_scale:.4f}+{dz:.6f}*({t}))'"

    # Pan — anchor keeps focus stable while zoom changes;
    # drift adds slow horizontal / vertical travel (primary for drift-family
    # motions, or a compound secondary micro-drift for zoom-family motions).
    # drift_x > 0 → camera pans left→right (x increases in input coords)
    # drift_y > 0 → camera tilts up (y decreases in FFmpeg coords → minus sign)
    drift_x = _clamp_drift(
        float(motion.get("drift_x", 0.0)), anchor_x, start_scale, end_scale
    )
    drift_y = _clamp_drift(
        float(motion.get("drift_y", 0.0)), anchor_y, start_scale, end_scale
    )

    active_frames = max(total_frames - fade_in_frames - fade_out_frames, 1)
    dx_body = _drift_component_expr(drift_x, out_w, "iw", t, active_frames)
    dy_body = _drift_component_expr(drift_y, out_h, "ih", t, active_frames)
    dx = f"+{dx_body}" if dx_body else ""
    dy = f"-{dy_body}" if dy_body else ""

    # Clamp to [0, zoom*iw - width] / [0, zoom*ih - height] — allows the full pan
    # range the zoompan filter actually supports while still preventing black-bars.
    x_expr = f"'max(0,min(iw*{anchor_x:.4f}-iw/(2*zoom){dx},iw*zoom-{out_w}))'"
    y_expr = f"'max(0,min(ih*{anchor_y:.4f}-ih/(2*zoom){dy},ih*zoom-{out_h}))'"

    _validate_motion_curve(
        motion_type,
        start_scale,
        end_scale,
        easing,
        total_frames,
        fps,
        fade_in_frames,
        fade_out_frames,
    )

    return (
        f"{prefix}zoompan=z={z_expr}:x={x_expr}:y={y_expr}"
        f":d=1:s={out_w}x{out_h}:fps={fps}{suffix}"
    )
