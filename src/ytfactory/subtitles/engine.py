"""
SubtitleEngine — production subtitle generation for YouTube Factory.

Single entry point that coordinates the full subtitle pipeline:

  word boundaries (from TTS)
       │
  SubtitleSegmenter      ← semantic grouping, two-line balancing
       │
  SubtitleTypographer    ← per-line display normalization
       │
  TimingEngine           ← gap/overlap repair, duration clamping
       │
  SubtitleValidator      ← CPS, line-length, orphan checks
       │
  SRTWriter              ← format serialization
       │
  SubtitleDebugWriter    ← audit trail (no-op when disabled)

Usage::

    from ytfactory.subtitles import SubtitleEngine

    engine = SubtitleEngine(settings)
    srt_content = engine.build(
        boundaries=boundaries,
        narration=scene["narration"],
        scene_index=scene["index"],
        project_id=project_id,
    )
    Path("subtitles/scene-001.srt").write_text(srt_content)

Both ``CaptionPipeline`` and ``scene_assets`` node delegate here —
there is no more duplicated SRT-building code.
"""

from __future__ import annotations


from loguru import logger

from .debug import SubtitleDebugWriter
from .models import SubtitleCue, SubtitleFormat, SubtitleReport, ValidationIssue
from .segmenter import SubtitleSegmenter
from .timing import TimingEngine
from .typography import SubtitleTypographer
from .validator import SubtitleValidator
from .writer import SRTWriter, get_writer


