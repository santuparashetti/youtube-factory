"""
TimingEngine — post-segmentation timing optimization.

Responsibilities:
  - Close tiny gaps between adjacent cues (< GAP_THRESHOLD)
  - Extend cue end times when next cue starts after a long gap
  - Prevent overlap between adjacent cues
  - Enforce minimum and maximum cue duration
  - Renumber cue indices after any repairs

All operations are non-destructive clones (returns a new list).
"""

from __future__ import annotations


from .models import SubtitleCue

# Gaps smaller than this (seconds) are closed — looks better than a flash of nothing
_GAP_CLOSE_THRESHOLD = 0.15

# Maximum gap to auto-close (larger gaps are intentional pauses between sentences)
_GAP_CLOSE_MAX = 0.40

# Minimum time between the end of one cue and the start of the next
_MIN_GAP = 0.04

# Absolute floor for cue duration — shorter cues are unreadable
_MIN_DURATION = 0.5

# Absolute ceiling for cue duration
_MAX_DURATION = 7.0


class TimingEngine:
    """
    Post-process subtitle cue timing for smooth, readable display.

    Usage::

        engine = TimingEngine()
        repaired_cues, (overlaps, gaps) = engine.repair(cues)
    """

    def __init__(
        self,
        min_duration: float = _MIN_DURATION,
        max_duration: float = _MAX_DURATION,
        gap_close_threshold: float = _GAP_CLOSE_THRESHOLD,
        gap_close_max: float = _GAP_CLOSE_MAX,
        min_gap: float = _MIN_GAP,
    ) -> None:
        self._min_duration = min_duration
        self._max_duration = max_duration
        self._gap_close_threshold = gap_close_threshold
        self._gap_close_max = gap_close_max
        self._min_gap = min_gap

    def repair(
        self,
        cues: list[SubtitleCue],
        tail_extension_seconds: float = 0.0,
    ) -> tuple[list[SubtitleCue], tuple[int, int]]:
        """
        Repair timing issues in a list of subtitle cues.

        Args:
            cues: List of subtitle cues to repair.
            tail_extension_seconds: Extend the last cue's end time by this
                amount (seconds). Use to keep the final subtitle visible
                through a fade-to-black transition at the end of the scene.

        Returns:
            (repaired_cues, (overlap_count, gap_count))
            Cue indices are renumbered 1-based after repair.
        """
        if not cues:
            return [], (0, 0)

        result = list(cues)
        overlap_count = 0
        gap_count = 0

        # ── Pass 1: enforce min/max duration ─────────────────────────────────
        result = [self._clamp_duration(c) for c in result]

        # ── Pass 2: fix overlaps ──────────────────────────────────────────────
        for i in range(len(result) - 1):
            cur = result[i]
            nxt = result[i + 1]
            if cur.end > nxt.start - self._min_gap:
                # Trim current cue so it ends before next starts
                new_end = max(cur.start + self._min_duration, nxt.start - self._min_gap)
                if new_end > cur.start:
                    result[i] = SubtitleCue(
                        index=cur.index,
                        start=cur.start,
                        end=new_end,
                        lines=cur.lines,
                    )
                    overlap_count += 1

        # ── Pass 3: close small gaps ──────────────────────────────────────────
        for i in range(len(result) - 1):
            cur = result[i]
            nxt = result[i + 1]
            gap = nxt.start - cur.end
            if self._gap_close_threshold >= gap > 0:
                # Extend current cue end to close the gap
                result[i] = SubtitleCue(
                    index=cur.index,
                    start=cur.start,
                    end=nxt.start,
                    lines=cur.lines,
                )
                gap_count += 1

        # ── Pass 4: extend last cue for fade-out visibility ───────────────────
        if tail_extension_seconds > 0 and result:
            last = result[-1]
            result[-1] = SubtitleCue(
                index=last.index,
                start=last.start,
                end=last.end + tail_extension_seconds,
                lines=last.lines,
            )

        # ── Pass 5: renumber ──────────────────────────────────────────────────
        result = [
            SubtitleCue(index=i + 1, start=c.start, end=c.end, lines=c.lines)
            for i, c in enumerate(result)
        ]

        return result, (overlap_count, gap_count)

    def _clamp_duration(self, cue: SubtitleCue) -> SubtitleCue:
        """Clamp cue duration to [min_duration, max_duration]."""
        duration = cue.end - cue.start
        if duration >= self._min_duration and duration <= self._max_duration:
            return cue

        if duration < self._min_duration:
            new_end = cue.start + self._min_duration
        else:
            new_end = cue.start + self._max_duration

        return SubtitleCue(
            index=cue.index,
            start=cue.start,
            end=new_end,
            lines=cue.lines,
        )
