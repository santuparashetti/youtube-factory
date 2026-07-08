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

from .ass import ASSWriter
from .ass.theme_manager import ThemeManager
from .debug import SubtitleDebugWriter
from .models import SubtitleCue, SubtitleFormat, SubtitleReport, ValidationIssue
from .segmenter import SubtitleSegmenter
from .timing import TimingEngine
from .typography import SubtitleTypographer
from .validator import SubtitleValidator
from .writer import SRTWriter


class SubtitleEngine:
    """
    Orchestrate the full subtitle generation pipeline.

    All configuration is passed at construction time via keyword arguments
    (or derived from ``Settings``). The engine is stateless between calls —
    safe to reuse across scenes.

    Dual-format output:
      build()       → SRT string (backward-compatible)
      build_both()  → (ass_str, srt_str, report) — primary path when ASS is enabled
      build_report() → (srt_str, report)
    """

    def __init__(
        self,
        *,
        max_cps: float = 18.0,
        max_chars_per_line: int = 42,
        max_lines: int = 2,
        min_duration: float = 0.5,
        max_duration: float = 7.0,
        tail_extension_seconds: float = 1.0,
        subtitle_format: SubtitleFormat | str = SubtitleFormat.SRT,
        debug: bool = False,
        validate: bool = True,
        ass_theme=None,
        segmentation_mode: str = "semantic",
    ) -> None:
        self._tail_extension = tail_extension_seconds
        self._segmenter = SubtitleSegmenter(
            max_cps=max_cps,
            max_chars_per_line=max_chars_per_line,
            max_lines=max_lines,
            min_duration=min_duration,
            mode=segmentation_mode,
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
        self._srt_writer = SRTWriter()
        # ASS writer — always constructed; theme can be overridden
        theme = ass_theme if ass_theme is not None else ThemeManager.get("default")
        self._ass_writer = ASSWriter(theme=theme)
        self._fmt = (
            SubtitleFormat(subtitle_format)
            if isinstance(subtitle_format, str)
            else subtitle_format
        )
        self._debug = debug
        self._validate = validate

    @classmethod
    def from_settings(cls, settings) -> "SubtitleEngine":
        """
        Construct from a ``Settings`` object.

        Reads subtitle_* settings including ASS-specific fields.
        Falls back to safe defaults for any missing attribute.
        """
        from .ass.theme_manager import ThemeManager as TM

        ass_theme = TM.from_settings(settings)
        fmt_str = getattr(settings, "subtitle_format", "ass")
        seg_mode = getattr(settings, "subtitle_segmentation_mode", "semantic")

        return cls(
            max_cps=getattr(settings, "subtitle_max_cps", 18.0),
            max_chars_per_line=getattr(settings, "subtitle_max_chars_per_line", 42),
            max_lines=getattr(settings, "subtitle_max_lines", 2),
            tail_extension_seconds=getattr(
                settings, "subtitle_tail_extension_seconds", 1.0
            ),
            debug=getattr(settings, "subtitle_debug", False),
            validate=getattr(settings, "subtitle_validate", True),
            subtitle_format=fmt_str,
            ass_theme=ass_theme,
            segmentation_mode=seg_mode,
        )

    # ── Main API ──────────────────────────────────────────────────────────────

    @property
    def format(self) -> SubtitleFormat:
        """The configured output format."""
        return self._fmt

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

        cues, (overlaps, gaps), issues = self._process(
            boundaries, narration, total_duration
        )
        srt = self._srt_writer.write(cues)

        debug.write_final_srt(srt)
        debug.write_analysis(cues)
        debug.write_validation(issues)

        report = _build_report(
            scene_index=scene_index,
            cues=cues,
            issues=issues,
            overlap_repairs=overlaps,
            gap_repairs=gaps,
        )
        _log_report(scene_index, report, issues)

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
        """Return (srt_string, SubtitleReport). Backward-compatible."""
        debug = SubtitleDebugWriter(
            project_id=project_id,
            scene_index=scene_index,
            enabled=self._debug,
        )
        debug.write_original(narration)
        debug.write_word_boundaries(boundaries)
        if formatted_narration:
            debug.write_optimized(formatted_narration)

        cues, (overlaps, gaps), issues = self._process(
            boundaries, narration, total_duration
        )
        srt = self._srt_writer.write(cues)

        debug.write_final_srt(srt)
        debug.write_analysis(cues)
        debug.write_validation(issues)

        report = _build_report(
            scene_index=scene_index,
            cues=cues,
            issues=issues,
            overlap_repairs=overlaps,
            gap_repairs=gaps,
        )
        return srt, report

    def build_both(
        self,
        *,
        boundaries: list[dict],
        narration: str,
        scene_index: int,
        project_id: str,
        total_duration: float = 0.0,
        formatted_narration: str = "",
    ) -> tuple[str, str, SubtitleReport]:
        """
        Build both ASS and SRT outputs in a single pass.

        Returns:
            (ass_content, srt_content, SubtitleReport)

        ASS is the primary format for rendering.
        SRT is written alongside for compatibility and debug.
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

        cues, (overlaps, gaps), issues = self._process(
            boundaries, narration, total_duration
        )

        ass = self._ass_writer.write(cues)
        srt = self._srt_writer.write(cues)

        debug.write_final_srt(srt)
        debug.write_final_ass(ass)
        debug.write_analysis(cues)
        debug.write_validation(issues)

        report = _build_report(
            scene_index=scene_index,
            cues=cues,
            issues=issues,
            overlap_repairs=overlaps,
            gap_repairs=gaps,
        )
        _log_report(scene_index, report, issues)

        return ass, srt, report

    @property
    def ass_writer(self) -> ASSWriter:
        """Direct access to the ASS writer — use after build_cues() for editing passes."""
        return self._ass_writer

    @property
    def srt_writer(self) -> SRTWriter:
        """Direct access to the SRT writer — use after build_cues() for editing passes."""
        return self._srt_writer

    def build_cues(
        self,
        *,
        boundaries: list[dict],
        narration: str,
        scene_index: int,
        project_id: str,
        total_duration: float = 0.0,
        formatted_narration: str = "",
    ) -> tuple[list[SubtitleCue], SubtitleReport]:
        """Build subtitle cues without writing output files.

        Useful when an editing pass (SubtitleEditingEngine) should run
        before the final SRT/ASS is serialised. Returns (cues, report).
        Debug files are written here so they reflect the raw generated
        cues (pre-edit). The caller is responsible for serialising and
        writing the (potentially edited) cues via ass_writer / srt_writer.
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

        cues, (overlaps, gaps), issues = self._process(
            boundaries, narration, total_duration
        )

        report = _build_report(
            scene_index=scene_index,
            cues=cues,
            issues=issues,
            overlap_repairs=overlaps,
            gap_repairs=gaps,
        )
        _log_report(scene_index, report, issues)

        return cues, report

    # ── Internal pipeline ─────────────────────────────────────────────────────

    def _process(
        self,
        boundaries: list[dict],
        narration: str,
        total_duration: float,
    ) -> tuple[list[SubtitleCue], tuple[int, int], list[ValidationIssue]]:
        """Shared segment → timing → validate pipeline used by all build methods."""
        if boundaries:
            cues = self._segmenter.segment(boundaries, narration)
        else:
            cues = self._segmenter.fallback_segment(narration, total_duration)

        cues, repair_counts = self._timing.repair(
            cues, tail_extension_seconds=self._tail_extension
        )

        issues: list[ValidationIssue] = []
        if self._validate and cues:
            cues, issues = self._validator.validate(cues)

        return cues, repair_counts, issues


# ── Internal helpers ──────────────────────────────────────────────────────────


def _log_report(
    scene_index: int,
    report: SubtitleReport,
    issues: list[ValidationIssue],
) -> None:
    if issues:
        warning_count = sum(1 for i in issues if i.severity == "warning")
        error_count = sum(1 for i in issues if i.severity == "error")
        logger.debug(
            "Subtitles scene {} — {} cues, {:.1f} avg CPS, {} warnings, {} errors",
            scene_index,
            report.cue_count,
            report.avg_cps,
            warning_count,
            error_count,
        )
    else:
        logger.debug(
            "Subtitles scene {} — {} cues, {:.1f} avg CPS",
            scene_index,
            report.cue_count,
            report.avg_cps,
        )


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
