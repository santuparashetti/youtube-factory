"""Post-planning motion variety rebalancer (Approach B).

Runs after MotionPlanner to break long consecutive runs of the same motion
type by substituting alternatives from the same emotion's acceptable set.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass

from video_core.cinematic.profiles import get_acceptable_motions

logger = logging.getLogger(__name__)


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
