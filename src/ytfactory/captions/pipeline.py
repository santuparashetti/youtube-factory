"""
CaptionPipeline — standalone subtitle generation stage.

Delegates all subtitle logic to SubtitleEngine.
The former duplicate _boundaries_to_srt / _fallback_srt functions
are no longer needed — they live in the engine's segmenter.
"""

from __future__ import annotations

import json
from pathlib import Path

from ytfactory.config.settings import Settings
from ytfactory.subtitles import SubtitleEngine
from ytfactory.subtitles.debug import SubtitleDebugWriter
from ytfactory.subtitles.models import SubtitleReport

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

        project_dir = Path("workspace") / "jobs" / project
        scene_file = project_dir / "scenes" / "scene-plan.json"
        scenes = json.loads(scene_file.read_text(encoding="utf-8"))["scenes"]

        reports: list[SubtitleReport] = []

        for scene in scenes:
            index = scene["index"]
            output = subtitles_directory(project) / f"scene-{index:03d}.srt"

            if output.exists():
                continue

            timing_file = project_dir / "audio" / f"scene-{index:03d}.timing.json"
            boundaries: list[dict] = []
            if timing_file.exists():
                data = timing_file.read_text(encoding="utf-8")
                boundaries = json.loads(data) if data.strip() else []

            srt, report = engine.build_report(
                boundaries=boundaries,
                narration=scene["narration"],
                scene_index=index,
                project_id=project,
                total_duration=float(scene.get("duration_seconds", 10.0)),
            )
            reports.append(report)

            output.write_text(srt, encoding="utf-8")

            self.repository.save(
                CaptionArtifact(
                    scene_id=index,
                    srt_path=output,
                )
            )

        SubtitleDebugWriter.write_project_summary(
            project_id=project,
            reports=reports,
            enabled=settings.subtitle_debug,
        )
