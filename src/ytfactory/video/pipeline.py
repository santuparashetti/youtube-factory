from __future__ import annotations

import json
from pathlib import Path

from rich.progress import track

from .artifacts import video_directory
from .ffmpeg import FFmpegRenderer


class VideoPipeline:
    """Render all scenes into individual YouTube-ready videos."""

    def __init__(self):
        self.renderer = FFmpegRenderer()

    def run(
        self,
        project: str,
    ) -> None:

        project_dir = (
            Path("workspace")
            / "jobs"
            / project
        )

        scene_plan = (
            project_dir
            / "scenes"
            / "scene-plan.json"
        )

        if not scene_plan.exists():
            raise FileNotFoundError(
                f"Missing scene plan: {scene_plan}"
            )

        with open(
            scene_plan,
            encoding="utf-8",
        ) as f:
            scenes = json.load(f)["scenes"]

        output_dir = video_directory(project)

        print(
            f"\nRendering {len(scenes)} video scenes...\n"
        )

        for scene in track(
            scenes,
            description="Rendering",
        ):

            index = scene["index"]

            image = (
                project_dir
                / "images"
                / f"scene-{index:03d}.png"
            )

            audio = (
                project_dir
                / "audio"
                / f"scene-{index:03d}.mp3"
            )

            subtitle = (
                project_dir
                / "subtitles"
                / f"scene-{index:03d}.srt"
            )

            output = (
                output_dir
                / f"scene-{index:03d}.mp4"
            )

            if not image.exists():
                raise FileNotFoundError(image)

            if not audio.exists():
                raise FileNotFoundError(audio)

            if not subtitle.exists():
                raise FileNotFoundError(subtitle)

            self.renderer.render(
                image=image,
                audio=audio,
                subtitle=subtitle,
                output=output,
            )

        print("\n✓ All videos rendered successfully.\n")