class SubtitleEngine:
    """
    Orchestrate the full subtitle generation pipeline.

    All configuration is passed at construction time via keyword arguments
    (or derived from ``Settings``). The engine is stateless between calls —
    safe to reuse across scenes.
    """

    def __init__(
        self,
        *,
        max_cps: float = 18.0,
        max_chars_per_line: int = 42,
        max_lines: int = 2,
        min_duration: float = 0.5,
        max_duration: float = 7.0,
        subtitle_format: SubtitleFormat | str = SubtitleFormat.SRT,
        debug: bool = False,
        validate: bool = True,
    ) -> None:
        self._segmenter = SubtitleSegmenter(
            max_cps=max_cps,
            max_chars_per_line=max_chars_per_line,
            max_lines=max_lines,
            min_duration=min_duration,
        )
        self._timing = TimingEngine(
            min_duration=min_duration,
            max_duration=max_duration,
        )
        self._validator = SubtitleValidator(
            max_cps=max_cps,
            max_chars_per_line=max_chars_per_line,
            min_duration=min_duration,
            max_duration=max_duration,
        )
        self._typo = SubtitleTypographer()
        self._writer: SRTWriter = get_writer(subtitle_format)
        self._debug = debug
        self._validate = validate

    @classmethod
    def from_settings(cls, settings) -> "SubtitleEngine":
        """
        Construct from a ``Settings`` object.

        Reads: subtitle_debug, subtitle_validate, subtitle_max_cps,
               subtitle_max_chars_per_line, subtitle_max_lines.
        """
        return cls(
            max_cps=getattr(settings, "subtitle_max_cps", 18.0),
            max_chars_per_line=getattr(settings, "subtitle_max_chars_per_line", 42),
            max_lines=getattr(settings, "subtitle_max_lines", 2),
            debug=getattr(settings, "subtitle_debug", False),
            validate=getattr(settings, "subtitle_validate", True),
        )

    # ── Main API ──────────────────────────────────────────────────────────────

    def build(
        self,
        *,
        boundaries: list[dict],
        narration: str,
        scene_index: int,
        project_id: str,
        total_duration: float = 0.0,
        formatted_narration: str = "",
    ) -> str:
        """
        Build a complete SRT string for one scene.

        Args:
            boundaries:          Word-level timing from TTS provider.
                                 [{word: str, start: float, end: float}]
                                 Empty list → fallback proportional timing.
            narration:           Original scene narration (for debug + fallback).
            scene_index:         1-based scene number (for filenames and logs).
            project_id:          Project identifier (for debug paths).
            total_duration:      Scene duration in seconds — used only for fallback.
            formatted_narration: Text after SpeechFormatter — written to debug only.

        Returns:
            SRT-formatted string ready to write to disk.
            Returns an empty string if no cues could be generated.
        """
        debug = SubtitleDebugWriter(
            project_id=project_id,
            scene_index=scene_index,
            enabled=self._debug,
        )
        debug.write_original(narration)
        debug.write_word_boundaries(boundaries)
        if formatted_narration:
            debug.write_optimized(formatted_narration)

        # ── 1. Segment ────────────────────────────────────────────────────────
        if boundaries:
            cues = self._segmenter.segment(boundaries, narration)
        else:
            cues = self._segmenter.fallback_segment(narration, total_duration)

        # ── 2. Timing repair ──────────────────────────────────────────────────
        cues, (overlaps, gaps) = self._timing.repair(cues)

        # ── 3. Validate (optional) ────────────────────────────────────────────
        issues: list[ValidationIssue] = []
        if self._validate and cues:
            cues, issues = self._validator.validate(cues)

        # ── 4. Serialize ──────────────────────────────────────────────────────
        srt = self._writer.write(cues)

        # ── 5. Debug output ───────────────────────────────────────────────────
        debug.write_final_srt(srt)
        debug.write_analysis(cues)
        debug.write_validation(issues)

        # ── 6. Metrics logging ────────────────────────────────────────────────
        report = _build_report(
            scene_index=scene_index,
            cues=cues,
            issues=issues,
            overlap_repairs=overlaps,
            gap_repairs=gaps,
        )

        if issues:
            warning_count = sum(1 for i in issues if i.severity == "warning")
            error_count = sum(1 for i in issues if i.severity == "error")
            logger.debug(
                "Subtitles scene {} — {} cues, {:.1f} avg CPS, {} warnings, {} errors",
                scene_index,
                len(cues),
                report.avg_cps,
                warning_count,
                error_count,
            )
        else:
            logger.debug(
                "Subtitles scene {} — {} cues, {:.1f} avg CPS",
                scene_index,
                len(cues),
                report.avg_cps,
            )

        return srt

    def build_report(
        self,
        *,
        boundaries: list[dict],
        narration: str,
        scene_index: int,
        project_id: str,
        total_duration: float = 0.0,
        formatted_narration: str = "",
    ) -> tuple[str, SubtitleReport]:
        """Same as build() but also returns the SubtitleReport for diagnostics."""
        debug = SubtitleDebugWriter(
            project_id=project_id,
            scene_index=scene_index,
            enabled=self._debug,
        )
        debug.write_original(narration)
        debug.write_word_boundaries(boundaries)
        if formatted_narration:
            debug.write_optimized(formatted_narration)

        if boundaries:
            cues = self._segmenter.segment(boundaries, narration)
        else:
            cues = self._segmenter.fallback_segment(narration, total_duration)

        cues, (overlaps, gaps) = self._timing.repair(cues)

        issues: list[ValidationIssue] = []
        typo_repairs = 0
        if self._validate and cues:
            cues, issues = self._validator.validate(cues)

        srt = self._writer.write(cues)

        debug.write_final_srt(srt)
        debug.write_analysis(cues)
        debug.write_validation(issues)

        report = _build_report(
            scene_index=scene_index,
            cues=cues,
            issues=issues,
            overlap_repairs=overlaps,
            gap_repairs=gaps,
            typography_repairs=typo_repairs,
        )
        return srt, report


# ── Internal helpers ──────────────────────────────────────────────────────────


def _build_report(
    *,
    scene_index: int,
    cues: list[SubtitleCue],
    issues: list[ValidationIssue],
    overlap_repairs: int,
    gap_repairs: int,
    typography_repairs: int = 0,
) -> SubtitleReport:
    if not cues:
        return SubtitleReport(
            scene_index=scene_index,
            cue_count=0,
            avg_cps=0.0,
            max_cps=0.0,
            avg_duration=0.0,
            min_duration=0.0,
            max_duration=0.0,
            overlap_repairs=overlap_repairs,
            gap_repairs=gap_repairs,
            typography_repairs=typography_repairs,
            issues=issues,
        )

    cpss = [c.cps for c in cues if c.duration > 0]
    durs = [c.duration for c in cues]

    return SubtitleReport(
        scene_index=scene_index,
        cue_count=len(cues),
        avg_cps=sum(cpss) / max(len(cpss), 1),
        max_cps=max(cpss, default=0.0),
        avg_duration=sum(durs) / max(len(durs), 1),
        min_duration=min(durs, default=0.0),
        max_duration=max(durs, default=0.0),
        overlap_repairs=overlap_repairs,
        gap_repairs=gap_repairs,
        typography_repairs=typography_repairs,
        issues=issues,
    )
