"""Post-planning motion variety rebalancer (Approach B).

Runs after MotionPlanner to break long consecutive runs of the same motion
type by substituting alternatives from the same emotion's acceptable set.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass

from video_core.cinematic.motion import _enforce_min_velocity
from video_core.cinematic.profiles import get_acceptable_motions

logger = logging.getLogger(__name__)

# CHANGE 5 — cross-scene rhythm pass.
_HOLD_FAMILY = frozenset({"hold_breathing", "hold_tripod", "hold_locked", "static"})
_MOVEMENT_PREFIXES = ("push", "pull", "drift", "reveal")
_RHYTHM_WINDOW = 5
_INTENSITY_RANK = {"normal": 0, "reflection": 1, "emotional": 2, "peak": 3}


def _is_movement(motion_type: str) -> bool:
    return any(motion_type.startswith(prefix) for prefix in _MOVEMENT_PREFIXES)


def _intensity_rank(scene: dict) -> int:
    linked = scene.get("linked_segment") or {}
    intensity = linked.get("emotional_intensity", "normal")
    return _INTENSITY_RANK.get(intensity, 0)


def _reset_motion_geometry(scene: dict, motion_type: str) -> dict:
    """Rebuild start/end scale, anchor, and drift for a motion_type swapped
    in by the rhythm pass — the scene's *previous* motion_type's geometry
    (e.g. a 1.5x push/pull scale) must never leak into the new motion_type,
    since hold_breathing in particular reads start_scale as its oscillation
    baseline (should be ~1.02, not a leftover push/pull extreme)."""
    duration = float(scene.get("duration_seconds", 5.0))
    duration_factor = max(1.0, min(duration / 5.0, 2.0))

    if motion_type == "hold_breathing":
        return {
            "start_scale": 1.020,
            "end_scale": 1.020,
            "anchor_x": 0.5,
            "anchor_y": 0.5,
            "drift_x": 0.0,
            "drift_y": 0.0,
        }

    # drift_float — single axis, no perpendicular wobble (drift-family rule).
    z = round(1.0 + (1.05 - 1.0) * duration_factor, 4)
    drift_sign = 1.0 if scene.get("index", 0) % 2 == 0 else -1.0
    dx = max(-0.012, min(0.012, round(0.03 * duration_factor * drift_sign, 4)))
    z, _, dx, dy = _enforce_min_velocity(motion_type, z, z, dx, 0.0)
    return {
        "start_scale": z,
        "end_scale": z,
        "anchor_x": 0.5,
        "anchor_y": 0.5,
        "drift_x": dx,
        "drift_y": dy,
    }


@dataclass(frozen=True)
class RebalanceConfig:
    """Tuning knobs for the motion rebalancer."""

    max_run_length: int = 2
    """Runs longer than this trigger rebalancing.  Set to 2 so that the
    validator's '3+ consecutive' threshold is always met after rebalancing."""

    rebalance_stride: int = 2
    """Substitute every N-th scene in an over-length run (starting from
    the second).  Use 2 for every-other, 3 for every-third, etc."""


class MotionRebalancer:
    """Post-planning pass that reduces long identical-motion runs.

    Does not change emotion assignments.  Only swaps the rendered motion
    type for a scene with an emotion-compatible alternative when the same
    motion would otherwise appear too many times in a row.
    """

    def __init__(self, config: RebalanceConfig | None = None) -> None:
        self._cfg = config or RebalanceConfig()

    def rebalance(self, scenes: list[dict]) -> list[dict]:
        """Return a new scene list with long motion runs broken up.

        Scenes whose motion is already varied are left untouched.
        """
        if not scenes:
            return scenes

        result = [dict(scene) for scene in scenes]
        lru: deque[str] = deque(maxlen=len(scenes))

        current_motion: str | None = None
        run_start: int = 0

        def _flush_run(end: int) -> None:
            nonlocal current_motion, run_start
            run_length = end - run_start
            if run_length > self._cfg.max_run_length and current_motion is not None:
                stride = self._cfg.rebalance_stride
                for scene_idx in range(run_start + 1, end, stride):
                    scene = result[scene_idx]
                    if scene.get("scene_type") == "brand_card":
                        # Brand card must stay static — never swapped for
                        # variety like a regular scene.
                        continue
                    emotion = (
                        scene.get("motion", {}).get("emotion") or "revelation"
                    )
                    alternatives = [
                        m
                        for m in get_acceptable_motions(emotion)
                        if m != current_motion
                    ]
                    if not alternatives:
                        continue

                    # Pick least-recently-used alternative with LRU tracking
                    choice = self._pick_lru(alternatives, lru)
                    scene["motion"] = dict(scene.get("motion", {}))
                    scene["motion"]["motion_type"] = choice
                    lru.append(choice)
            current_motion = None
            run_start = end

        for idx, scene in enumerate(result):
            motion = scene.get("motion", {}).get("motion_type", "static")
            if motion == current_motion:
                continue
            _flush_run(idx)
            current_motion = motion
            run_start = idx

        _flush_run(len(result))
        return self._apply_rhythm_pass(result)

    @staticmethod
    def _apply_rhythm_pass(scenes: list[dict]) -> list[dict]:
        """CHANGE 5 — pacing rhythm check.

        In any window of 5 consecutive scenes there must be at least one
        hold-family motion and at least one movement motion. Brand card /
        asset scenes are never chosen as the swap target (though they still
        count toward satisfying the window's hold/movement requirement).
        Skipped entirely for scene lists shorter than the window size.
        """
        n = len(scenes)
        if n < _RHYTHM_WINDOW:
            return scenes

        result = [dict(scene) for scene in scenes]

        for start in range(0, n - _RHYTHM_WINDOW + 1):
            window = result[start : start + _RHYTHM_WINDOW]
            has_hold = any(
                w.get("motion", {}).get("motion_type", "static") in _HOLD_FAMILY
                for w in window
            )
            has_movement = any(
                _is_movement(w.get("motion", {}).get("motion_type", "static"))
                for w in window
            )
            if has_hold and has_movement:
                continue

            eligible = [
                (i, w)
                for i, w in enumerate(window)
                if w.get("scene_type") not in ("brand_card", "asset")
            ]
            if not eligible:
                continue

            # Tie-break toward the LAST position in the window (not the
            # first): emotional_intensity is "normal" for most scenes in
            # practice, so every window would tie at rank 0. Picking the
            # first element on a tie means the fix falls out of range for
            # the very next (stride-1) overlapping window, cascading into a
            # swap on every window instead of one isolated swap every ~5
            # scenes. Picking the last element keeps it inside several
            # subsequent overlapping windows, so they see the fix and skip.
            _, target = min(eligible, key=lambda pair: (_intensity_rank(pair[1]), -pair[0]))
            replacement = "hold_breathing" if not has_hold else "drift_float"
            motion = dict(target.get("motion", {}))
            motion["motion_type"] = replacement
            motion.update(_reset_motion_geometry(target, replacement))
            target["motion"] = motion

        return result

    @staticmethod
    def _pick_lru(alternatives: list[str], lru: deque[str]) -> str:
        """Pick the least-recently-used alternative, or the first if none used yet."""
        if not lru:
            return alternatives[0]
        for candidate in alternatives:
            if candidate not in lru:
                return candidate
        # All alternatives in LRU — return the oldest
        for candidate in lru:
            if candidate in alternatives:
                return candidate
        return alternatives[0]
