"""
CaptionPipeline — standalone subtitle generation stage.

Delegates all subtitle logic to SubtitleEngine.

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

from .artifacts import subtitles_directory
from .models import CaptionArtifact
from .repository import CaptionRepository


class CaptionPipeline:
    def __init__(self):
        self.repository = CaptionRepository()

    def run(
        self,
        project: str,
    ) -> None:
        settings = Settings()
        engine = SubtitleEngine.from_settings(settings)
        use_ass = engine.format == SubtitleFormat.ASS

        project_dir = Path("workspace") / "jobs" / project
        scene_file = project_dir / "scenes" / "scene-plan.json"
        scenes = json.loads(scene_file.read_text(encoding="utf-8"))["scenes"]

        reports: list[SubtitleReport] = []

        for scene in scenes:
            index = scene["index"]
            srt_path = subtitles_directory(project) / f"scene-{index:03d}.srt"
            ass_path = subtitles_directory(project) / f"scene-{index:03d}.ass"

            # Skip if primary output already exists
            primary = ass_path if use_ass else srt_path
            if primary.exists():
                continue

            timing_file = project_dir / "audio" / f"scene-{index:03d}.timing.json"
            boundaries: list[dict] = []
            if timing_file.exists():
                data = timing_file.read_text(encoding="utf-8")
                boundaries = json.loads(data) if data.strip() else []

            total_duration = float(scene.get("duration_seconds", 10.0))

            if use_ass:
                ass, srt, report = engine.build_both(
                    boundaries=boundaries,
                    narration=scene["narration"],
                    scene_index=index,
                    project_id=project,
                    total_duration=total_duration,
                )
                ass_path.write_text(ass, encoding="utf-8")
                srt_path.write_text(srt, encoding="utf-8")
                artifact = CaptionArtifact(
                    scene_id=index,
                    srt_path=srt_path,
                    ass_path=ass_path,
                )
            else:
                srt, report = engine.build_report(
                    boundaries=boundaries,
                    narration=scene["narration"],
                    scene_index=index,
                    project_id=project,
                    total_duration=total_duration,
                )
                srt_path.write_text(srt, encoding="utf-8")
                artifact = CaptionArtifact(
                    scene_id=index,
                    srt_path=srt_path,
                )

            reports.append(report)
            self.repository.save(artifact)

        SubtitleDebugWriter.write_project_summary(
            project_id=project,
            reports=reports,
            enabled=settings.subtitle_debug,
        )
