"""Standalone FFmpeg filter-string builders for pan/zoom (Ken Burns) motion.

These functions are pure — no I/O, no Settings, no side effects.
They accept all parameters explicitly so they work at any target resolution,
including portrait formats (e.g. 1080×1920 for shorts).

Primary public API:
    build_zoompan_filter(width, height, fps, motion, duration_hint) -> str
    build_scale_crop_filter(width, height) -> str
"""

from __future__ import annotations


def _t_factor(total_frames: int, easing: str) -> str:
    """Return an FFmpeg expression for the time interpolation factor t ∈ [0, 1].

    Uses exact normalization so the final frame reaches t=1.0 exactly,
    ensuring end_scale is fully reached rather than undershooting.

    linear:       t = on / (total_frames - 1)
    ease_in_out:  smoothstep(t) = t²·(3 − 2t)  — no pow() needed
    """
    inv_n = 1.0 / max(total_frames - 1, 1)
    t = f"(on)*{inv_n:.8f}"
    if easing == "ease_in_out":
        return f"({t})*({t})*(3-2*({t}))"
    return t


def build_scale_crop_filter(width: int, height: int) -> str:
    """Return a static scale+crop filter string (no motion, no zoompan overhead)."""
    return (
        f"scale={width}:{height}:"
        "force_original_aspect_ratio=increase,"
        f"crop={width}:{height}"
    )


def build_zoompan_filter(
    width: int,
    height: int,
    fps: int,
    motion: dict,
    duration_hint: float,
    supersample: int = 1,
) -> str:
    """Build the spatial/motion filter chain from a MotionSpec dict.

    Works at any target resolution — pass 1920×1080 for landscape or
    1080×1920 for portrait (shorts). Does NOT include a subtitle filter;
    callers append that separately.

    Static motion uses a fast scale+crop path (no zoompan overhead).
    All animated motions drive a zoompan expression via start/end scale,
    anchor point, optional drift, and easing.

    Supersampling (supersample > 1) renders zoompan at a higher internal
    resolution then downscales with lanczos to suppress sub-pixel rounding
    jitter.

    Args:
        width:         Target frame width in pixels.
        height:        Target frame height in pixels.
        fps:           Frames per second.
        motion:        MotionSpec dict (keys: motion_type, start_scale,
                       end_scale, anchor_x, anchor_y, drift_x, drift_y, easing).
        duration_hint: Approximate scene duration in seconds.
        supersample:   Internal render scale factor (1 = disabled).

    Returns:
        FFmpeg -vf filter string (no leading/trailing comma).
    """
    motion_type = motion.get("motion_type", "static")
    start_scale = float(motion.get("start_scale", 1.0))
    end_scale = float(motion.get("end_scale", 1.0))
    anchor_x = float(motion.get("anchor_x", 0.5))
    anchor_y = float(motion.get("anchor_y", 0.5))
    drift_x = float(motion.get("drift_x", 0.0))
    drift_y = float(motion.get("drift_y", 0.0))
    easing = motion.get("easing", "linear")

    if motion_type == "static":
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
    t = _t_factor(total_frames, easing)

    # Zoom — absolute formula: no dependency on initial 'zoom' state
    dz = end_scale - start_scale
    z_expr = f"'{start_scale:.4f}+{dz:.6f}*({t})'"

    # Pan — anchor keeps focus stable while zoom changes;
    # drift adds slow horizontal / vertical travel.
    # drift_x > 0 → camera pans left→right (x increases in input coords)
    # drift_y > 0 → camera tilts up (y decreases in FFmpeg coords → minus sign)
    raw_dx = float(motion.get("drift_x", 0.0))
    raw_dy = float(motion.get("drift_y", 0.0))

    def _clamp_drift(
        drift: float,
        anchor: float,
        start_zoom: float,
        end_zoom: float,
    ) -> float:
        if abs(drift) < 1e-9:
            return drift
        worst_zoom = min(start_zoom, end_zoom)
        x0 = anchor - 1.0 / (2.0 * worst_zoom)
        upper = 1.0 - 1.0 / worst_zoom
        room = min(upper - x0, x0)
        if abs(drift) > room and room > 1e-9:
            return room * (1.0 if drift > 0 else -1.0)
        return drift

    drift_x = _clamp_drift(raw_dx, anchor_x, start_scale, end_scale)
    drift_y = _clamp_drift(raw_dy, anchor_y, start_scale, end_scale)

    dx = f"+iw*{drift_x:.6f}*({t})" if abs(drift_x) > 1e-6 else ""
    dy = f"-ih*{drift_y:.6f}*({t})" if abs(drift_y) > 1e-6 else ""

    # Clamp to [0, zoom*iw - width] / [0, zoom*ih - height] — allows the full pan
    # range the zoompan filter actually supports while still preventing black-bars.
    x_expr = f"'max(0,min(iw*{anchor_x:.4f}-iw/(2*zoom){dx},iw*zoom-{out_w}))'"
    y_expr = f"'max(0,min(ih*{anchor_y:.4f}-ih/(2*zoom){dy},ih*zoom-{out_h}))'"

    return (
        f"{prefix}zoompan=z={z_expr}:x={x_expr}:y={y_expr}"
        f":d=1:s={out_w}x{out_h}:fps={fps}{suffix}"
    )
