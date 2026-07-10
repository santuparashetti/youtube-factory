"""
CaptionPipeline — standalone subtitle generation stage.

Delegates all subtitle logic to SubtitleEngine.

When subtitle_editor_enabled=True (settings), the raw cues produced by
SubtitleEngine are passed through SubtitleEditingEngine before being
written to disk.  The editing pass only changes text (punctuation,
capitalisation, line breaks) — timing and cue count are frozen.

When subtitle_format="ass" (default):
  - Writes scene-NNN.ass as the primary file (used for rendering)
  - Writes scene-NNN.srt alongside for compatibility and debug

When subtitle_format="srt":
  - Writes scene-NNN.srt only (original behavior, fully backward-compatible)
"""

from __future__ import annotations

import json
from pathlib import Path

from ytfactory.config.settings import Settings
from ytfactory.subtitles import SubtitleEngine
from ytfactory.subtitles.debug import SubtitleDebugWriter
from ytfactory.subtitles.models import SubtitleFormat, SubtitleReport
from ytfactory.voice.aligner import boundaries_from_alignment, load_alignment

from .artifacts import subtitles_directory
from .models import CaptionArtifact
from .repository import CaptionRepository


class CaptionPipeline:
    def __init__(self):
        self.repository = CaptionRepository()

    def run(
        self,
        project_id: str,
    ) -> None:
        settings = Settings()
        engine = SubtitleEngine.from_settings(settings)
        use_ass = engine.format == SubtitleFormat.ASS

        # Build subtitle editor once (None when disabled)
        editor = _build_editor(settings)

        project_dir = Path("workspace") / "jobs" / project_id
        scene_file = project_dir / "scenes" / "scene-plan.json"
        scenes = json.loads(scene_file.read_text(encoding="utf-8"))["scenes"]

        reports: list[SubtitleReport] = []

        for scene in scenes:
            index = scene["index"]
            srt_path = subtitles_directory(project_id) / f"scene-{index:03d}.srt"
            ass_path = subtitles_directory(project_id) / f"scene-{index:03d}.ass"

            # Skip if primary output already exists
            primary = ass_path if use_ass else srt_path
            if primary.exists():
                continue

            # Prefer WhisperX alignment (more accurate) over TTS timing.
            alignment_file = project_dir / "audio" / f"scene-{index:03d}.alignment.json"
            timing_file = project_dir / "audio" / f"scene-{index:03d}.timing.json"

            boundaries: list[dict] = []
            alignment_data = load_alignment(alignment_file)
            if alignment_data is not None:
                boundaries = boundaries_from_alignment(alignment_data)
            elif timing_file.exists():
                data = timing_file.read_text(encoding="utf-8")
                boundaries = json.loads(data) if data.strip() else []

            total_duration = float(scene.get("duration_seconds", 10.0))

            # ── Build raw cues ────────────────────────────────────────────
            cues, report = engine.build_cues(
                boundaries=boundaries,
                narration=scene["narration"],
                scene_index=index,
                project_id=project_id,
                total_duration=total_duration,
            )

            # ── Editorial pass (when enabled) ─────────────────────────────
            if editor is not None:
                cues = editor.edit(
                    cues, scene_id=f"scene-{index:03d}", project_id=project_id
                )

            # ── Serialise and write ───────────────────────────────────────
            if use_ass:
                ass = engine.ass_writer.write(cues)
                srt = engine.srt_writer.write(cues)
                ass_path.write_text(ass, encoding="utf-8")
                srt_path.write_text(srt, encoding="utf-8")
                artifact = CaptionArtifact(
                    scene_id=index,
                    srt_path=srt_path,
                    ass_path=ass_path,
                )
            else:
                srt = engine.srt_writer.write(cues)
                srt_path.write_text(srt, encoding="utf-8")
                artifact = CaptionArtifact(
                    scene_id=index,
                    srt_path=srt_path,
                )

            reports.append(report)
            self.repository.save(artifact)

        SubtitleDebugWriter.write_project_summary(
            project_id=project_id,
            reports=reports,
            enabled=settings.subtitle_debug,
        )


def _build_editor(settings: Settings):
    """Return a SubtitleEditingEngine or None when editor is disabled."""
    if not settings.subtitle_editor_enabled:
        return None

    from ytfactory.subtitles.editor import SubtitleEditingEngine
    from ytfactory.subtitles.editor.factory import get_subtitle_editor_provider

    provider = get_subtitle_editor_provider(settings)
    return SubtitleEditingEngine(
        provider=provider,
        max_passes=settings.subtitle_editor_max_passes,
        pass_threshold=settings.subtitle_editor_pass_threshold,
        max_retries=settings.subtitle_editor_max_retries,
        debug=settings.subtitle_debug,
    )
