from pathlib import Path


def video_directory(project: str) -> Path:
    directory = (
        Path("workspace")
        / "jobs"
        / project
        / "video"
    )

    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    return directory