from __future__ import annotations

import json
from pathlib import Path

from .artifacts import video_directory
from .ffmpeg import FFmpegRenderer


class VideoPipeline:

    def __init__(self):
        self.renderer = FFmpegRenderer()

    def run(
        self,
        project: str,
    ) -> None:

        scenes = json.loads(
            (
                Path("workspace")
                / "jobs"
                / project
                / "scenes"
                / "scene-plan.json"
            ).read_text()
        )["scenes"]

        for scene in scenes:

            self.renderer.render(
                image=(
                    Path("workspace")
                    / "jobs"
                    / project
                    / "images"
                    / f"scene-{scene['index']:03d}.png"
                ),
                audio=(
                    Path("workspace")
                    / "jobs"
                    / project
                    / "audio"
                    / f"scene-{scene['index']:03d}.mp3"
                ),
                subtitle=(
                    Path("workspace")
                    / "jobs"
                    / project
                    / "subtitles"
                    / f"scene-{scene['index']:03d}.srt"
                ),
                output=(
                    video_directory(project)
                    / f"scene-{scene['index']:03d}.mp4"
                ),
            )