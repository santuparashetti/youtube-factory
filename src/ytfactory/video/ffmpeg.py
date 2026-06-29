from __future__ import annotations

import subprocess
from pathlib import Path


class FFmpegRenderer:

    def render(
        self,
        image: Path,
        audio: Path,
        subtitle: Path,
        output: Path,
    ) -> None:

        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loop",
                "1",
                "-i",
                str(image),
                "-i",
                str(audio),
                "-vf",
                f"subtitles={subtitle}",
                "-c:v",
                "libx264",
                "-tune",
                "stillimage",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-pix_fmt",
                "yuv420p",
                "-shortest",
                str(output),
            ],
            check=True,
        )