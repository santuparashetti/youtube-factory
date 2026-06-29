from __future__ import annotations

from pathlib import Path


def subtitles_directory(project: str) -> Path:
    directory = (
        Path("workspace")
        / "jobs"
        / project
        / "subtitles"
    )

    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    return directory