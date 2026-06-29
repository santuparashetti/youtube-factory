from __future__ import annotations

import json
from pathlib import Path

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

        scene_file = (
            Path("workspace")
            / "jobs"
            / project
            / "scenes"
            / "scene-plan.json"
        )

        scenes = json.loads(
            scene_file.read_text(
                encoding="utf-8",
            )
        )["scenes"]

        for scene in scenes:

            output = (
                subtitles_directory(project)
                / f"scene-{scene['index']:03d}.srt"
            )

            duration = int(scene["duration_seconds"])

            output.write_text(
                f"""1
00:00:00,000 --> 00:00:{duration:02d},000
{scene["narration"]}
""",
                encoding="utf-8",
            )

            self.repository.save(
                CaptionArtifact(
                    scene_id=scene["index"],
                    srt_path=output,
                )
            )