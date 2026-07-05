"""
SubtitleDebugWriter — per-scene audit trail when SUBTITLE_DEBUG=true.

Writes to: workspace/jobs/<project>/subtitle-debug/scene-NNN/

Files created per scene:
  subtitle-original.txt      — raw narration from scene-plan.json
  subtitle-optimized.txt     — narration after SpeechFormatter (what was spoken)
  subtitle-final.srt         — the generated SRT content
  subtitle-analysis.json     — per-cue metrics (CPS, duration, chars, lines)
  subtitle-validation.json   — ValidationIssue list
  subtitle-word-boundaries.json — input word timings
  SUBTITLE_DIAGNOSTICS.md   — human-readable project-level summary

When SUBTITLE_DEBUG=false all methods are no-ops — zero overhead.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from ytfactory.shared.constants import WORKSPACE_DIR

from .models import SubtitleCue, SubtitleReport, ValidationIssue


class SubtitleDebugWriter:
    """
    Write subtitle debug artefacts for one scene.

    Instantiate once per scene.  All write_* methods are no-ops when
    ``enabled=False``.
    """

    def __init__(self, project_id: str, scene_index: int, enabled: bool = True):
        self._enabled = enabled
        self._scene_index = scene_index
        self._project_id = project_id
        self._dir = (
            Path(WORKSPACE_DIR)
            / project_id
            / "subtitle-debug"
            / f"scene-{scene_index:03d}"
        )
        if enabled:
            self._dir.mkdir(parents=True, exist_ok=True)

    # ── Per-scene files ────────────────────────────────────────────────────────

    def write_original(self, narration: str) -> None:
        self._write_text("subtitle-original.txt", narration)

    def write_optimized(self, formatted_narration: str) -> None:
        """The text after SpeechFormatter — this is what was synthesized by TTS."""
        self._write_text("subtitle-optimized.txt", formatted_narration)

    def write_word_boundaries(self, boundaries: list[dict]) -> None:
        self._write_json("subtitle-word-boundaries.json", boundaries)

    def write_final_srt(self, srt_content: str) -> None:
        self._write_text("subtitle-final.srt", srt_content)

    def write_final_ass(self, ass_content: str) -> None:
        self._write_text("subtitle-final.ass", ass_content)

    def write_analysis(self, cues: list[SubtitleCue]) -> None:
        """Write per-cue metrics for every generated cue."""
        data = [
            {
                "index": cue.index,
                "start": round(cue.start, 3),
                "end": round(cue.end, 3),
                "duration": round(cue.duration, 3),
                "cps": round(cue.cps, 2),
                "chars": cue.char_count,
                "longest_line": cue.longest_line,
                "lines": cue.lines,
            }
            for cue in cues
        ]
        self._write_json("subtitle-analysis.json", data)

    def write_validation(self, issues: list[ValidationIssue]) -> None:
        self._write_json(
            "subtitle-validation.json",
            [
                {
                    "cue_index": i.cue_index,
                    "code": i.code,
                    "severity": i.severity,
                    "message": i.message,
                    "repaired": i.repaired,
                }
                for i in issues
            ],
        )

    # ── Project-level summary ──────────────────────────────────────────────────

    @staticmethod
    def write_project_summary(
        project_id: str,
        reports: list[SubtitleReport],
        enabled: bool = True,
    ) -> None:
        """
        Write SUBTITLE_DIAGNOSTICS.md to the subtitle-debug root.
        Call once after all scenes have been processed.
        """
        if not enabled:
            return

        debug_dir = Path(WORKSPACE_DIR) / project_id / "subtitle-debug"
        debug_dir.mkdir(parents=True, exist_ok=True)

        total_scenes = len(reports)
        total_cues = sum(r.cue_count for r in reports)
        all_cps = [r.avg_cps for r in reports if r.avg_cps > 0]
        avg_cps = sum(all_cps) / max(len(all_cps), 1)
        max_cps = max((r.max_cps for r in reports), default=0.0)
        total_overlaps = sum(r.overlap_repairs for r in reports)
        total_gaps = sum(r.gap_repairs for r in reports)
        total_typo = sum(r.typography_repairs for r in reports)
        total_issues = sum(len(r.issues) for r in reports)

        lines = [
            "# Subtitle Diagnostics Report",
            "",
            f"**Project:** `{project_id}`  ",
            f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ",
            f"**Total scenes:** {total_scenes}  ",
            f"**Total cues:** {total_cues}  ",
            f"**Average CPS:** {avg_cps:.1f}  ",
            f"**Maximum CPS:** {max_cps:.1f}  ",
            f"**Overlap repairs:** {total_overlaps}  ",
            f"**Gap repairs:** {total_gaps}  ",
            f"**Typography repairs:** {total_typo}  ",
            f"**Validation issues:** {total_issues}",
            "",
            "---",
            "",
            "## Per-Scene Summary",
            "",
            "| Scene | Cues | Avg CPS | Max CPS | Avg Dur | Overlaps | Gaps | Issues |",
            "|-------|------|---------|---------|---------|----------|------|--------|",
        ]

        for r in reports:
            lines.append(
                f"| {r.scene_index:>3} | {r.cue_count:>4} "
                f"| {r.avg_cps:>7.1f} | {r.max_cps:>7.1f} "
                f"| {r.avg_duration:>7.2f}s "
                f"| {r.overlap_repairs:>8} | {r.gap_repairs:>4} "
                f"| {len(r.issues):>6} |"
            )

        lines += [
            "",
            "---",
            "",
            "## Debug File Structure",
            "",
            "Each scene has its own subdirectory under `subtitle-debug/`:",
            "",
            "```",
            "subtitle-debug/",
            "├── SUBTITLE_DIAGNOSTICS.md",
            "└── scene-NNN/",
            "    ├── subtitle-original.txt         ← raw narration",
            "    ├── subtitle-optimized.txt        ← after SpeechFormatter",
            "    ├── subtitle-word-boundaries.json ← TTS timing input",
            "    ├── subtitle-final.srt            ← generated SRT output",
            "    ├── subtitle-analysis.json        ← per-cue metrics",
            "    └── subtitle-validation.json      ← validation issues",
            "```",
            "",
            "## Troubleshooting",
            "",
            "**High CPS:** Check `subtitle-analysis.json` for cues with CPS > 18.",
            "The cause is usually a very short boundary duration. Consider adjusting",
            "`SUBTITLE_MAX_CPS` upward or slowing TTS rate.",
            "",
            "**Awkward breaks:** Review `subtitle-final.srt` and compare to",
            "`subtitle-word-boundaries.json`. The segmenter respects punctuation",
            "boundaries — if breaks look wrong, check that the narration is",
            "correctly punctuated in `subtitle-original.txt`.",
            "",
            "**Overlap repairs:** Normal for dense narration. Check `overlap_repairs`",
            "count — if it is very high, consider shorter scene narrations.",
        ]

        out = debug_dir / "SUBTITLE_DIAGNOSTICS.md"
        out.write_text("\n".join(lines), encoding="utf-8")

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _write_text(self, filename: str, content: str) -> None:
        if not self._enabled:
            return
        (self._dir / filename).write_text(content, encoding="utf-8")

    def _write_json(self, filename: str, data: object) -> None:
        if not self._enabled:
            return
        (self._dir / filename).write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
