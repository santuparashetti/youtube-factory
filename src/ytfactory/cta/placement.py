"""CTA placement engine — context-aware timing search.

Search algorithm (from spec):
  1. Find all insight-tier pauses after the video midpoint, up to
     max_placement_search_pct.
  2. For each candidate pause (in order):
     a. Check subtitle safety.
     b. If subtitle-safe → place CTA (full or compact based on duration).
     c. If NOT subtitle-safe → continue searching.
  3. If no subtitle-safe pause found → fall back to fallback_timing
     position with compact variant (always renders).

Two distinct failure modes:
  - No insight-tier pause exists in the window → primary trigger for fallback.
  - Pause exists but isn't subtitle-safe → keep searching before fallback.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from loguru import logger

from .config import CTAOverlayConfig
from .models import CTAPlacement, CTAVariant, CTAZone, PlacementPath


# ── Subtitle window reader ──────────────────────────────────────────────────────


def _parse_srt_timecodes(content: str) -> list[tuple[float, float]]:
    """Return list of (start, end) in seconds from SRT file content."""
    windows: list[tuple[float, float]] = []
    pattern = re.compile(
        r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})"
    )
    for m in pattern.finditer(content):
        h1, m1, s1, ms1 = (
            int(m.group(1)),
            int(m.group(2)),
            int(m.group(3)),
            int(m.group(4)),
        )
        h2, m2, s2, ms2 = (
            int(m.group(5)),
            int(m.group(6)),
            int(m.group(7)),
            int(m.group(8)),
        )
        start = h1 * 3600 + m1 * 60 + s1 + ms1 / 1000.0
        end = h2 * 3600 + m2 * 60 + s2 + ms2 / 1000.0
        windows.append((start, end))
    return windows


def _build_subtitle_windows(project_dir: Path) -> list[tuple[float, float]]:
    """Build a list of (start, end) seconds where subtitles are active."""
    subtitles_dir = project_dir / "subtitles"
    windows: list[tuple[float, float]] = []

    if not subtitles_dir.exists():
        return windows

    for srt_path in sorted(subtitles_dir.glob("scene-*.srt")):
        try:
            content = srt_path.read_text(encoding="utf-8")
            windows.extend(_parse_srt_timecodes(content))
        except Exception:
            pass

    return sorted(windows)


def _subtitle_active_at(
    windows: list[tuple[float, float]], t: float, duration: float
) -> bool:
    """Return True if any subtitle window overlaps [t, t+duration]."""
    end = t + duration
    for w_start, w_end in windows:
        if w_start < end and w_end > t:
            return True
    return False


# ── Speech timeline reader ──────────────────────────────────────────────────────


def _get_video_duration(project_dir: Path) -> float:
    """Estimate video duration from timing.json files (sum of all scene durations)."""
    audio_dir = project_dir / "audio"
    if not audio_dir.exists():
        return 0.0

    total = 0.0
    for timing_path in sorted(audio_dir.glob("scene-*.timing.json")):
        try:
            data = json.loads(timing_path.read_text(encoding="utf-8"))
            if isinstance(data, list) and data:
                total += float(data[-1].get("end", 0.0)) + 0.1
        except Exception:
            pass
    return total


# ── Hook end timestamp ─────────────────────────────────────────────────────────


def _get_hook_end_timestamp(
    project_dir: Path, min_seconds: float = 8.0
) -> float | None:
    """Return the end timestamp of scene 1 (the hook), or None if unavailable.

    Prefers alignment.json (WhisperX word-level) over timing.json (TTS).
    Returns None when neither file exists so the caller can fall back gracefully.
    Clamps to min_seconds so the CTA never appears in the very first seconds.
    """
    audio_dir = project_dir / "audio"
    for filename in ("scene-001.alignment.json", "scene-001.timing.json"):
        path = audio_dir / filename
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list) and data:
                # timing.json: list of word dicts with "end" field
                end = float(data[-1].get("end", 0.0))
                return max(end, min_seconds)
            if isinstance(data, dict):
                # alignment.json: {"words": [...], ...}
                words = data.get("words", [])
                if words:
                    end = float(words[-1].get("end", 0.0))
                    return max(end, min_seconds)
        except Exception:
            pass
    return None


# ── Zone selection ─────────────────────────────────────────────────────────────


def _choose_zone(
    subtitle_active: bool,
    config: CTAOverlayConfig,
) -> tuple[CTAZone, bool]:
    """Return (zone, subtitle_safe) for the given subtitle activity.

    Bottom-center is preferred when subtitles are inactive.
    When subtitles are active, move to upper-left or upper-right.
    Upper zones are always considered subtitle-safe.
    """
    if not subtitle_active:
        return (
            CTAZone(config.zone_default)
            if config.zone_default in CTAZone.__members__.values()
            else CTAZone.BOTTOM_CENTER,
            True,
        )

    # Subtitle active → move to upper zone (right preferred, then left)
    return CTAZone.UPPER_RIGHT, True


# ── Placement engine ───────────────────────────────────────────────────────────


class CTAPlacementEngine:
    """Implements the context-aware timing search algorithm from the spec."""

    def __init__(self, config: CTAOverlayConfig) -> None:
        self._config = config

    def find_placement(self, project_dir: Path) -> CTAPlacement:
        """Execute the placement search and return the chosen placement.

        Always returns a placement — falls back to fixed fallback_timing with
        compact variant when no suitable pause is found (spec: guaranteed render).
        """
        subtitle_windows = _build_subtitle_windows(project_dir)
        video_duration = _get_video_duration(project_dir)

        if video_duration <= 0:
            # No timing data yet — place at 65% fallback
            return self._fallback_placement(video_duration or 300.0, subtitle_windows)

        if self._config.timing_mode == "post_hook":
            hook_end = _get_hook_end_timestamp(project_dir)
            if hook_end is not None:
                return self._post_hook_placement(project_dir, subtitle_windows, hook_end)
            logger.warning(
                "CTA post_hook: no scene-001 timing data found — falling back to contextual"
            )

        midpoint = video_duration / 2.0
        search_limit = video_duration * self._config.max_placement_search_pct
        insight_min_s = self._config.insight_tier_min_ms / 1000.0

        # Build speech timeline from Kokoro timestamps
        pauses = self._get_insight_tier_pauses(
            project_dir, midpoint, search_limit, insight_min_s
        )

        for pause_start, pause_end, pause_type in pauses:
            pause_dur = pause_end - pause_start
            cta_dur = min(
                self._config.duration
                if pause_dur * 1000 >= self._config.min_pause_ms_for_full_cta
                else pause_dur * 0.85,  # compact fits within available pause
                pause_dur,
            )
            variant = (
                CTAVariant.FULL
                if pause_dur * 1000 >= self._config.min_pause_ms_for_full_cta
                else CTAVariant.COMPACT
            )

            subtitle_active = _subtitle_active_at(
                subtitle_windows, pause_start, cta_dur
            )
            zone, safe = _choose_zone(subtitle_active, self._config)

            if safe:
                logger.info(
                    "CTA placement: {} at {:.1f}s (pause={:.2f}s, type={}, zone={})",
                    variant.value,
                    pause_start,
                    pause_dur,
                    pause_type,
                    zone.value,
                )
                return CTAPlacement(
                    timestamp=pause_start,
                    duration=cta_dur,
                    variant=variant,
                    placement_path=PlacementPath.PRIMARY_CONTEXTUAL,
                    subtitle_safe=True,
                    zone=zone,
                    pause_type=pause_type,
                    pause_duration=pause_dur,
                )

        # No suitable pause found — fall back
        logger.warning(
            "CTA: no subtitle-safe insight-tier pause found by {:.0%} — using fallback_timing",
            self._config.max_placement_search_pct,
        )
        return self._fallback_placement(video_duration, subtitle_windows)

    def _fallback_placement(
        self,
        video_duration: float,
        subtitle_windows: list[tuple[float, float]],
    ) -> CTAPlacement:
        """Fixed-percentage placement with compact variant.

        Renders regardless of subtitle state (spec: guaranteed render).
        Uses upper-right corner to minimise subtitle overlap risk.
        """
        ts = video_duration * self._config.fallback_timing
        cta_dur = min(
            self._config.duration * 0.6,  # compact is shorter
            self._config.duration,
        )
        subtitle_active = _subtitle_active_at(subtitle_windows, ts, cta_dur)
        zone = CTAZone.UPPER_RIGHT if subtitle_active else CTAZone.BOTTOM_CENTER
        return CTAPlacement(
            timestamp=ts,
            duration=cta_dur,
            variant=CTAVariant.COMPACT,
            placement_path=PlacementPath.FALLBACK_TIMING,
            subtitle_safe=not subtitle_active,
            zone=zone,
            pause_type=None,
            pause_duration=0.0,
        )

    def _post_hook_placement(
        self,
        project_dir: Path,
        subtitle_windows: list[tuple[float, float]],
        hook_end: float,
    ) -> CTAPlacement:
        """Place CTA immediately after scene 1 (hook) ends.

        Uses FULL variant when the bottom zone is subtitle-free; falls back to
        COMPACT at upper-right when subtitles are still active at that timestamp.
        """
        cta_dur = self._config.duration
        subtitle_active = _subtitle_active_at(subtitle_windows, hook_end, cta_dur)
        zone, safe = _choose_zone(subtitle_active, self._config)

        if subtitle_active:
            variant = CTAVariant.COMPACT
            cta_dur = min(self._config.duration * 0.6, self._config.duration)
        else:
            variant = CTAVariant.FULL

        logger.info(
            "CTA placement: post_hook {} at {:.1f}s (zone={}, subtitle_active={})",
            variant.value,
            hook_end,
            zone.value,
            subtitle_active,
        )
        return CTAPlacement(
            timestamp=hook_end,
            duration=cta_dur,
            variant=variant,
            placement_path=PlacementPath.POST_HOOK,
            subtitle_safe=safe,
            zone=zone,
            pause_type="post_hook",
            pause_duration=0.0,
        )

    def _get_insight_tier_pauses(
        self,
        project_dir: Path,
        midpoint: float,
        search_limit: float,
        insight_min_s: float,
    ) -> list[tuple[float, float, str]]:
        """Return list of (start, end, pause_type) for insight-tier pauses.

        Uses Kokoro word timestamps (timing.json / alignment.json) to build
        a speech timeline, then classifies gaps between phrases.
        Falls back to silence detection via the narration-only audio if
        no timing files are available.
        """
        from ytfactory.bgm.vad import (
            PauseClassifier,
            PauseType,
            build_speech_timeline_from_kokoro,
        )

        timeline = build_speech_timeline_from_kokoro(project_dir)
        if timeline is None:
            return []

        classifier = PauseClassifier(long_silence_threshold_ms=2500)
        pause_events = classifier.classify(timeline)

        result: list[tuple[float, float, str]] = []
        for evt in pause_events:
            if evt.start < midpoint:
                continue
            if evt.start > search_limit:
                break
            if evt.duration < insight_min_s:
                continue
            if evt.pause_type in (PauseType.SENTENCE_PAUSE, PauseType.LONG_SILENCE):
                result.append((evt.start, evt.end, evt.pause_type.value))

        return result
