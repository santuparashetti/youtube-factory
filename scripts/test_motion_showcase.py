"""Standalone motion showcase — renders one clip per motion type and measures
whether the resulting motion is actually visible.

Forces each motion type directly through _resolve_motion() (bypassing the
emotion classifier) so every type gets exercised regardless of what the
emotion map currently routes to.

Usage:
    uv run python3 scripts/test_motion_showcase.py
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

from video_core.cinematic.ffmpeg_filters import build_zoompan_filter
from video_core.cinematic.motion import _resolve_easing, _resolve_motion
from video_core.cinematic.profiles import get_profile_config

MOTION_TYPES = [
    "push_slow", "push_emotional", "push_hero", "push_reveal", "push_suspense",
    "pull_reflection", "pull_isolation", "pull_ending", "pull_wide",
    "drift_float", "drift_horizon", "drift_vertical_up", "drift_vertical_down",
    "drift_river", "hold_breathing", "hold_tripod",
    "reveal_corner", "reveal_window", "reveal_light", "reveal_subject",
    "macro_detail", "macro_drift",
]

WIDTH, HEIGHT, FPS = 1280, 720, 30
DURATION = 6.5
OUT_DIR = Path("/tmp/motion_showcase")

VISIBLE_THRESHOLD = 25.0
WEAK_THRESHOLD = 10.0


def _find_test_image() -> Path:
    for candidate in sorted(Path("workspace/jobs").glob("*/images/*.png")):
        return candidate
    raise FileNotFoundError("No PNG found under workspace/jobs/*/images/ — run any job through generate-images first.")


def _mean_pixel_diff(clip: Path) -> float:
    first = OUT_DIR / f"{clip.stem}_first.png"
    last = OUT_DIR / f"{clip.stem}_last.png"
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(clip), "-vf", "select=eq(n\\,0)", "-vframes", "1", str(first)],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["ffmpeg", "-y", "-sseof", "-0.1", "-i", str(clip), "-vframes", "1", str(last)],
        check=True, capture_output=True,
    )
    a = np.asarray(Image.open(first).convert("L"), dtype=np.float32)
    b = np.asarray(Image.open(last).convert("L"), dtype=np.float32)
    return float(np.abs(a - b).mean())


def _classify(diff: float) -> str:
    if diff > VISIBLE_THRESHOLD:
        return "VISIBLE"
    if diff >= WEAK_THRESHOLD:
        return "WEAK"
    return "STATIC"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    image = _find_test_image()
    cfg = get_profile_config("cinematic")

    print(f"Test image: {image}")
    print(f"Output dir: {OUT_DIR}")
    print()

    rows: list[tuple[str, str, float, str]] = []

    for i, motion_type in enumerate(MOTION_TYPES):
        scene_index = 1 if i % 2 == 0 else 2
        start, end, ax, ay, dx, dy = _resolve_motion(
            motion_type, "medium", cfg, scene_index, DURATION
        )
        motion = {
            "motion_type": motion_type,
            "start_scale": start,
            "end_scale": end,
            "anchor_x": ax,
            "anchor_y": ay,
            "drift_x": dx,
            "drift_y": dy,
            "easing": _resolve_easing(motion_type, cfg),
        }
        vf = build_zoompan_filter(WIDTH, HEIGHT, FPS, motion, DURATION, supersample=2)

        clip = OUT_DIR / f"{motion_type}.mp4"
        subprocess.run(
            [
                "ffmpeg", "-y", "-loop", "1", "-framerate", str(FPS), "-i", str(image),
                "-vf", vf, "-t", str(DURATION),
                "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                str(clip),
            ],
            check=True, capture_output=True,
        )

        diff = _mean_pixel_diff(clip)
        verdict = _classify(diff)
        rows.append((motion_type, f"{start:.3f}→{end:.3f}", diff, verdict))
        print(f"{motion_type:22s} | {start:.3f}→{end:.3f} | diff={diff:6.2f} | {verdict}")

    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"{'motion_type':22s} | {'scale':13s} | {'diff':>7s} | verdict")
    print("-" * 60)
    for motion_type, scale_range, diff, verdict in rows:
        print(f"{motion_type:22s} | {scale_range:13s} | {diff:7.2f} | {verdict}")

    n_visible = sum(1 for r in rows if r[3] == "VISIBLE")
    n_weak = sum(1 for r in rows if r[3] == "WEAK")
    n_static = sum(1 for r in rows if r[3] == "STATIC")
    print("-" * 60)
    print(f"VISIBLE: {n_visible}  WEAK: {n_weak}  STATIC: {n_static}  (total {len(rows)})")


if __name__ == "__main__":
    main()
