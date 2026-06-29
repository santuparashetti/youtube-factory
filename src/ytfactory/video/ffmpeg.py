from __future__ import annotations

import subprocess
from pathlib import Path

from ytfactory.config.settings import Settings


class FFmpegRenderer:
    """Render a single YouTube-ready video scene."""

    def __init__(self) -> None:
        self.settings = Settings()

    def render(
        self,
        image: Path,
        audio: Path,
        subtitle: Path,
        output: Path,
    ) -> None:

        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        width = self.settings.video_width
        height = self.settings.video_height
        fps = self.settings.video_fps

        vf = (
            f"scale={width}:{height}:"
            "force_original_aspect_ratio=increase,"
            f"crop={width}:{height},"
            f"subtitles='{subtitle}'"
        )

        subprocess.run(
            [
                "ffmpeg",
                "-y",

                # ---------- Input ----------
                "-loop",
                "1",
                "-framerate",
                str(fps),
                "-i",
                str(image),

                "-i",
                str(audio),

                # ---------- Video ----------
                "-vf",
                vf,

                "-r",
                str(fps),

                "-s",
                f"{width}x{height}",

                "-c:v",
                "libx264",

                "-preset",
                "medium",

                "-crf",
                "18",

                "-pix_fmt",
                "yuv420p",

                "-profile:v",
                "high",

                "-movflags",
                "+faststart",

                # ---------- Audio ----------
                "-c:a",
                "aac",

                "-b:a",
                "192k",

                "-ar",
                "48000",

                # ---------- Finish ----------
                "-shortest",

                str(output),
            ],
            check=True,
        )